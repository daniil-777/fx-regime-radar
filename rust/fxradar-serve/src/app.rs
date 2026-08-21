//! The HTTP layer (phase 13 routes + phase 24 productisation): router, thin handlers, key/tier
//! middleware, Prometheus middleware, OpenAPI document, widget. Handlers call the engine or read
//! artifacts and do arithmetic — no model math, no blocking third-party calls (alert delivery runs
//! on the background queue in [`crate::alerts`]). The start-up gate stays in `bin/serve.rs`.

use crate::alerts;
use crate::avatar;
use crate::features::PairWindow;
use crate::metrics as m;
use crate::ratelimit::RateLimiter;
use crate::state_store;
use crate::store::{Store, Tier};
use crate::stripe;
use crate::treasury::{self, TreasuryQuery};
use crate::{Engine, ScoredRow};
use axum::body::Bytes;
use axum::extract::{MatchedPath, Path as AxPath, Query, Request, State};
use axum::http::{header, HeaderMap, HeaderValue, StatusCode};
use axum::middleware::{self, Next};
use axum::response::{Html, IntoResponse, Response};
use axum::routing::{delete, get, post};
use axum::{Extension, Json, Router};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashMap};
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tower_http::trace::TraceLayer;
use tracing::{info, warn};
use utoipa::openapi::security::{ApiKey, ApiKeyValue, SecurityScheme};
use utoipa::{Modify, OpenApi, ToSchema};
use utoipa_swagger_ui::SwaggerUi;

pub const DISCLAIMER: &str = "Educational tool. Not investment advice.";
pub const WIDGET_JS: &str = include_str!("../static/widget.js");
/// Phase 38: the eight render primitives and their generated stylesheet. Served as static assets
/// so the answer boards of phase 36 can import them; both are cacheable (they change per release,
/// not per request) unlike /avatar, which is the application itself.
pub const CARDS_JS: &str = include_str!("../static/cards.js");
pub const WIDGET_TOKENS_CSS: &str = include_str!("../static/widget-tokens.css");
pub const CARDS_DEMO_HTML: &str = include_str!("../static/cards-demo.html");
pub const WIDGET_HTML: &str = include_str!("../static/widget.html");
const MAX_WEBHOOKS_PER_KEY: usize = 10;

// ---------------------------------------------------------------------------------------------
// state
// ---------------------------------------------------------------------------------------------

#[derive(Clone, Serialize, ToSchema)]
pub struct SelftestStatus {
    /// "pass" | "skipped"
    pub status: String,
    pub goldens: usize,
    pub at_unix: u64,
    pub worst: Vec<(String, f64)>,
}

/// Bounded in-memory latency samples for p50/p99 on /api/score.
#[derive(Default)]
pub struct Latencies {
    samples_us: Vec<u64>,
    count: u64,
}

impl Latencies {
    pub fn record(&mut self, us: u64) {
        self.count += 1;
        if self.samples_us.len() >= 10_000 {
            self.samples_us.remove(0);
        }
        self.samples_us.push(us);
    }
    pub fn quantile(&self, q: f64) -> Option<u64> {
        if self.samples_us.is_empty() {
            return None;
        }
        let mut v = self.samples_us.clone();
        v.sort_unstable();
        let idx = ((v.len() as f64 - 1.0) * q).round() as usize;
        v.get(idx).copied()
    }
}

/// mtime-stamped cache of the two answer-board artifacts (phase 36).
pub struct VisualCache {
    pub index_stamp: (std::time::SystemTime, u64),
    pub boards_stamp: (std::time::SystemTime, u64),
    pub loaded: Arc<(crate::visuals::VisualIndex, crate::visuals::VisualBoards)>,
}

