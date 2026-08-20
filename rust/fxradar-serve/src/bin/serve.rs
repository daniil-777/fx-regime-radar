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
    /// Avatar feature flag: "on" | "off" (phase 35). Off → every /avatar/* route answers 503.
    #[arg(long, env = "FXRADAR_AVATAR", default_value = "off")]
    avatar: String,
    /// Static vendor token for POST /avatar/brain and /avatar/heartbeat (never logged)
    #[arg(long, env = "FXRADAR_AVATAR_BRAIN_TOKEN", hide_env_values = true)]
    avatar_brain_token: Option<String>,
    /// Default avatar vendor: local | anam | heygen
    #[arg(long, env = "FXRADAR_AVATAR_VENDOR", default_value = "local")]
    avatar_vendor: String,
    /// Monthly avatar session cap (cost control)
    #[arg(long, env = "FXRADAR_AVATAR_MAX_SESSIONS_MONTH", default_value_t = 300)]
    avatar_max_sessions_month: i64,
    /// Monthly avatar minutes cap (cost control)
    #[arg(
        long,
        env = "FXRADAR_AVATAR_MAX_MINUTES_MONTH",
        default_value_t = 600.0
    )]
    avatar_max_minutes_month: f64,
    /// Versioned avatar system prompt file (default: v1, or v2 when FXRADAR_AVATAR_OPEN=1)
    #[arg(long, env = "FXRADAR_AVATAR_SYSTEM_PROMPT")]
    avatar_system_prompt: Option<PathBuf>,
    /// ElevenLabs voice id for POST /avatar/tts
    #[arg(
        long,
        env = "FXRADAR_AVATAR_VOICE_ID",
        default_value = "21m00Tcm4TlvDq8ikWAM"
    )]
    avatar_voice_id: String,
    /// Monthly TTS character cap (cost control)
    #[arg(
        long,
        env = "FXRADAR_AVATAR_MAX_TTS_CHARS_MONTH",
        default_value_t = 100_000
    )]
    avatar_max_tts_chars_month: i64,
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
    // ---- phase 35: avatar layer (flag off by default; every /avatar/* route answers 503) -----
    let env_opt = |k: &str| std::env::var(k).ok().filter(|s| !s.trim().is_empty());
    let avatar_dev = std::env::var("FXRADAR_AVATAR_DEV").as_deref() == Ok("1");
    let avatar_open = std::env::var("FXRADAR_AVATAR_OPEN").as_deref() == Ok("1");
    let avatar_advice = std::env::var("FXRADAR_AVATAR_ADVICE").as_deref() == Ok("1");
    if avatar_advice {
        info!("avatar advice mode ON: hedging decision support comes from data/decision_table.json (deterministic; the LLM never writes advice)");
    }
    if avatar_dev {
        warn!("FXRADAR_AVATAR_DEV=1: /avatar/session-token waives the API key for the LOCAL vendor. DEV ONLY — never set this in production.");
    }
    let avatar_cfg = fxradar_serve::avatar::AvatarCfg {
        enabled: args.avatar.trim().eq_ignore_ascii_case("on"),
        brain_token: args
            .avatar_brain_token
            .clone()
            .filter(|s| !s.trim().is_empty()),
        vendor_default: args.avatar_vendor.clone(),
        max_sessions_month: args.avatar_max_sessions_month,
        max_minutes_month: args.avatar_max_minutes_month,
        anthropic_key: env_opt("ANTHROPIC_API_KEY"),
        anam_key: env_opt("ANAM_API_KEY"),
        anam_avatar_id: std::env::var("FXRADAR_AVATAR_ANAM_AVATAR_ID")
            .unwrap_or_else(|_| "30fa96d0-26c4-4e55-94a0-517025942e18".into()),
        anam_avatar_model: std::env::var("FXRADAR_AVATAR_ANAM_AVATAR_MODEL")
            .unwrap_or_else(|_| "cara-4".into()),
        anam_voice_id: std::env::var("FXRADAR_AVATAR_ANAM_VOICE_ID")
            .unwrap_or_else(|_| "6bfbe25a-979d-40f3-a92b-5394170af54b".into()),
        heygen_key: env_opt("HEYGEN_API_KEY"),
        system_prompt_path: args
            .avatar_system_prompt
            .clone()
            .unwrap_or_else(|| fxradar_serve::avatar::default_system_prompt(avatar_open)),
        open: avatar_open,
        elevenlabs_key: env_opt("ELEVENLABS_API_KEY"),
        voice_id: args.avatar_voice_id.clone(),
        max_tts_chars_month: args.avatar_max_tts_chars_month,
        advice: avatar_advice,
        dev: avatar_dev,
        test_hook: cfg!(debug_assertions)
            || std::env::var("FXRADAR_AVATAR_TEST").as_deref() == Ok("1"),
    };
    if avatar_cfg.enabled {
        info!(
            vendor = %avatar_cfg.vendor_default,
            llm = avatar_cfg.anthropic_key.is_some(),
            "avatar enabled (brain gated by direction lint + numeric grounding)"
        );
    }
    let state = AppState::new(
        Some(engine),
        store.clone(),
        args.data_dir.clone(),
        status,
        args.rate_limit_per_min,
        stripe_secret,
    )
    .with_avatar(avatar_cfg);
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
