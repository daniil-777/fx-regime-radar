//! `fxradar-serve`: the production HTTP service. Startup order is law: load bundle → verify hashes
//! → run the full golden-vector self-test in-process → only then bind the port. Any failure logs
//! the diff table and exits nonzero. Handlers live in `fxradar_serve::app` and call the engine; no
//! model math lives in the service layer. Phase 24 adds keys (sqlite), alerts, docs and metrics
//! around the same gate — the gate itself is unchanged.

use clap::Parser;
use fxradar_serve::alerts::{self, AlertEngine, DeliveryConfig};
use fxradar_serve::app::{build_router, AppState, SelftestStatus};
use fxradar_serve::store::Store;
use fxradar_serve::{selftest, Bundle, Engine};
use std::net::SocketAddr;
use std::path::PathBuf;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tracing::{error, info, warn};

#[derive(Parser, Debug)]
#[command(
    name = "fxradar-serve",
    about = "FX Regime Radar — Rust scoring service"
)]
struct Args {
    /// Bundle directory (json/onnx/parquet)
    #[arg(long, default_value = "models/bundle_v1.4.0")]
    bundle: PathBuf,
    /// Artifact directory holding regimes.parquet (read-only)
    #[arg(long, default_value = "data")]
    data_dir: PathBuf,
    /// Bind address
    #[arg(long, default_value = "0.0.0.0:8080")]
    bind: SocketAddr,
    /// DEV ONLY: skip the golden-vector self-test at start-up (loudly logged)
    #[arg(long, default_value_t = false)]
    skip_selftest: bool,
    /// SQLite file for API keys / webhooks / alert state (a secret file, never committed)
    #[arg(long, env = "FXRADAR_KEYS_DB", default_value = "data/keys.db")]
    keys_db: PathBuf,
    /// Per-key rate limit, requests per minute (burst = same number)
    #[arg(long, env = "FXRADAR_RATE_LIMIT_PER_MIN", default_value_t = 60)]
    rate_limit_per_min: u32,
    /// Alert engine poll interval in seconds (0 disables the alert engine)
    #[arg(long, env = "FXRADAR_ALERT_POLL_SECS", default_value_t = 300)]
    alert_poll_secs: u64,
}

// ---------------------------------------------------------------------------------------------
// startup gate
// ---------------------------------------------------------------------------------------------
fn gate(args: &Args) -> Result<(Engine, SelftestStatus), Box<dyn std::error::Error>> {
    info!(bundle = %args.bundle.display(), "loading bundle and verifying manifest hashes");
    let bundle = Bundle::load(&args.bundle)?;
    info!(version = %bundle.manifest.bundle_version, commit = %bundle.manifest.git_commit, files = bundle.manifest.files.len(), "bundle hashes verified");
    let mut engine = Engine::new(bundle)?;
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or(Duration::ZERO)
        .as_secs();
    if args.skip_selftest {
        warn!("SELF-TEST SKIPPED (--skip-selftest). This binary has NOT proven parity with research. Dev only.");
        return Ok((
            engine,
            SelftestStatus {
                status: "skipped".into(),
                goldens: 0,
                at_unix: now,
                worst: vec![],
            },
        ));
    }
    let n = selftest::read_goldens(&engine)?.len();
    let (table, ok) = selftest::run(&mut engine)?;
    let rendered = selftest::format_table(&table, n);
    if !ok {
        for line in rendered.lines() {
            error!("{line}");
        }
        error!("REFUSING TO START: outputs diverge from the golden vectors");
        return Err("selftest failed".into());
    }
    for line in rendered.lines() {
        info!("{line}");
    }
    let mut worst: Vec<(String, f64)> = table
        .iter()
        .map(|r| (r.output.clone(), r.max_abs_diff))
        .collect();
    worst.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    worst.truncate(5);
    info!(goldens = n, "self-test PASSED — binding port");
    Ok((
        engine,
        SelftestStatus {
            status: "pass".into(),
            goldens: n,
            at_unix: now,
            worst,
        },
    ))
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info,tower_http=info".into()),
        )
        .init();
    let args = Args::parse();
    let (engine, status) = match gate(&args) {
        Ok(v) => v,
        Err(e) => {
            error!("startup gate failed: {e}");
            std::process::exit(1);
        }
    };
    // ---- phase 24: service layer around the gated engine -------------------------------------
    let store = Store::open(&args.keys_db)?;
    info!(db = %args.keys_db.display(), keys = store.list_keys()?.len(), "key store opened");
    let stripe_secret = std::env::var("STRIPE_WEBHOOK_SECRET")
        .ok()
        .filter(|s| !s.trim().is_empty());
    if stripe_secret.is_some() {
        info!("stripe webhook secret configured (value not logged)");
    } else {
        warn!("STRIPE_WEBHOOK_SECRET not set: POST /api/stripe/webhook answers 503");
    }
    // touch the metrics recorder so /metrics renders even before the first request
    let _ = fxradar_serve::metrics::handle();
    let state = AppState::new(
        Some(engine),
        store.clone(),
        args.data_dir.clone(),
        status,
        args.rate_limit_per_min,
        stripe_secret,
    );
    if args.alert_poll_secs > 0 {
        let engine = AlertEngine::new(
            store,
            alerts::parquet_source(args.data_dir.join("regimes.parquet")),
            &args.data_dir,
            DeliveryConfig::default(),
        );
        engine.spawn_worker();
        info!(
            every_s = args.alert_poll_secs,
            "alert engine started (evaluates once now, then on the interval)"
        );
        tokio::spawn(engine.run(Duration::from_secs(args.alert_poll_secs)));
    } else {
        warn!("alert engine disabled (--alert-poll-secs 0)");
    }
    let app = build_router(state);
    let listener = tokio::net::TcpListener::bind(args.bind).await?;
    info!(addr = %args.bind, "fxradar-serve listening (docs at /docs, metrics at /metrics)");
    axum::serve(listener, app)
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await?;
    Ok(())
}
