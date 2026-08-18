use approx::assert_abs_diff_eq;
use fxradar_serve::features::{build_features, log_returns, std_ddof1, PairWindow, WARMUP_ROWS};
use fxradar_serve::hmm::logsumexp;

fn window(pair: &str, close: &[f64]) -> PairWindow {
    PairWindow {
        pair: pair.into(),
        dates: (0..close.len() as i64).collect(),
        close: close.to_vec(),
        high: close.iter().map(|c| c * 1.001).collect(),
        low: close.iter().map(|c| c * 0.999).collect(),
    }
}

fn synthetic(n: usize, seed: u64) -> Vec<f64> {
    // deterministic pseudo-random walk (LCG) — no rand dependency needed
    let mut s = seed;
    let mut c = 1.0;
    let mut out = Vec::with_capacity(n);
    for _ in 0..n {
        s = s
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        let u = ((s >> 11) as f64) / ((1u64 << 53) as f64) - 0.5;
        c *= (0.01 * u).exp();
        out.push(c);
    }
    out
}

#[test]
fn constant_prices_give_zero_returns_and_vol() {
    let w = vec![
        window("EURUSD", &[1.1; 100]),
        window("GBPUSD", &[1.3; 100]),
        window("USDCHF", &[0.9; 100]),
    ];
    let rows = build_features(&w, "EURUSD", &["USDCHF".to_string()]).unwrap();
    assert_eq!(rows.len(), 100 - WARMUP_ROWS);
    for r in &rows {
        assert_eq!(r.ret_1d, 0.0);
        assert_eq!(r.vol_20, 0.0);
        assert_eq!(r.mom_20, 0.0);
        assert_eq!(r.ret_5d_abs, 0.0);
        assert!(r.corr_20.is_nan()); // zero variance -> undefined, like pandas
    }
}

#[test]
fn hand_computed_vol_20_and_mom_20() {
    let close = synthetic(80, 1);
    let w = vec![
        window("EURUSD", &close),
        window("GBPUSD", &synthetic(80, 2)),
        window("USDCHF", &synthetic(80, 3)),
    ];
    let rows = build_features(&w, "EURUSD", &["USDCHF".to_string()]).unwrap();
    let last = rows.last().unwrap();
    let r = log_returns(&close);
    let expected_vol = std_ddof1(&r[r.len() - 20..]) * 252f64.sqrt();
    assert_abs_diff_eq!(last.vol_20, expected_vol, epsilon = 1e-12);
    assert_abs_diff_eq!(last.mom_20, close[79] / close[59] - 1.0, epsilon = 1e-12);
    assert_abs_diff_eq!(last.ret_1d, (close[79] / close[78]).ln(), epsilon = 1e-15);
    assert!(last.corr_20.is_finite() && last.corr_20.abs() <= 1.0);
}

#[test]
fn truncation_invariance() {
    let full = vec![
        window("EURUSD", &synthetic(300, 4)),
        window("GBPUSD", &synthetic(300, 5)),
        window("USDCHF", &synthetic(300, 6)),
    ];
    let cut: Vec<PairWindow> = full
        .iter()
        .map(|w| PairWindow {
            pair: w.pair.clone(),
            dates: w.dates[..270].to_vec(),
            close: w.close[..270].to_vec(),
            high: w.high[..270].to_vec(),
            low: w.low[..270].to_vec(),
        })
        .collect();
    let a = build_features(&full, "GBPUSD", &["USDCHF".to_string()]).unwrap();
    let b = build_features(&cut, "GBPUSD", &["USDCHF".to_string()]).unwrap();
    assert_eq!(b.len(), 270 - WARMUP_ROWS);
    for (x, y) in a.iter().zip(b.iter()) {
        assert_eq!(x, y, "features must not depend on the future");
    }
}

#[test]
fn logsumexp_is_stable() {
    assert_abs_diff_eq!(
        logsumexp(&[-1000.0, -1000.0]),
        -1000.0 + 2f64.ln(),
        epsilon = 1e-12
    );
    assert_abs_diff_eq!(
        logsumexp(&[1000.0, 1000.0]),
        1000.0 + 2f64.ln(),
        epsilon = 1e-9
    );
    assert!(logsumexp(&[f64::NEG_INFINITY, f64::NEG_INFINITY]).is_infinite());
    assert_abs_diff_eq!(logsumexp(&[0.0]), 0.0, epsilon = 1e-15);
}
