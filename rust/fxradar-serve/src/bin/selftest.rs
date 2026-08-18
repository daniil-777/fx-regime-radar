//! `selftest <bundle_dir>`: load + hash-verify the bundle, replay all goldens, print the diff
//! table, exit nonzero on any divergence beyond tolerance.

use fxradar_serve::{selftest, Bundle, Engine};
use std::process::ExitCode;

fn main() -> ExitCode {
    let dir = std::env::args().nth(1).unwrap_or_else(|| "models/bundle_v1.4.0".to_string());
    match run(&dir) {
        Ok(true) => ExitCode::SUCCESS,
        Ok(false) => {
            eprintln!("SELFTEST FAILED: outputs diverge from the goldens");
            ExitCode::from(2)
        }
        Err(e) => {
            eprintln!("SELFTEST ERROR: {e}");
            ExitCode::from(1)
        }
    }
}

fn run(dir: &str) -> Result<bool, Box<dyn std::error::Error>> {
    let bundle = Bundle::load(dir)?;
    println!(
        "bundle v{} ({} @ {}) — hashes verified for {} files",
        bundle.manifest.bundle_version,
        bundle.manifest.git_commit,
        bundle.manifest.created_at,
        bundle.manifest.files.len()
    );
    let mut engine = Engine::new(bundle)?;
    let n = selftest::read_goldens(&engine)?.len();
    let (table, ok) = selftest::run(&mut engine)?;
    print!("{}", selftest::format_table(&table, n));
    println!("{}", if ok { "PASS" } else { "FAIL" });
    Ok(ok)
}