#[derive(Clone)]
pub struct AppState {
    /// `None` only in tests that exercise the service layer without a bundle.
    pub engine: Option<Arc<Mutex<Engine>>>,
    pub store: Store,
    pub limiter: Arc<RateLimiter>,
    pub data_dir: PathBuf,
    pub started: Instant,
    pub selftest: SelftestStatus,
    pub latencies: Arc<Mutex<Latencies>>,
    pub bundle_version: String,
    pub git_commit: String,
    /// From env STRIPE_WEBHOOK_SECRET; never logged.
    pub stripe_secret: Option<String>,
    /// Avatar layer config (phase 35). Defaults to disabled; set via [`AppState::with_avatar`].
    pub avatar: avatar::AvatarCfg,
    touched: Arc<Mutex<HashMap<String, Instant>>>,
    regimes_cache: Arc<Mutex<Option<RegimesCache>>>,
    avatar_pack_cache: Arc<Mutex<Option<avatar::PackCache>>>,
    /// sha256 of gated brain answers per session (last 8) — /avatar/tts only speaks these.
    pub(crate) tts_hashes: Arc<Mutex<HashMap<String, std::collections::VecDeque<String>>>>,
    /// Session ids in first-seen order, so the TTS map can evict the oldest instead of growing
    /// without bound for the life of the process.
    pub(crate) tts_order: Arc<Mutex<std::collections::VecDeque<String>>>,
    decision_cache: Arc<Mutex<Option<avatar::DecisionCache>>>,
    /// Phase 36: the resolved answer boards and their retrieval index, both written by the daily
    /// pipeline (rule 8) and read here as data (rule 11 — no Python at runtime).
    visual_cache: Arc<Mutex<Option<VisualCache>>>,
    /// Sessions that already heard the decision-support disclosure (advice mode).
    pub(crate) advice_disclosed: Arc<Mutex<std::collections::HashSet<String>>>,
}

/// Newest-row-per-pair view of regimes.parquet, re-read only when the file changes (the pipeline
/// rewrites it once a day; the full row-wise parquet scan costs ~0.2 s and must not run per hit).
struct RegimesCache {
    modified: std::time::SystemTime,
    len: u64,
    rows: BTreeMap<String, serde_json::Value>,
}

impl AppState {
    pub fn new(
        engine: Option<Engine>,
        store: Store,
        data_dir: PathBuf,
        selftest: SelftestStatus,
        rate_limit_per_min: u32,
        stripe_secret: Option<String>,
    ) -> AppState {
        // install the Prometheus recorder before the first request so nothing is lost
        let _ = m::handle();
        let (bundle_version, git_commit) = engine
            .as_ref()
            .map(|e| {
                (
                    e.bundle.manifest.bundle_version.clone(),
                    e.bundle.manifest.git_commit.clone(),
                )
            })
            .unwrap_or_else(|| ("none".into(), "none".into()));
        AppState {
            engine: engine.map(|e| Arc::new(Mutex::new(e))),
            store,
            limiter: Arc::new(RateLimiter::new(rate_limit_per_min)),
            data_dir,
            started: Instant::now(),
            selftest,
            latencies: Arc::new(Mutex::new(Latencies::default())),
            bundle_version,
            git_commit,
            stripe_secret,
            avatar: avatar::AvatarCfg::default(),
            touched: Arc::new(Mutex::new(HashMap::new())),
            regimes_cache: Arc::new(Mutex::new(None)),
            avatar_pack_cache: Arc::new(Mutex::new(None)),
            tts_hashes: Arc::new(Mutex::new(HashMap::new())),
            tts_order: Arc::new(Mutex::new(std::collections::VecDeque::new())),
            decision_cache: Arc::new(Mutex::new(None)),
            visual_cache: Arc::new(Mutex::new(None)),
            advice_disclosed: Arc::new(Mutex::new(std::collections::HashSet::new())),
        }
    }

    /// Attach the avatar configuration (builder-style, so `new`'s signature stays stable).
    pub fn with_avatar(mut self, cfg: avatar::AvatarCfg) -> AppState {
        self.avatar = cfg;
        self
    }

    /// The decision table (advice mode), reloaded from `<data_dir>/decision_table.json` on
    /// mtime change — same pattern as the context pack.
    pub fn decision_table(&self) -> Result<Arc<avatar::DecisionTable>, String> {
        let path = self.data_dir.join("decision_table.json");
        let meta = std::fs::metadata(&path).map_err(|e| format!("decision table missing: {e}"))?;
        let modified = meta.modified().unwrap_or(std::time::UNIX_EPOCH);
        let len = meta.len();
        if let Ok(guard) = self.decision_cache.lock() {
            if let Some(c) = guard.as_ref() {
                if c.modified == modified && c.len == len {
                    return Ok(Arc::clone(&c.table));
                }
            }
        }
        let table = Arc::new(avatar::load_decision_table(&path)?);
        if let Ok(mut guard) = self.decision_cache.lock() {
            *guard = Some(avatar::DecisionCache {
                modified,
                len,
                table: Arc::clone(&table),
            });
        }
        Ok(table)
    }

