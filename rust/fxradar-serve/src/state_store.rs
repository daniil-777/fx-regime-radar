//! Read-only view of the current artifacts (data/regimes.parquet) for `GET /api/regimes/{pair}`.
//! The service never writes; the Python pipeline owns the artifacts.

use crate::error::{EngineError, Result};
use parquet::file::reader::{FileReader, SerializedFileReader};
use parquet::record::Field;
use serde_json::{json, Map, Value};
use std::collections::BTreeMap;
use std::fs::File;
use std::path::Path;

fn field_to_json(f: &Field) -> Value {
    match f {
        Field::Null => Value::Null,
        Field::Bool(b) => json!(b),
        Field::Int(v) => json!(v),
        Field::Long(v) => json!(v),
        Field::Float(v) => json!(v),
        Field::Double(v) => json!(v),
        Field::Str(s) => json!(s),
        Field::TimestampMicros(v) => json!(days_to_iso(v.div_euclid(86_400_000_000))),
        Field::TimestampMillis(v) => json!(days_to_iso(v.div_euclid(86_400_000))),
        Field::Date(v) => json!(days_to_iso(*v as i64)),
        Field::ListInternal(l) => Value::Array(l.elements().iter().map(field_to_json).collect()),
        other => json!(other.to_string()),
    }
}

/// Civil date (YYYY-MM-DD) from days since the Unix epoch (Howard Hinnant's algorithm).
pub fn days_to_iso(days: i64) -> String {
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    format!("{y:04}-{m:02}-{d:02}")
}

/// Latest row per pair from regimes.parquet as JSON objects (all columns).
pub fn latest_regimes(path: &Path) -> Result<BTreeMap<String, Value>> {
    let file = File::open(path).map_err(|source| EngineError::Io {
        path: path.display().to_string(),
        source,
    })?;
    let reader = SerializedFileReader::new(file)?;
    let mut latest: BTreeMap<String, (i64, Value)> = BTreeMap::new();
    for row in reader.get_row_iter(None)? {
        let row = row?;
        let mut obj = Map::new();
        let mut pair = String::new();
        let mut date_key = i64::MIN;
        for (name, field) in row.get_column_iter() {
            if name == "pair" {
                if let Field::Str(s) = field {
                    pair = s.clone();
                }
            }
            if name == "date" {
                date_key = match field {
                    Field::TimestampMicros(v) => *v,
                    Field::TimestampMillis(v) => *v * 1000,
                    Field::Long(v) => *v,
                    Field::Date(v) => *v as i64 * 86_400_000_000,
                    _ => i64::MIN,
                };
                // pandas datetime64[ns] arrives as INT64 nanoseconds
                if date_key.abs() > 1_000_000_000_000_000 {
                    obj.insert(
                        "date".into(),
                        json!(days_to_iso(date_key.div_euclid(86_400_000_000_000))),
                    );
                    continue;
                }
            }
            obj.insert(name.clone(), field_to_json(field));
        }
        if pair.is_empty() {
            continue;
        }
        let newer = latest
            .get(&pair)
            .map(|(d, _)| date_key > *d)
            .unwrap_or(true);
        if newer {
            latest.insert(pair, (date_key, Value::Object(obj)));
        }
    }
    Ok(latest.into_iter().map(|(k, (_, v))| (k, v)).collect())
}
