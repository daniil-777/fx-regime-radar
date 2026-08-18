//! `fxradar-serve`: the production HTTP service. Startup order is law: load bundle → verify hashes
//! → run the full golden-vector self-test in-process → only then bind the port. Any failure logs
//! the diff table and exits nonzero. Handlers call the engine; no model math lives here.

use axum::extract::{Path as AxPath, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use clap::Parser;
use fxradar_serve::features::PairWindow;
use fxradar_serve::{selftest, state_store, Bundle, Engine, ScoredRow};
use serde::{Deserialize, Serialize};
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tower_http::trace::TraceLayer;
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
}

#[derive(Clone)]
struct AppState {
    engine: Arc<Mutex<Engine>>,
    data_dir: PathBuf,
    started: Instant,
    selftest: SelftestStatus,
    latencies: Arc<Mutex<Latencies>>,
    bundle_version: String,
    git_commit: String,
}

#[derive(Clone, Serialize)]
struct SelftestStatus {
    status: String, // "pass" | "skipped"
    goldens: usize,
    at_unix: u64,
    worst: Vec<(String, f64)>,
}

/// Bounded in-memory latency samples for p50/p99 on /api/score.
#[derive(Default)]
struct Latencies {
    samples_us: Vec<u64>,
    count: u64,
}

impl Latencies {
    fn record(&mut self, us: u64) {
        self.count += 1;
        if self.samples_us.len() >= 10_000 {
            self.samples_us.remove(0);
        }
        self.samples_us.push(us);
    }
    fn quantile(&self, q: f64) -> Option<u64> {
        if self.samples_us.is_empty() {
            return None;
        }
        let mut v = self.samples_us.clone();
        v.sort_unstable();
        let idx = ((v.len() as f64 - 1.0) * q).round() as usize;
        v.get(idx).copied()
    }
}

// ---------------------------------------------------------------------------------------------
// errors -> JSON with status codes
// ---------------------------------------------------------------------------------------------
struct ApiError(StatusCode, String);

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let body = serde_json::json!({"error": self.1, "status": self.0.as_u16()});
        (self.0, Json(body)).into_response()
    }
}

impl From<fxradar_serve::EngineError> for ApiError {
    fn from(e: fxradar_serve::EngineError) -> Self {
        use fxradar_serve::EngineError as E;
        let code = match &e {
            E::UnknownPair(_)
            | E::InsufficientHistory { .. }
            | E::RaggedWindow { .. }
            | E::Shape(_) => StatusCode::BAD_REQUEST,
            E::Io { .. } | E::Parquet(_) => StatusCode::SERVICE_UNAVAILABLE,
            _ => StatusCode::INTERNAL_SERVER_ERROR,
        };
        ApiError(code, e.to_string())
    }
}

// ---------------------------------------------------------------------------------------------
// handlers (thin: they call the engine)
// ---------------------------------------------------------------------------------------------
async fn health(State(st): State<AppState>) -> Json<serde_json::Value> {
    let lat = st
        .latencies
        .lock()
        .map(|l| (l.count, l.quantile(0.5), l.quantile(0.99)))
        .unwrap_or((0, None, None));
    Json(serde_json::json!({
        "service": "fxradar-serve",
        "version": env!("CARGO_PKG_VERSION"),
        "bundle_version": st.bundle_version,
        "git_commit": st.git_commit,
        "selftest": st.selftest,
        "uptime_s": st.started.elapsed().as_secs(),
        "score_requests": lat.0,
        "score_latency_us": {"p50": lat.1, "p99": lat.2},
    }))
}

async fn regimes(
    State(st): State<AppState>,
    AxPath(pair): AxPath<String>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let path = st.data_dir.join("regimes.parquet");
    let latest = state_store::latest_regimes(&path)?;
    match latest.get(&pair) {
        Some(v) => {
            let mut v = v.clone();
            if let Some(obj) = v.as_object_mut() {
                obj.insert(
                    "served_by".into(),
                    serde_json::json!(format!("rust v{}", env!("CARGO_PKG_VERSION"))),
                );
                obj.insert(
                    "bundle_version".into(),
                    serde_json::json!(st.bundle_version),
                );
            }
            Ok(Json(v))
        }
        None => Err(ApiError(
            StatusCode::NOT_FOUND,
            format!("unknown pair {pair}"),
        )),
    }
}

#[derive(Deserialize)]
struct ScoreRequest {
    pair: String,
    windows: Vec<PairWindow>,
}

#[derive(Serialize)]
struct ScoreResponse {
    #[serde(flatten)]
    row: ScoredRowJson,
    served_by: String,
    latency_us: u64,
}

#[derive(Serialize)]
struct ScoredRowJson {
    date: String,
    pair: String,
    regime: String,
    regime_prob: f64,
    probs: std::collections::BTreeMap<String, f64>,
    hmm_entropy: f64,
    days_in_regime: usize,
    vol_trend: f64,
    change_risk_5d: f64,
    change_risk_raw: f64,
    anomaly_score: f64,
    anomaly_pct: f64,
    features: std::collections::BTreeMap<String, f64>,
}

impl From<ScoredRow> for ScoredRowJson {
    fn from(r: ScoredRow) -> Self {
        Self {
            date: state_store::days_to_iso(r.date),
            pair: r.pair,
            regime: r.regime,
            regime_prob: r.regime_prob,
            probs: r.probs,
            hmm_entropy: r.hmm_entropy,
            days_in_regime: r.days_in_regime,
            vol_trend: r.vol_trend,
            change_risk_5d: r.change_risk_5d,
            change_risk_raw: r.change_risk_raw,
            anomaly_score: r.anomaly_score,
            anomaly_pct: r.anomaly_pct,
            features: r.features,
        }
    }
}

async fn score(
    State(st): State<AppState>,
    Json(req): Json<ScoreRequest>,
) -> Result<Json<ScoreResponse>, ApiError> {
    let t0 = Instant::now();
    let row = {
        let mut eng = st.engine.lock().map_err(|_| {
            ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "engine lock poisoned".into(),
            )
        })?;
        eng.score(&req.windows, &req.pair)?
    };
    let us = t0.elapsed().as_micros() as u64;
    if let Ok(mut l) = st.latencies.lock() {
        l.record(us);
    }
    Ok(Json(ScoreResponse {
        row: row.into(),
        served_by: format!("rust v{}", env!("CARGO_PKG_VERSION")),
        latency_us: us,
    }))
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
    let bundle_version = engine.bundle.manifest.bundle_version.clone();
    let git_commit = engine.bundle.manifest.git_commit.clone();
    let state = AppState {
        engine: Arc::new(Mutex::new(engine)),
        data_dir: args.data_dir.clone(),
        started: Instant::now(),
        selftest: status,
        latencies: Arc::new(Mutex::new(Latencies::default())),
        bundle_version,
        git_commit,
    };
    let app = Router::new()
        .route("/api/health", get(health))
        .route("/api/regimes/{pair}", get(regimes))
        .route("/api/score", post(score))
        .layer(TraceLayer::new_for_http())
        .with_state(state);
    let listener = tokio::net::TcpListener::bind(args.bind).await?;
    info!(addr = %args.bind, "fxradar-serve listening");
    axum::serve(listener, app)
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await?;
    Ok(())
}
