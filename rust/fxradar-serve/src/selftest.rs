//! Replay every golden vector end-to-end and compare with Python's exact outputs.

use crate::error::{EngineError, Result};
use crate::features::PairWindow;
use crate::infer::Engine;
use parquet::file::reader::{FileReader, SerializedFileReader};
use parquet::record::{Field, Row};
use std::collections::BTreeMap;
use std::fs::File;

pub const FEATURE_TOL: f64 = 1e-8;
pub const OUTPUT_TOL: f64 = 1e-6;

/// One golden row: raw windows + Python's expected values.
#[derive(Debug, Clone)]
pub struct Golden {
    pub date: i64,
    pub pair: String,
    pub windows: Vec<PairWindow>,
    pub expected: BTreeMap<String, f64>,
    pub regime: String,
}

fn field_f64(f: &Field) -> Option<f64> {
    match f {
        Field::Double(v) => Some(*v),
        Field::Float(v) => Some(*v as f64),
        Field::Long(v) => Some(*v as f64),
        Field::Int(v) => Some(*v as f64),
        _ => None,
    }
}

/// Days since the Unix epoch from whatever timestamp encoding the writer used (pandas writes
/// datetime64[ns] as INT64 nanoseconds; other writers use micros/millis/DATE).
fn field_days(f: &Field) -> Option<i64> {
    match f {
        Field::TimestampMicros(v) => Some(v.div_euclid(86_400_000_000)),
        Field::TimestampMillis(v) => Some(v.div_euclid(86_400_000)),
        Field::Date(v) => Some(*v as i64),
        Field::Long(v) => Some(if v.abs() > 1_000_000_000_000_000 {
            v.div_euclid(86_400_000_000_000) // nanoseconds
        } else if v.abs() > 1_000_000_000_000 {
            v.div_euclid(86_400_000_000) // microseconds
        } else if v.abs() > 1_000_000_000 {
            v.div_euclid(86_400_000) // milliseconds
        } else {
            *v // already days
        }),
        _ => None,
    }
}

fn list_f64(f: &Field, row: usize, col: &str) -> Result<Vec<f64>> {
    match f {
        Field::ListInternal(list) => list
            .elements()
            .iter()
            .map(|e| field_f64(e).ok_or_else(|| EngineError::Golden { row, column: col.into(), reason: "non-numeric element".into() }))
            .collect(),
        _ => Err(EngineError::Golden { row, column: col.into(), reason: "not a list".into() }),
    }
}

fn parse_row(row: &Row, idx: usize, pairs: &[String]) -> Result<Golden> {
    let mut cols: BTreeMap<String, Field> = BTreeMap::new();
    for (name, field) in row.get_column_iter() {
        cols.insert(name.clone(), field.clone());
    }
    let get = |c: &str| cols.get(c).ok_or_else(|| EngineError::Golden { row: idx, column: c.into(), reason: "missing".into() });
    let date = field_days(get("date")?).ok_or_else(|| EngineError::Golden { row: idx, column: "date".into(), reason: "not a timestamp".into() })?;
    let pair = match get("pair")? {
        Field::Str(s) => s.clone(),
        _ => return Err(EngineError::Golden { row: idx, column: "pair".into(), reason: "not a string".into() }),
    };
    let regime = match get("regime")? {
        Field::Str(s) => s.clone(),
        _ => return Err(EngineError::Golden { row: idx, column: "regime".into(), reason: "not a string".into() }),
    };
    let mut windows = Vec::new();
    for p in pairs {
        let dates = list_f64(get(&format!("{p}_dates"))?, idx, &format!("{p}_dates"))?.into_iter().map(|v| v as i64).collect();
        windows.push(PairWindow {
            pair: p.clone(),
            dates,
            close: list_f64(get(&format!("{p}_close"))?, idx, &format!("{p}_close"))?,
            high: list_f64(get(&format!("{p}_high"))?, idx, &format!("{p}_high"))?,
            low: list_f64(get(&format!("{p}_low"))?, idx, &format!("{p}_low"))?,
        });
    }
    let mut expected = BTreeMap::new();
    for (name, field) in &cols {
        if name.starts_with("feat_") || name.starts_with("prob_") || matches!(name.as_str(), "regime_prob" | "hmm_entropy" | "days_in_regime" | "change_risk_5d" | "anomaly_score" | "anomaly_pct") {
            if let Some(v) = field_f64(field) {
                expected.insert(name.clone(), v);
            }
        }
    }
    Ok(Golden { date, pair, windows, expected, regime })
}

