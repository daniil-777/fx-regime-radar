//! End-to-end scoring: raw windows -> features -> HMM -> forecaster.onnx -> siren.onnx.

use crate::bundle::Bundle;
use crate::error::{EngineError, Result};
use crate::features::{build_features, vol_trend, FeatureRow, PairWindow};
use crate::hmm;
use ort::session::Session;
use ort::value::Tensor;
use std::collections::BTreeMap;

/// The scored state of one pair on the last day of its window.
#[derive(Debug, Clone, PartialEq)]
pub struct ScoredRow {
    pub date: i64,
    pub pair: String,
    pub regime: String,
    pub regime_prob: f64,
    pub probs: BTreeMap<String, f64>,
    pub hmm_entropy: f64,
    pub days_in_regime: usize,
    pub vol_trend: f64,
    pub change_risk_5d: f64,
    pub change_risk_raw: f64,
    pub anomaly_score: f64,
    pub anomaly_pct: f64,
    pub features: BTreeMap<String, f64>,
}

/// Owns the bundle and the two ONNX sessions. Construct once, score many times.
pub struct Engine {
    pub bundle: Bundle,
    forecaster: Session,
    siren: Session,
}

fn platt(p: f64, a: f64, b: f64) -> f64 {
    let p = p.clamp(1e-6, 1.0 - 1e-6);
    let z = a * (p / (1.0 - p)).ln() + b;
    1.0 / (1.0 + (-z).exp())
}

/// searchsorted(sorted, x, side="right") / n * 100
fn percentile_of(sorted: &[f64], x: f64) -> f64 {
    let idx = sorted.partition_point(|v| *v <= x);
    idx as f64 / sorted.len() as f64 * 100.0
}

impl Engine {
    pub fn new(bundle: Bundle) -> Result<Self> {
        let forecaster = Session::builder()?.commit_from_file(bundle.path("forecaster.onnx"))?;
        let siren = Session::builder()?.commit_from_file(bundle.path("siren.onnx"))?;
        Ok(Self {
            bundle,
            forecaster,
            siren,
        })
    }

    /// Score the LAST day of `pair`'s window given windows for all pairs.
    pub fn score(&mut self, windows: &[PairWindow], pair: &str) -> Result<ScoredRow> {
        let spec = &self.bundle.spec;
        let rows: Vec<FeatureRow> = build_features(windows, pair, &spec.usd_base_pairs)?;
        let params = self
            .bundle
            .hmm
            .get(pair)
            .ok_or_else(|| EngineError::UnknownPair(pair.to_string()))?;
        // HMM over the whole (post warm-up) window
        let mut x: Vec<Vec<f64>> = Vec::with_capacity(rows.len());
        for r in &rows {
            let raw: Vec<f64> = params
                .features
                .iter()
                .map(|f| {
                    r.get(f)
                        .ok_or_else(|| EngineError::Shape(format!("unknown hmm feature {f}")))
                })
                .collect::<Result<_>>()?;
            x.push(hmm::scale(params, &raw));
        }
        let probs = hmm::filtered_probs(params, &x)?;
        let labels: Vec<usize> = probs.iter().map(|p| hmm::argmax(p)).collect();
        let runs = hmm::run_lengths(&labels);
        let vt = vol_trend(&rows);
        let last = rows.len() - 1;
        let regime = params.state_names[labels[last]].clone();
        let entropy = hmm::entropy(&probs[last]);

        // assemble named features for the last row
        let mut feats: BTreeMap<String, f64> = BTreeMap::new();
        for name in crate::features::BASE_FEATURES {
            if let Some(v) = rows[last].get(name) {
                feats.insert(name.to_string(), v);
            }
        }
        feats.insert("hmm_entropy".into(), entropy);
        feats.insert("days_in_regime".into(), runs[last] as f64);
        feats.insert("vol_trend".into(), vt[last]);
        for r in ["trend", "chop", "crisis"] {
            feats.insert(format!("regime_{r}"), if regime == r { 1.0 } else { 0.0 });
        }
        for p in ["GBPUSD", "USDCHF"] {
            feats.insert(format!("pair_{p}"), if pair == p { 1.0 } else { 0.0 });
        }

        // forecaster (float32 in, [1,2] probabilities out) + Platt calibration
        let fc = &self.bundle.forecaster;
        let xf: Vec<f32> =
            fc.features
                .iter()
                .map(|f| {
                    feats.get(f).copied().map(|v| v as f32).ok_or_else(|| {
                        EngineError::Shape(format!("missing forecaster feature {f}"))
                    })
                })
                .collect::<Result<_>>()?;
        let n_fc = xf.len();
        let input = Tensor::from_array(([1usize, n_fc], xf))?;
        let outputs = self
            .forecaster
            .run(ort::inputs![fc.onnx_input.as_str() => input])?;
        let (_, probs_fc) =
            outputs[fc.onnx_output_probabilities.as_str()].try_extract_tensor::<f32>()?;
        let p_raw = probs_fc
            .get(1)
            .copied()
            .ok_or_else(|| EngineError::Shape("forecaster output".into()))?
            as f64;
        let p_cal = platt(p_raw, fc.calibration.a, fc.calibration.b);

        // siren (float64 in/out) -> MSE -> percentile vs calm-train scores
        let si = &self.bundle.siren;
        let xs: Vec<f64> = si
            .features
            .iter()
            .enumerate()
            .map(|(i, f)| {
                feats
                    .get(f)
                    .copied()
                    .map(|v| (v - si.scaler_mean[i]) / si.scaler_scale[i])
                    .ok_or_else(|| EngineError::Shape(format!("missing siren feature {f}")))
            })
            .collect::<Result<_>>()?;
        let n_si = xs.len();
        let input = Tensor::from_array(([1usize, n_si], xs.clone()))?;
        let outputs = self
            .siren
            .run(ort::inputs![si.onnx_input.as_str() => input])?;
        let (_, recon) = outputs[si.onnx_output.as_str()].try_extract_tensor::<f64>()?;
        if recon.len() != n_si {
            return Err(EngineError::Shape(format!(
                "siren output len {} != {n_si}",
                recon.len()
            )));
        }
        let score = recon
            .iter()
            .zip(xs.iter())
            .map(|(r, x)| (r - x) * (r - x))
            .sum::<f64>()
            / n_si as f64;
        let pct = percentile_of(&si.train_scores_sorted, score);

        let mut named_probs = BTreeMap::new();
        for (k, name) in params.state_names.iter().enumerate() {
            named_probs.insert(name.clone(), probs[last][k]);
        }
        Ok(ScoredRow {
            date: rows[last].date,
            pair: pair.to_string(),
            regime,
            regime_prob: probs[last][labels[last]],
            probs: named_probs,
            hmm_entropy: entropy,
            days_in_regime: runs[last],
            vol_trend: vt[last],
            change_risk_5d: p_cal,
            change_risk_raw: p_raw,
            anomaly_score: score,
            anomaly_pct: pct,
            features: feats,
        })
    }
}
