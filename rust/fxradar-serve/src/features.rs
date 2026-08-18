//! Causal features from raw price windows — the exact semantics of `feature_spec.yaml`
//! (mirrors `src/fxradar/features.py`). No lookahead: row i uses rows <= i only.

use crate::error::{EngineError, Result};
use serde::{Deserialize, Serialize};

pub const ANNUALIZE: f64 = 15.874_507_866_387_544; // sqrt(252)
pub const WARMUP_ROWS: usize = 60;
pub const BASE_FEATURES: [&str; 8] = [
    "ret_1d",
    "vol_20",
    "vol_60",
    "vol_ratio",
    "mom_20",
    "rng_hl",
    "corr_20",
    "ret_5d_abs",
];

/// Raw daily bars for one pair, oldest first. `dates` are days since the Unix epoch.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PairWindow {
    pub pair: String,
    pub dates: Vec<i64>,
    pub close: Vec<f64>,
    pub high: Vec<f64>,
    pub low: Vec<f64>,
}

impl PairWindow {
    pub fn validate(&self) -> Result<()> {
        let n = self.dates.len();
        if self.close.len() != n || self.high.len() != n || self.low.len() != n {
            return Err(EngineError::RaggedWindow {
                pair: self.pair.clone(),
                dates: n,
                close: self.close.len(),
                high: self.high.len(),
                low: self.low.len(),
            });
        }
        Ok(())
    }
}

/// One day of base features (NaN where undefined, exactly like pandas).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct FeatureRow {
    pub date: i64,
    pub ret_1d: f64,
    pub vol_20: f64,
    pub vol_60: f64,
    pub vol_ratio: f64,
    pub mom_20: f64,
    pub rng_hl: f64,
    pub corr_20: f64,
    pub ret_5d_abs: f64,
}

impl FeatureRow {
    pub fn get(&self, name: &str) -> Option<f64> {
        Some(match name {
            "ret_1d" => self.ret_1d,
            "vol_20" => self.vol_20,
            "vol_60" => self.vol_60,
            "vol_ratio" => self.vol_ratio,
            "mom_20" => self.mom_20,
            "rng_hl" => self.rng_hl,
            "corr_20" => self.corr_20,
            "ret_5d_abs" => self.ret_5d_abs,
            _ => return None,
        })
    }
}

/// Sample standard deviation (ddof = 1) of a full slice; NaN if fewer than 2 values.
pub fn std_ddof1(x: &[f64]) -> f64 {
    let n = x.len();
    if n < 2 {
        return f64::NAN;
    }
    let mean = x.iter().sum::<f64>() / n as f64;
    let ss = x.iter().map(|v| (v - mean) * (v - mean)).sum::<f64>();
    (ss / (n as f64 - 1.0)).sqrt()
}

/// Pearson correlation of two equal-length slices; NaN if undefined (zero variance).
pub fn pearson(x: &[f64], y: &[f64]) -> f64 {
    let n = x.len();
    if n < 2 || y.len() != n {
        return f64::NAN;
    }
    let mx = x.iter().sum::<f64>() / n as f64;
    let my = y.iter().sum::<f64>() / n as f64;
    let (mut sxy, mut sxx, mut syy) = (0.0, 0.0, 0.0);
    for i in 0..n {
        let dx = x[i] - mx;
        let dy = y[i] - my;
        sxy += dx * dy;
        sxx += dx * dx;
        syy += dy * dy;
    }
    if sxx <= 0.0 || syy <= 0.0 {
        return f64::NAN;
    }
    sxy / (sxx.sqrt() * syy.sqrt())
}

/// log returns aligned to the window (index 0 is NaN).
pub fn log_returns(close: &[f64]) -> Vec<f64> {
    let mut r = vec![f64::NAN; close.len()];
    for i in 1..close.len() {
        r[i] = (close[i] / close[i - 1]).ln();
    }
    r
}

/// Rolling sample std over the last `w` values ending at each index; NaN until `w` non-NaN values.
fn rolling_std(x: &[f64], w: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    for i in 0..x.len() {
        if i + 1 >= w {
            let sl = &x[i + 1 - w..=i];
            if sl.iter().all(|v| v.is_finite()) {
                out[i] = std_ddof1(sl);
            }
        }
    }
    out
}

