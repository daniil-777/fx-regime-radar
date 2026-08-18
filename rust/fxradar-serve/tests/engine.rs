//! Integration test against the committed bundle: load, verify, score a golden, and check the
//! self-test passes. Skips (passes trivially) if the bundle is not present in the checkout.

use fxradar_serve::{selftest, Bundle, Engine};
use std::path::Path;

fn bundle_dir() -> Option<String> {
    let candidates = ["../../models/bundle_v1.4.0", "models/bundle_v1.4.0"];
    candidates
        .iter()
        .find(|p| Path::new(p).join("manifest.json").exists())
        .map(|s| s.to_string())
}

#[test]
fn bundle_loads_and_goldens_replay() {
    let Some(dir) = bundle_dir() else { return };
    let bundle = Bundle::load(&dir).expect("bundle loads and hashes verify");
    assert_eq!(bundle.spec.pairs.len(), 3);
    let mut engine = Engine::new(bundle).expect("engine");
    let goldens = selftest::read_goldens(&engine).expect("goldens");
    assert!(goldens.len() >= 300);
    let g = &goldens[0];
    let row = engine.score(&g.windows, &g.pair).expect("score");
    assert_eq!(row.regime, g.regime);
    assert!((row.change_risk_5d - g.expected["change_risk_5d"]).abs() < 1e-6);
    let (table, ok) = selftest::run(&mut engine).expect("selftest runs");
    assert!(ok, "{}", selftest::format_table(&table, goldens.len()));
}

#[test]
fn tampered_manifest_is_refused() {
    let Some(dir) = bundle_dir() else { return };
    let tmp = std::env::temp_dir().join("fxradar_bad_bundle_test");
    let _ = std::fs::remove_dir_all(&tmp);
    std::fs::create_dir_all(&tmp).unwrap();
    for entry in std::fs::read_dir(&dir).unwrap() {
        let e = entry.unwrap();
        std::fs::copy(e.path(), tmp.join(e.file_name())).unwrap();
    }
    let sidecar = tmp.join("forecaster.json");
    let mut txt = std::fs::read_to_string(&sidecar).unwrap();
    txt.push(' ');
    std::fs::write(&sidecar, txt).unwrap();
    let err = Bundle::load(&tmp).expect_err("must refuse");
    assert!(
        err.to_string()
            .contains("SHA-256 mismatch for forecaster.json"),
        "{err}"
    );
}