    /// The answer-board artifacts, reloaded together on mtime change. Missing files are NOT an
    /// error: a deployment without them simply answers in words, which is the phase-35 behaviour.
    pub fn visuals(
        &self,
    ) -> Option<Arc<(crate::visuals::VisualIndex, crate::visuals::VisualBoards)>> {
        let index_path = self.data_dir.join("visual_index.json");
        let boards_path = self.data_dir.join("visual_boards.json");
        let stamp = |p: &std::path::Path| {
            std::fs::metadata(p)
                .ok()
                .map(|m| (m.modified().unwrap_or(std::time::UNIX_EPOCH), m.len()))
        };
        let (si, sb) = (stamp(&index_path)?, stamp(&boards_path)?);
        if let Ok(guard) = self.visual_cache.lock() {
            if let Some(c) = guard.as_ref() {
                if c.index_stamp == si && c.boards_stamp == sb {
                    return Some(Arc::clone(&c.loaded));
                }
            }
        }
        let index = crate::visuals::load_index(&index_path)
            .map_err(|e| tracing::warn!(error = %e, "visual index unusable; answering in words"))
            .ok()?;
        let boards = crate::visuals::load_boards(&boards_path)
            .map_err(|e| tracing::warn!(error = %e, "visual boards unusable; answering in words"))
            .ok()?;
        let loaded = Arc::new((index, boards));
        if let Ok(mut guard) = self.visual_cache.lock() {
            *guard = Some(VisualCache {
                index_stamp: si,
                boards_stamp: sb,
                loaded: Arc::clone(&loaded),
            });
        }
        Some(loaded)
    }

    /// The avatar context pack, reloaded from `<data_dir>/avatar_context.json` on mtime change
    /// (same pattern as the regimes cache). Errors map to 503 in the handlers.
    pub fn avatar_pack(&self) -> Result<Arc<avatar::Pack>, String> {
        let path = self.data_dir.join("avatar_context.json");
        let meta =
            std::fs::metadata(&path).map_err(|e| format!("avatar context pack missing: {e}"))?;
        let modified = meta.modified().unwrap_or(std::time::UNIX_EPOCH);
        let len = meta.len();
        if let Ok(guard) = self.avatar_pack_cache.lock() {
            if let Some(c) = guard.as_ref() {
                if c.modified == modified && c.len == len {
                    return Ok(Arc::clone(&c.pack));
                }
            }
        }
        let pack = Arc::new(avatar::load_pack(&path)?);
        if let Ok(mut guard) = self.avatar_pack_cache.lock() {
            *guard = Some(avatar::PackCache {
                modified,
                len,
                pack: Arc::clone(&pack),
            });
        }
        Ok(pack)
    }

    /// Latest regimes rows, served from the mtime-keyed cache.
    pub fn latest_regimes(
        &self,
    ) -> Result<BTreeMap<String, serde_json::Value>, crate::EngineError> {
        let path = self.data_dir.join("regimes.parquet");
        let meta = std::fs::metadata(&path).map_err(|source| crate::EngineError::Io {
            path: path.display().to_string(),
            source,
        })?;
        let modified = meta.modified().unwrap_or(std::time::UNIX_EPOCH);
        let len = meta.len();
        if let Ok(guard) = self.regimes_cache.lock() {
            if let Some(c) = guard.as_ref() {
                if c.modified == modified && c.len == len {
                    return Ok(c.rows.clone());
                }
            }
        }
        let rows = state_store::latest_regimes(&path)?;
        if let Ok(mut guard) = self.regimes_cache.lock() {
            *guard = Some(RegimesCache {
                modified,
                len,
                rows: rows.clone(),
            });
        }
        Ok(rows)
    }
}

// ---------------------------------------------------------------------------------------------
// errors -> JSON with status codes
// ---------------------------------------------------------------------------------------------

#[derive(Serialize, ToSchema)]
pub struct ApiErrorBody {
    pub error: String,
    pub status: u16,
}

pub struct ApiError(pub StatusCode, pub String);

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let body = ApiErrorBody {
            error: self.1,
            status: self.0.as_u16(),
        };
        (self.0, Json(body)).into_response()
    }
}

