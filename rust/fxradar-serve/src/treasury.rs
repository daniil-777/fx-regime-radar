//! `GET /api/treasury` support (phase 25 req 4): read `data/treasury_risk.json` written by the
//! Python pipeline and do ARITHMETIC ONLY — ES in notional = amount × es × sqrt(weeks). No model
//! math lives here; if the artifact is absent the handler answers 404.

use serde_json::{json, Value};
use std::path::Path;

pub const DISCLAIMER: &str = "Educational tool. Not investment advice.";

#[derive(Debug, Clone, Default, serde::Deserialize, utoipa::IntoParams)]
pub struct TreasuryQuery {
    /// Pair, e.g. EURUSD (omit to get the whole artifact)
    pub pair: Option<String>,
    /// Exposure amount in quote currency units (any positive number)
    pub amount: Option<f64>,
    /// Horizon in weeks (1–12); the artifact's table is one week
    pub weeks: Option<f64>,
    /// Confidence level, 0.95 or 0.99 (default 0.95)
    pub level: Option<f64>,
}

#[derive(Debug, thiserror::Error)]
pub enum TreasuryError {
    #[error("treasury_risk.json not found — run the pipeline")]
    Missing,
    #[error("treasury_risk.json unreadable: {0}")]
    Unreadable(String),
    #[error("{0}")]
    BadQuery(String),
}

pub fn load(path: &Path) -> Result<Value, TreasuryError> {
    if !path.exists() {
        return Err(TreasuryError::Missing);
    }
    let raw =
        std::fs::read_to_string(path).map_err(|e| TreasuryError::Unreadable(e.to_string()))?;
    serde_json::from_str(&raw).map_err(|e| TreasuryError::Unreadable(e.to_string()))
}

fn level_key(prefix: &str, level: f64) -> String {
    // 0.95 -> "es_95", 0.99 -> "es_99", 0.975 -> "es_97.5"
    let pct = level * 100.0;
    if (pct - pct.round()).abs() < 1e-9 {
        format!("{prefix}_{}", pct.round() as i64)
    } else {
        format!("{prefix}_{pct}")
    }
}

/// Build the response: the artifact as-is, plus an optional notional calculation.
pub fn respond(artifact: &Value, q: &TreasuryQuery) -> Result<Value, TreasuryError> {
    let mut out = json!({
        "disclaimer": DISCLAIMER,
        "source": "data/treasury_risk.json",
        "artifact": artifact,
    });
    let Some(pair) = q.pair.as_deref() else {
        return Ok(out);
    };
    let pair = pair.to_ascii_uppercase();
    let entry = artifact
        .get("pairs")
        .and_then(|p| p.get(&pair))
        .ok_or_else(|| TreasuryError::BadQuery(format!("pair {pair} not in artifact")))?;
    let regime = entry
        .get("current_regime")
        .and_then(|v| v.as_str())
        .unwrap_or("n/a")
        .to_string();
    let level = q.level.unwrap_or(0.95);
    if !(0.5..1.0).contains(&level) {
        return Err(TreasuryError::BadQuery("level must be in [0.5, 1)".into()));
    }
    let weeks = q.weeks.unwrap_or(1.0);
    if !(weeks > 0.0 && weeks <= 12.0) {
        return Err(TreasuryError::BadQuery("weeks must be in (0, 12]".into()));
    }
    let amount = q.amount.unwrap_or(1.0);
    if !(amount >= 0.0 && amount.is_finite()) {
        return Err(TreasuryError::BadQuery("amount must be >= 0".into()));
    }
    let row = entry.get("table").and_then(|t| t.get(&regime));
    let es_key = level_key("es", level);
    let var_key = level_key("var", level);
    let es = row.and_then(|r| r.get(&es_key)).and_then(|v| v.as_f64());
    let var = row.and_then(|r| r.get(&var_key)).and_then(|v| v.as_f64());
    let scale = weeks.sqrt();
    let calc = json!({
        "pair": pair,
        "regime": regime,
        "level": level,
        "weeks": weeks,
        "amount": amount,
        "es_1w": es,
        "var_1w": var,
        "es_horizon": es.map(|e| e * scale),
        "var_horizon": var.map(|v| v * scale),
        "es_notional": es.map(|e| amount * e * scale),
        "var_notional": var.map(|v| amount * v * scale),
        "formula": "notional = amount × es_1w × sqrt(weeks) (square-root-of-time scaling of the artifact's one-week number; arithmetic only)",
    });
    if let Some(obj) = out.as_object_mut() {
        obj.insert("calc".into(), calc);
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn artifact() -> Value {
        json!({
            "generated_at_utc": "2026-08-18T06:00:00Z",
            "levels": [0.95, 0.99],
            "horizon_days": 5,
            "pairs": {"EURUSD": {"current_regime": "calm",
                "table": {"calm": {"var_95": 0.01, "es_95": 0.0123, "var_99": 0.02, "es_99": 0.03}}}}
        })
    }

    #[test]
    fn passthrough_without_pair() {
        let out = respond(&artifact(), &TreasuryQuery::default()).unwrap();
        assert_eq!(out["disclaimer"], DISCLAIMER);
        assert_eq!(out["artifact"]["horizon_days"], 5);
        assert!(out.get("calc").is_none());
    }

    #[test]
    fn notional_is_amount_times_es_times_sqrt_weeks() {
        let q = TreasuryQuery {
            pair: Some("eurusd".into()),
            amount: Some(800_000.0),
            weeks: Some(4.0),
            level: Some(0.99),
        };
        let out = respond(&artifact(), &q).unwrap();
        let es_notional = out["calc"]["es_notional"].as_f64().unwrap();
        assert!((es_notional - 800_000.0 * 0.03 * 2.0).abs() < 1e-6);
        assert_eq!(out["calc"]["regime"], "calm");
        assert!(respond(
            &artifact(),
            &TreasuryQuery {
                pair: Some("XXXYYY".into()),
                ..Default::default()
            }
        )
        .is_err());
    }
}