/// Read goldens.parquet from the bundle directory.
pub fn read_goldens(engine: &Engine) -> Result<Vec<Golden>> {
    let path = engine.bundle.path("goldens.parquet");
    let file = File::open(&path).map_err(|source| EngineError::Io { path: path.display().to_string(), source })?;
    let reader = SerializedFileReader::new(file)?;
    let pairs = engine.bundle.spec.pairs.clone();
    let mut out = Vec::new();
    for (i, row) in reader.get_row_iter(None)?.enumerate() {
        out.push(parse_row(&row?, i, &pairs)?);
    }
    Ok(out)
}

/// Per-output max absolute difference and tolerance.
#[derive(Debug, Clone)]
pub struct DiffRow {
    pub output: String,
    pub max_abs_diff: f64,
    pub tolerance: f64,
    pub ok: bool,
}

/// Replay every golden through the engine; returns the diff table (sorted) and overall pass flag.
pub fn run(engine: &mut Engine) -> Result<(Vec<DiffRow>, bool)> {
    let goldens = read_goldens(engine)?;
    if goldens.is_empty() {
        return Err(EngineError::SelfTest("no golden vectors".into()));
    }
    let n_train = engine.bundle.siren.train_scores_sorted.len() as f64;
    let mut diffs: BTreeMap<String, f64> = BTreeMap::new();
    let mut upd = |name: &str, d: f64| {
        let e = diffs.entry(name.to_string()).or_insert(0.0);
        if d > *e {
            *e = d;
        }
    };
    for g in &goldens {
        let s = engine.score(&g.windows, &g.pair)?;
        for (name, exp) in &g.expected {
            let got = if let Some(f) = name.strip_prefix("feat_") {
                s.features.get(f).copied()
            } else if let Some(r) = name.strip_prefix("prob_") {
                s.probs.get(r).copied()
            } else {
                match name.as_str() {
                    "regime_prob" => Some(s.regime_prob),
                    "hmm_entropy" => Some(s.hmm_entropy),
                    "days_in_regime" => Some(s.days_in_regime as f64),
                    "change_risk_5d" => Some(s.change_risk_5d),
                    "anomaly_score" => Some(s.anomaly_score),
                    "anomaly_pct" => Some(s.anomaly_pct),
                    _ => None,
                }
            };
            match got {
                Some(v) => upd(name, (v - exp).abs()),
                None => upd(name, f64::INFINITY),
            }
        }
        upd("regime_mismatch", if s.regime == g.regime { 0.0 } else { 1.0 });
        if s.date != g.date {
            upd("date_mismatch", 1.0);
        }
    }
    let mut table = Vec::new();
    let mut all_ok = true;
    for (name, d) in diffs {
        let tol = if name.starts_with("feat_") {
            FEATURE_TOL
        } else if name == "anomaly_pct" {
            100.0 / n_train + 1e-9 // rank statistic: one rank step (see docs/bundle_format.md)
        } else if name.ends_with("_mismatch") {
            0.0
        } else {
            OUTPUT_TOL
        };
        let ok = d <= tol;
        all_ok &= ok;
        table.push(DiffRow { output: name, max_abs_diff: d, tolerance: tol, ok });
    }
    Ok((table, all_ok))
}

/// Render the diff table as text (for logs).
pub fn format_table(table: &[DiffRow], n_goldens: usize) -> String {
    let mut s = format!("{:<22} {:>14} {:>12}  ok   ({} goldens)\n", "output", "max_abs_diff", "tolerance", n_goldens);
    for r in table {
        s.push_str(&format!("{:<22} {:>14.3e} {:>12.3e}  {}\n", r.output, r.max_abs_diff, r.tolerance, if r.ok { "✓" } else { "✗" }));
    }
    s
}