impl From<crate::EngineError> for ApiError {
    fn from(e: crate::EngineError) -> Self {
        use crate::EngineError as E;
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

impl From<crate::store::StoreError> for ApiError {
    fn from(e: crate::store::StoreError) -> Self {
        ApiError(StatusCode::INTERNAL_SERVER_ERROR, format!("store: {e}"))
    }
}

// ---------------------------------------------------------------------------------------------
// middleware: API key + tier + rate limit; Prometheus
// ---------------------------------------------------------------------------------------------

/// What the key middleware attaches to the request for the handlers.
#[derive(Clone, Debug)]
pub struct AuthKey {
    pub key_hash: String,
    pub tier: Tier,
}

/// Keyed routes: valid + not revoked (else 401), under the per-key rate limit (else 429 with
/// Retry-After), and on a paid tier (else 403). Public routes never pass through here.
pub async fn auth_paid(State(st): State<AppState>, mut req: Request, next: Next) -> Response {
    let key = match req
        .headers()
        .get("x-api-key")
        .and_then(|v| v.to_str().ok())
        .map(|s| s.trim().to_string())
    {
        Some(k) if !k.is_empty() => k,
        _ => {
            return ApiError(StatusCode::UNAUTHORIZED, "missing X-API-Key header".into())
                .into_response()
        }
    };
    let rec = match st.store.lookup_plaintext(&key) {
        Ok(Some(r)) if !r.revoked => r,
        Ok(_) => {
            return ApiError(
                StatusCode::UNAUTHORIZED,
                "unknown or revoked API key".into(),
            )
            .into_response()
        }
        Err(e) => return ApiError::from(e).into_response(),
    };
    if let Err(retry) = st.limiter.check(&rec.key_hash) {
        let mut resp = ApiError(
            StatusCode::TOO_MANY_REQUESTS,
            format!(
                "rate limit {} requests/min exceeded; retry in {retry}s",
                st.limiter.per_minute()
            ),
        )
        .into_response();
        if let Ok(v) = HeaderValue::from_str(&retry.to_string()) {
            resp.headers_mut().insert(header::RETRY_AFTER, v);
        }
        return resp;
    }
    if !rec.tier.is_paid() {
        return ApiError(
            StatusCode::FORBIDDEN,
            format!(
                "tier {} cannot use this route; pro or partner required",
                rec.tier
            ),
        )
        .into_response();
    }
    // last_used bookkeeping, throttled to one write per key per minute
    let stale = st
        .touched
        .lock()
        .map(|mut t| {
            let now = Instant::now();
            match t.get(&rec.key_hash) {
                Some(prev) if now.duration_since(*prev) < Duration::from_secs(60) => false,
                _ => {
                    t.insert(rec.key_hash.clone(), now);
                    true
                }
            }
        })
        .unwrap_or(false);
    if stale {
        let _ = st.store.touch_last_used(&rec.key_hash);
    }
    req.extensions_mut().insert(AuthKey {
        key_hash: rec.key_hash,
        tier: rec.tier,
    });
    next.run(req).await
}

/// Prometheus golden signals per matched route.
pub async fn track_metrics(req: Request, next: Next) -> Response {
    let route = req
        .extensions()
        .get::<MatchedPath>()
        .map(|p| p.as_str().to_string())
        .unwrap_or_else(|| "unmatched".into());
    let t0 = Instant::now();
    let resp = next.run(req).await;
    m::record_http(&route, resp.status().as_u16(), t0.elapsed().as_secs_f64());
    resp
}

// ---------------------------------------------------------------------------------------------
// public handlers
// ---------------------------------------------------------------------------------------------

/// Service health: version, bundle, self-test verdict, uptime, engine latency quantiles.
#[utoipa::path(get, path = "/api/health", tag = "public",
    responses((status = 200, description = "service is up; selftest.status is pass or skipped", body = Object)))]
pub async fn health(State(st): State<AppState>) -> Json<serde_json::Value> {
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
        "rate_limit_per_min": st.limiter.per_minute(),
        "disclaimer": DISCLAIMER,
    }))
}

#[derive(Deserialize, Default, utoipa::IntoParams)]
pub struct RegimesQuery {
    /// Widget attribution tag (logged only)
    pub partner: Option<String>,
}

/// Newest regimes.parquet row for one pair (all columns), as written by the Python pipeline.
#[utoipa::path(get, path = "/api/regimes/{pair}", tag = "public",
    params(("pair" = String, Path, description = "EURUSD | USDCHF | GBPUSD"), RegimesQuery),
    responses((status = 200, description = "newest row", body = Object),
              (status = 404, description = "unknown pair", body = ApiErrorBody),
              (status = 503, description = "artifact unreadable", body = ApiErrorBody)))]
pub async fn regimes(
    State(st): State<AppState>,
    AxPath(pair): AxPath<String>,
    Query(q): Query<RegimesQuery>,
) -> Result<Json<serde_json::Value>, ApiError> {
    if let Some(p) = q.partner.as_deref().filter(|p| !p.is_empty()) {
        let p: String = p
            .chars()
            .filter(|c| c.is_alphanumeric() || *c == '-' || *c == '_')
            .take(40)
            .collect();
        info!(partner = %p, pair = %pair, "widget attribution");
        metrics::counter!("widget_requests_total", "partner" => p).increment(1);
    }
    let latest = st.latest_regimes()?;
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

/// Prometheus text exposition.
#[utoipa::path(get, path = "/metrics", tag = "public",
    responses((status = 200, description = "text/plain; version=0.0.4", body = String)))]