/// corr component of `target` with `other`: computed on the dates BOTH traded (returns non-NaN),
/// rolling 20 common days, then as-of aligned backward onto `target`'s own dates.
fn corr_component(
    target: &PairWindow,
    t_ret: &[f64],
    other: &PairWindow,
    o_ret: &[f64],
    flip_t: bool,
    flip_o: bool,
) -> Vec<f64> {
    // common dates with finite returns on both sides
    let mut oi = 0usize;
    let mut common: Vec<(i64, f64, f64)> = Vec::new();
    for (ti, &d) in target.dates.iter().enumerate() {
        while oi < other.dates.len() && other.dates[oi] < d {
            oi += 1;
        }
        if oi < other.dates.len()
            && other.dates[oi] == d
            && t_ret[ti].is_finite()
            && o_ret[oi].is_finite()
        {
            let a = if flip_t { -t_ret[ti] } else { t_ret[ti] };
            let b = if flip_o { -o_ret[oi] } else { o_ret[oi] };
            common.push((d, a, b));
        }
    }
    // rolling 20 correlation on the common calendar
    let w = 20usize;
    let mut corr_at: Vec<(i64, f64)> = Vec::with_capacity(common.len());
    for k in 0..common.len() {
        let v = if k + 1 >= w {
            let xa: Vec<f64> = common[k + 1 - w..=k].iter().map(|c| c.1).collect();
            let xb: Vec<f64> = common[k + 1 - w..=k].iter().map(|c| c.2).collect();
            pearson(&xa, &xb)
        } else {
            f64::NAN
        };
        corr_at.push((common[k].0, v));
    }
    // as-of backward onto target dates (carry the latest common value <= d, NaN kept as NaN)
    let mut out = vec![f64::NAN; target.dates.len()];
    let mut ci = 0usize;
    let mut last = f64::NAN;
    for (ti, &d) in target.dates.iter().enumerate() {
        while ci < corr_at.len() && corr_at[ci].0 <= d {
            last = corr_at[ci].1;
            ci += 1;
        }
        out[ti] = last;
    }
    out
}

/// Compute the base features of `pair` from windows of ALL pairs (corr_20 needs the others).
/// Returns rows AFTER the warm-up (the first `WARMUP_ROWS` rows are dropped, like Python).
pub fn build_features(
    windows: &[PairWindow],
    pair: &str,
    usd_base_pairs: &[String],
) -> Result<Vec<FeatureRow>> {
    for w in windows {
        w.validate()?;
    }
    let target = windows
        .iter()
        .find(|w| w.pair == pair)
        .ok_or_else(|| EngineError::UnknownPair(pair.to_string()))?;
    let n = target.dates.len();
    if n <= WARMUP_ROWS {
        return Err(EngineError::InsufficientHistory {
            pair: pair.to_string(),
            rows: n,
            need: WARMUP_ROWS + 1,
        });
    }
    let close = &target.close;
    let ret = log_returns(close);
    let vol20 = rolling_std(&ret, 20);
    let vol60 = rolling_std(&ret, 60);
    let vol5 = rolling_std(&ret, 5);

    let flip_t = usd_base_pairs.iter().any(|p| p == pair);
    let mut components: Vec<Vec<f64>> = Vec::new();
    for other in windows.iter().filter(|w| w.pair != pair) {
        let o_ret = log_returns(&other.close);
        let flip_o = usd_base_pairs.contains(&other.pair);
        components.push(corr_component(target, &ret, other, &o_ret, flip_t, flip_o));
    }

    let mut rows = Vec::with_capacity(n - WARMUP_ROWS);
    for i in WARMUP_ROWS..n {
        let mom = if i >= 20 {
            close[i] / close[i - 20] - 1.0
        } else {
            f64::NAN
        };
        let r5 = if i >= 5 {
            (close[i] / close[i - 5] - 1.0).abs()
        } else {
            f64::NAN
        };
        let rng = if i >= 9 {
            (i - 9..=i)
                .map(|j| (target.high[j] - target.low[j]) / target.close[j])
                .sum::<f64>()
                / 10.0
        } else {
            f64::NAN
        };
        let corr = if components.is_empty() {
            f64::NAN
        } else {
            let vals: Vec<f64> = components.iter().map(|c| c[i]).collect();
            if vals.iter().all(|v| v.is_finite()) {
                vals.iter().sum::<f64>() / vals.len() as f64
            } else {
                f64::NAN
            }
        };
        rows.push(FeatureRow {
            date: target.dates[i],
            ret_1d: ret[i],
            vol_20: vol20[i] * ANNUALIZE,
            vol_60: vol60[i] * ANNUALIZE,
            vol_ratio: (vol5[i] * ANNUALIZE) / (vol60[i] * ANNUALIZE),
            mom_20: mom,
            rng_hl: rng,
            corr_20: corr,
            ret_5d_abs: r5,
        });
    }
    Ok(rows)
}

/// sign(vol_20[i] - vol_20[i-10]) per feature row (0 when undefined), like Python's vol_trend.
pub fn vol_trend(rows: &[FeatureRow]) -> Vec<f64> {
    (0..rows.len())
        .map(|i| {
            if i >= 10 {
                let d = rows[i].vol_20 - rows[i - 10].vol_20;
                if d.is_nan() {
                    0.0
                } else if d > 0.0 {
                    1.0
                } else if d < 0.0 {
                    -1.0
                } else {
                    0.0
                }
            } else {
                0.0
            }
        })
        .collect()
}
