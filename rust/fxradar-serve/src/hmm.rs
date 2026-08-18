//! Gaussian HMM scoring: per-state log-likelihood with precomputed precisions/log-dets and the
//! forward filter with log-sum-exp. Filtered = P(state_t | obs <= t): causal by construction.

use crate::bundle::HmmParams;
use crate::error::{EngineError, Result};

const LN_2PI: f64 = 1.837_877_066_409_345_5;

/// Numerically stable log(sum(exp(x))).
pub fn logsumexp(x: &[f64]) -> f64 {
    let m = x.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
    if m == f64::NEG_INFINITY {
        return f64::NEG_INFINITY;
    }
    m + x.iter().map(|v| (v - m).exp()).sum::<f64>().ln()
}

/// log N(x | mu_k, Sigma_k) for each state, using Sigma_k^{-1} and log|Sigma_k| from the bundle.
pub fn frame_log_likelihood(p: &HmmParams, x: &[f64]) -> Result<Vec<f64>> {
    let d = x.len();
    let mut out = Vec::with_capacity(p.n_states);
    for k in 0..p.n_states {
        let mu = &p.means[k];
        let prec = &p.precisions[k];
        if mu.len() != d || prec.len() != d {
            return Err(EngineError::Shape(format!(
                "hmm state {k}: dim {d} vs means {}",
                mu.len()
            )));
        }
        let mut maha = 0.0;
        for i in 0..d {
            let di = x[i] - mu[i];
            for j in 0..d {
                maha += di * prec[i][j] * (x[j] - mu[j]);
            }
        }
        out.push(-0.5 * (d as f64 * LN_2PI + p.log_dets[k] + maha));
    }
    Ok(out)
}

/// Standardise a raw feature vector with the bundle's train-window scaler.
pub fn scale(p: &HmmParams, raw: &[f64]) -> Vec<f64> {
    raw.iter()
        .enumerate()
        .map(|(i, v)| (v - p.scaler_mean[i]) / p.scaler_scale[i])
        .collect()
}

/// Forward filter over a sequence of SCALED observations. Returns filtered probabilities per row.
pub fn filtered_probs(p: &HmmParams, x: &[Vec<f64>]) -> Result<Vec<Vec<f64>>> {
    let k = p.n_states;
    let log_a: Vec<Vec<f64>> = p
        .transmat
        .iter()
        .map(|row| row.iter().map(|v| v.max(1e-300).ln()).collect())
        .collect();
    let mut out = Vec::with_capacity(x.len());
    let mut log_alpha: Vec<f64> = vec![0.0; k];
    for (t, obs) in x.iter().enumerate() {
        let log_b = frame_log_likelihood(p, obs)?;
        let mut next = vec![0.0; k];
        if t == 0 {
            for j in 0..k {
                next[j] = p.startprob[j].max(1e-300).ln() + log_b[j];
            }
        } else {
            for j in 0..k {
                let terms: Vec<f64> = (0..k).map(|i| log_alpha[i] + log_a[i][j]).collect();
                next[j] = logsumexp(&terms) + log_b[j];
            }
        }
        let z = logsumexp(&next);
        for v in next.iter_mut() {
            *v -= z;
        }
        out.push(next.iter().map(|v| v.exp()).collect());
        log_alpha = next;
    }
    Ok(out)
}

pub fn argmax(v: &[f64]) -> usize {
    let mut best = 0;
    for (i, x) in v.iter().enumerate() {
        if *x > v[best] {
            best = i;
        }
    }
    best
}

/// -sum p log p in nats.
pub fn entropy(probs: &[f64]) -> f64 {
    -probs.iter().map(|p| p * p.max(1e-300).ln()).sum::<f64>()
}

/// Run length of the current label, counting today (1, 2, 3, ...).
pub fn run_lengths(labels: &[usize]) -> Vec<usize> {
    let mut out = Vec::with_capacity(labels.len());
    let mut run = 0usize;
    for (i, l) in labels.iter().enumerate() {
        if i > 0 && labels[i - 1] == *l {
            run += 1;
        } else {
            run = 1;
        }
        out.push(run);
    }
    out
}