pub async fn metrics_handler() -> Response {
    (
        [(
            header::CONTENT_TYPE,
            "text/plain; version=0.0.4; charset=utf-8",
        )],
        m::render(),
    )
        .into_response()
}

/// Embeddable badge script (vanilla JS, same-origin fetch of /api/regimes/{pair}).
#[utoipa::path(get, path = "/widget.js", tag = "public",
    responses((status = 200, description = "application/javascript", body = String)))]
pub async fn widget_js() -> Response {
    (
        [
            (
                header::CONTENT_TYPE,
                "application/javascript; charset=utf-8",
            ),
            (header::CACHE_CONTROL, "public, max-age=300"),
        ],
        WIDGET_JS,
    )
        .into_response()
}

#[utoipa::path(get, path = "/cards.js", tag = "public",
    responses((status = 200, description = "the eight render primitives (ES module)", body = String)))]
pub async fn cards_js() -> Response {
    (
        [
            (
                header::CONTENT_TYPE,
                "application/javascript; charset=utf-8",
            ),
            (header::CACHE_CONTROL, "public, max-age=300"),
        ],
        CARDS_JS,
    )
        .into_response()
}

#[utoipa::path(get, path = "/widget-tokens.css", tag = "public",
    responses((status = 200, description = "generated card stylesheet", body = String)))]
pub async fn widget_tokens_css() -> Response {
    (
        [
            (header::CONTENT_TYPE, "text/css; charset=utf-8"),
            (header::CACHE_CONTROL, "public, max-age=300"),
        ],
        WIDGET_TOKENS_CSS,
    )
        .into_response()
}

#[utoipa::path(get, path = "/cards", tag = "public",
    responses((status = 200, description = "primitive gallery: normal, skeleton and stale states")))]
pub async fn cards_demo() -> Html<&'static str> {
    Html(CARDS_DEMO_HTML)
}

/// Demo page embedding the widget three times.
#[utoipa::path(get, path = "/widget", tag = "public",
    responses((status = 200, description = "text/html", body = String)))]
pub async fn avatar_page() -> Response {
    // no-store, deliberately: this page IS the application (its script drives WebRTC, the mic and
    // the gated brain). A cached copy silently pairs old client code with a new server — the exact
    // failure that made "the mic does nothing" survive three fixes. It is 26 kB; correctness wins.
    (
        [
            (header::CONTENT_TYPE, "text/html; charset=utf-8"),
            (header::CACHE_CONTROL, "no-store, must-revalidate"),
        ],
        include_str!("../static/avatar.html"),
    )
        .into_response()
}

#[utoipa::path(get, path = "/widget", tag = "public",
    responses((status = 200, description = "Demo page embedding the widget")))]
pub async fn widget_demo() -> Html<&'static str> {
    Html(WIDGET_HTML)
}

// ---------------------------------------------------------------------------------------------
// keyed handlers (pro | partner)
// ---------------------------------------------------------------------------------------------

#[derive(Deserialize, ToSchema)]
pub struct ScoreRequest {
    /// Pair to score (EURUSD | USDCHF | GBPUSD)
    pub pair: String,
    /// Raw daily windows for ALL three pairs (≥ 600 rows each, oldest first)
    pub windows: Vec<PairWindow>,
}

#[derive(Serialize, ToSchema)]
pub struct ScoreResponse {
    #[serde(flatten)]
    pub row: ScoredRowJson,
    pub served_by: String,
    pub latency_us: u64,
}

#[derive(Serialize, ToSchema)]
pub struct ScoredRowJson {
    pub date: String,
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

/// Score raw price windows through the frozen bundle (features → HMM filter → ONNX models).
#[utoipa::path(post, path = "/api/score", tag = "keyed", security(("api_key" = [])),
    request_body = ScoreRequest,
    responses((status = 200, description = "scored row", body = ScoreResponse),
              (status = 400, description = "bad window", body = ApiErrorBody),
              (status = 401, description = "missing/unknown key", body = ApiErrorBody),
              (status = 403, description = "free tier", body = ApiErrorBody),
              (status = 429, description = "rate limited (Retry-After)", body = ApiErrorBody)))]
pub async fn score(
    State(st): State<AppState>,
    Json(req): Json<ScoreRequest>,
) -> Result<Json<ScoreResponse>, ApiError> {
    let t0 = Instant::now();
    let engine = st.engine.as_ref().ok_or_else(|| {
        ApiError(
            StatusCode::SERVICE_UNAVAILABLE,
            "scoring engine not loaded".into(),
        )
    })?;
    let row = {
        let mut eng = engine.lock().map_err(|_| {
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
    m::record_score_latency(us as f64 / 1e6);
    Ok(Json(ScoreResponse {
        row: row.into(),
        served_by: format!("rust v{}", env!("CARGO_PKG_VERSION")),
        latency_us: us,
    }))
}

/// Treasury risk table (data/treasury_risk.json) with optional notional arithmetic.
#[utoipa::path(get, path = "/api/treasury", tag = "keyed", security(("api_key" = [])),
    params(TreasuryQuery),
    responses((status = 200, description = "artifact + optional calc; always carries the disclaimer", body = Object),
              (status = 400, description = "bad query", body = ApiErrorBody),
              (status = 404, description = "artifact absent", body = ApiErrorBody)))]
pub async fn treasury_handler(
    State(st): State<AppState>,
    Query(q): Query<TreasuryQuery>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let artifact =
        treasury::load(&st.data_dir.join("treasury_risk.json")).map_err(|e| match e {
            treasury::TreasuryError::Missing => ApiError(StatusCode::NOT_FOUND, e.to_string()),
            other => ApiError(StatusCode::SERVICE_UNAVAILABLE, other.to_string()),
        })?;
    treasury::respond(&artifact, &q)
        .map(Json)
        .map_err(|e| ApiError(StatusCode::BAD_REQUEST, e.to_string()))
}

#[derive(Deserialize, ToSchema)]
pub struct WebhookCreate {
    /// Receiver URL (generic JSON POST, Slack incoming webhook, or Telegram bot sendMessage URL)
    pub url: String,
    /// generic | slack | telegram (default generic)
    pub kind: Option<String>,
    /// Pairs to subscribe (default: all)
    pub pairs: Option<Vec<String>>,
    /// Telegram chat id (telegram only)
    pub chat_id: Option<String>,
}

#[derive(Serialize, ToSchema)]
pub struct WebhookCreated {
    pub id: i64,
    pub url: String,
    pub kind: String,
    pub pairs: Vec<String>,
    pub created_at: String,
    /// Shown ONCE. Verify deliveries with HMAC-SHA256(secret, "{X-FXRadar-Timestamp}.{body}").
    pub secret: String,
    pub signing: String,
    pub triggers: Vec<String>,
}

#[derive(Serialize, ToSchema)]
pub struct WebhookInfo {
    pub id: i64,
    pub url: String,
    pub kind: String,
    pub pairs: Vec<String>,
    pub created_at: String,
}

/// Register an alert receiver for the calling key. Returns the signing secret once.
#[utoipa::path(post, path = "/api/webhooks", tag = "keyed", security(("api_key" = [])),
    request_body = WebhookCreate,
    responses((status = 201, description = "registered", body = WebhookCreated),
              (status = 400, description = "bad input", body = ApiErrorBody),
              (status = 409, description = "too many webhooks", body = ApiErrorBody)))]
pub async fn webhooks_create(
    State(st): State<AppState>,
    Extension(auth): Extension<AuthKey>,
    Json(req): Json<WebhookCreate>,
) -> Result<(StatusCode, Json<WebhookCreated>), ApiError> {
    let url = req.url.trim();
    if !(url.starts_with("http://") || url.starts_with("https://")) {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "url must start with http:// or https://".into(),
        ));
    }
    let kind = req
        .kind
        .unwrap_or_else(|| "generic".into())
        .to_ascii_lowercase();
    if !["generic", "slack", "telegram"].contains(&kind.as_str()) {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "kind must be generic | slack | telegram".into(),
        ));
    }
    if kind == "telegram" && req.chat_id.as_deref().unwrap_or("").is_empty() {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "telegram webhooks need chat_id".into(),
        ));
    }
    let pairs: Vec<String> = req
        .pairs
        .unwrap_or_default()
        .into_iter()
        .map(|p| p.trim().to_ascii_uppercase())
        .filter(|p| !p.is_empty())
        .collect();
    if pairs
        .iter()
        .any(|p| p.len() != 6 || !p.chars().all(|c| c.is_ascii_alphanumeric()))
    {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "pairs must look like EURUSD".into(),
        ));
    }
    if st.store.list_webhooks(Some(&auth.key_hash))?.len() >= MAX_WEBHOOKS_PER_KEY {
        return Err(ApiError(
            StatusCode::CONFLICT,
            format!("at most {MAX_WEBHOOKS_PER_KEY} webhooks per key"),
        ));
    }
    let w = st
        .store
        .add_webhook(&auth.key_hash, url, &kind, &pairs, req.chat_id.as_deref())?;
    info!(webhook = w.id, kind = %w.kind, key = %&auth.key_hash[..8], "webhook registered");
    Ok((
        StatusCode::CREATED,
        Json(WebhookCreated {
            id: w.id,
            url: w.url,
            kind: w.kind,
            pairs: w.pairs,
            created_at: w.created_at,
            secret: w.secret,
            signing: "X-FXRadar-Signature: sha256=hex(HMAC-SHA256(secret, \"{X-FXRadar-Timestamp}.{raw body}\"))".into(),
            triggers: alerts::TRIGGERS.iter().map(|s| s.to_string()).collect(),
        }),
    ))
}

/// List the calling key's webhooks (secrets never returned again).
#[utoipa::path(get, path = "/api/webhooks", tag = "keyed", security(("api_key" = [])),
    responses((status = 200, description = "webhooks", body = Vec<WebhookInfo>)))]
pub async fn webhooks_list(
    State(st): State<AppState>,
    Extension(auth): Extension<AuthKey>,
) -> Result<Json<Vec<WebhookInfo>>, ApiError> {
    let hooks = st.store.list_webhooks(Some(&auth.key_hash))?;
    Ok(Json(
        hooks
            .into_iter()
            .map(|w| WebhookInfo {
                id: w.id,
                url: w.url,
                kind: w.kind,
                pairs: w.pairs,
                created_at: w.created_at,
            })
            .collect(),
    ))
}

/// Delete one of the calling key's webhooks.
#[utoipa::path(delete, path = "/api/webhooks/{id}", tag = "keyed", security(("api_key" = [])),
    params(("id" = i64, Path, description = "webhook id")),
    responses((status = 204, description = "deleted"), (status = 404, description = "not yours / unknown", body = ApiErrorBody)))]
pub async fn webhooks_delete(
    State(st): State<AppState>,
    Extension(auth): Extension<AuthKey>,
    AxPath(id): AxPath<i64>,
) -> Result<StatusCode, ApiError> {
    if st.store.delete_webhook(&auth.key_hash, id)? {
        Ok(StatusCode::NO_CONTENT)
    } else {
        Err(ApiError(StatusCode::NOT_FOUND, format!("no webhook {id}")))
    }
}

// ---------------------------------------------------------------------------------------------
// Stripe webhook (public route, signature-verified)
// ---------------------------------------------------------------------------------------------

#[derive(Serialize, ToSchema)]
pub struct StripeAck {
    pub received: bool,
    /// {key_prefix, tier, event_type} when a tier was changed
    pub applied: Option<serde_json::Value>,
}

/// Stripe events (TEST MODE): verifies Stripe-Signature with STRIPE_WEBHOOK_SECRET, then maps
/// checkout.session.completed / customer.subscription.updated|deleted to a tier change.
#[utoipa::path(post, path = "/api/stripe/webhook", tag = "public",
    request_body(content = String, content_type = "application/json", description = "raw Stripe event JSON (signed with Stripe-Signature)"),
    responses((status = 200, description = "acknowledged", body = StripeAck),
              (status = 400, description = "bad signature or body", body = ApiErrorBody),
              (status = 503, description = "secret not configured", body = ApiErrorBody)))]
pub async fn stripe_webhook(
    State(st): State<AppState>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<Json<StripeAck>, ApiError> {
    let secret = st.stripe_secret.as_deref().ok_or_else(|| {
        ApiError(
            StatusCode::SERVICE_UNAVAILABLE,
            "STRIPE_WEBHOOK_SECRET not configured".into(),
        )
    })?;
    let sig = headers
        .get("stripe-signature")
        .and_then(|v| v.to_str().ok())
        .ok_or_else(|| ApiError(StatusCode::BAD_REQUEST, "missing Stripe-Signature".into()))?;
    stripe::verify(secret, sig, &body, crate::store::now_unix(), 300)
        .map_err(|e| ApiError(StatusCode::BAD_REQUEST, format!("stripe: {e}")))?;
    let event: serde_json::Value = serde_json::from_slice(&body)
        .map_err(|e| ApiError(StatusCode::BAD_REQUEST, format!("stripe: bad json: {e}")))?;
    let Some(change) = stripe::tier_change(&event) else {
        return Ok(Json(StripeAck {
            received: true,
            applied: None,
        }));
    };
    match st.store.set_tier(&change.key_prefix, change.tier) {
        Ok(h) => {
            info!(key = %&h[..12], tier = %change.tier, event = %change.event_type, "stripe: tier updated");
            Ok(Json(StripeAck {
                received: true,
                applied: Some(serde_json::json!({
                    "key_prefix": &h[..12], "tier": change.tier, "event_type": change.event_type})),
            }))
        }
        Err(e) => {
            warn!(error = %e, event = %change.event_type, "stripe: could not map event to a key");
            Ok(Json(StripeAck {
                received: true,
                applied: None,
            }))
        }
    }
}

// ---------------------------------------------------------------------------------------------
// OpenAPI
// ---------------------------------------------------------------------------------------------

struct SecurityAddon;

impl Modify for SecurityAddon {
    fn modify(&self, openapi: &mut utoipa::openapi::OpenApi) {
        let components = openapi.components.get_or_insert_with(Default::default);
        components.add_security_scheme(
            "api_key",
            SecurityScheme::ApiKey(ApiKey::Header(ApiKeyValue::new("X-API-Key"))),
        );
    }
}

#[derive(OpenApi)]
#[openapi(
    info(
        title = "FX Regime Radar API",
        description = "Regime nowcast, change-risk and anomaly state for EURUSD / USDCHF / GBPUSD, \
served by the Rust engine from the frozen model bundle. Public routes need no key; keyed routes \
take `X-API-Key` (tier pro or partner). Educational tool. Not investment advice.",
        license(name = "MIT")
    ),
    paths(health, regimes, metrics_handler, widget_js, widget_demo, cards_js, widget_tokens_css,
        cards_demo, score, treasury_handler,
          webhooks_create, webhooks_list, webhooks_delete, stripe_webhook,
          avatar::brain, avatar::greeting, avatar::session_token, avatar::heartbeat, avatar::tts),
    components(schemas(ApiErrorBody, ScoreRequest, ScoreResponse, ScoredRowJson, PairWindow,
        WebhookCreate, WebhookCreated, WebhookInfo, StripeAck, SelftestStatus,
        avatar::BrainRequest, avatar::BrainMessage, avatar::BrainResponse,
        avatar::SessionTokenRequest, avatar::HeartbeatRequest, avatar::TtsRequest)),
    modifiers(&SecurityAddon),
    tags((name = "public", description = "No key needed"),
         (name = "keyed", description = "X-API-Key with tier pro or partner"),
         (name = "avatar", description = "AI presenter (feature-flagged; 503 while FXRADAR_AVATAR is off). \
/avatar/brain and /avatar/heartbeat take X-Avatar-Token; /avatar/session-token takes X-API-Key"))
)]
pub struct ApiDoc;

// ---------------------------------------------------------------------------------------------
// router
// ---------------------------------------------------------------------------------------------

/// Build the full application router (public + keyed routes, docs, metrics).
pub fn build_router(state: AppState) -> Router {
    let public = Router::new()
        .route("/api/health", get(health))
        .route("/api/regimes/{pair}", get(regimes))
        .route("/metrics", get(metrics_handler))
        .route("/widget.js", get(widget_js))
        .route("/widget", get(widget_demo))
        .route("/cards.js", get(cards_js))
        .route("/widget-tokens.css", get(widget_tokens_css))
        .route("/cards", get(cards_demo))
        .route("/api/stripe/webhook", post(stripe_webhook));
    let keyed = Router::new()
        .route("/api/score", post(score))
        .route("/api/treasury", get(treasury_handler))
        .route("/api/webhooks", post(webhooks_create).get(webhooks_list))
        .route("/api/webhooks/{id}", delete(webhooks_delete))
        .route_layer(middleware::from_fn_with_state(state.clone(), auth_paid));
    // Avatar routes (phase 35), all behind the feature flag (503 when off). Auth is per-route:
    // brain/heartbeat check X-Avatar-Token, session-token checks X-API-Key in-handler (so the
    // DEV flag can waive it for the "local" vendor only), greeting is public while the flag is on.
    let avatar_routes = Router::new()
        .route("/avatar", get(avatar_page))
        .route("/avatar/greeting", get(avatar::greeting))
        .route("/avatar/brain", post(avatar::brain))
        .route("/avatar/session-token", post(avatar::session_token))
        .route("/avatar/heartbeat", post(avatar::heartbeat))
        .route("/avatar/tts", post(avatar::tts))
        .route_layer(middleware::from_fn_with_state(
            state.clone(),
            avatar::require_enabled,
        ));
    Router::new()
        .merge(public)
        .merge(keyed)
        .merge(avatar_routes)
        .merge(SwaggerUi::new("/docs").url("/api-docs/openapi.json", ApiDoc::openapi()))
        .layer(middleware::from_fn(track_metrics))
        .layer(TraceLayer::new_for_http())
        .with_state(state)
}
