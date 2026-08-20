//! The avatar "mouth" (phase 35): a BYO-LLM brain endpoint grounded ONLY in the daily context
//! pack, with hard output gates (direction lint + numeric grounding) in front of any voice.
//!
//! Everything is behind the `FXRADAR_AVATAR` feature flag (default off → all `/avatar/*` routes
//! answer 503). The pack (`data/avatar_context.json`) is written by the Python pipeline and
//! reloaded here on mtime change, like the regimes cache. No model math lives here — the handlers
//! read the pack, call the (optional) Anthropic API, and run pure text gates. The gates never
//! trust the generator: a fabricated number or a direction word is discarded and replaced by the
//! pack's own pre-linted refusal text.

use crate::app::{ApiError, ApiErrorBody, AppState};
use crate::metrics as m;
use crate::store::now_unix;
use axum::body::Bytes;
use axum::extract::{Request, State};
use axum::http::{HeaderMap, StatusCode};
use axum::middleware::Next;
use axum::response::{IntoResponse, Response};
use axum::Json;
use rand::RngCore;
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use std::time::{Duration, Instant, SystemTime};
use tracing::{error, warn};
use utoipa::ToSchema;

pub const DISCLAIMER: &str = "Educational tool. Not investment advice.";
/// Model + params are fixed by the phase prompt; the call is non-streaming with a 10 s timeout.
const ANTHROPIC_MODEL: &str = "claude-haiku-4-5";
const ANTHROPIC_MAX_TOKENS: u32 = 220;
const ANTHROPIC_TEMPERATURE: f64 = 0.2;
const SESSION_TTL_SECS: u64 = 30 * 60;

/// Compiled-in fallback for `prompts/avatar_system_v1.txt` (used only if the file is unreadable
/// at runtime, e.g. inside a container that shipped without the prompts directory). Keep the
/// required clauses in sync with the file: identity/disclosure, grounding, brevity, tone, bans.
const FALLBACK_SYSTEM_PROMPT: &str = "You are the FX Regime Radar's AI presenter — a \
computer-generated voice, not a person; say so if asked. Answer ONLY from the CONTEXT and \
KNOWLEDGE below; if the answer is not there, say you don't have it. Never state a number absent \
from CONTEXT or KNOWLEDGE. Never state or imply price direction and never give investment \
advice — use the refusal texts in CONTEXT. At most 3 sentences; calm, neutral tone. \
Educational tool. Not investment advice.";

// ---------------------------------------------------------------------------------------------
// config
// ---------------------------------------------------------------------------------------------

/// Runtime configuration for the avatar layer, wired from env in `bin/serve.rs`.
#[derive(Clone, Debug)]
pub struct AvatarCfg {
    /// FXRADAR_AVATAR ("on"/"off", default off). Off → every /avatar/* route answers 503.
    pub enabled: bool,
    /// FXRADAR_AVATAR_BRAIN_TOKEN: static vendor token for /avatar/brain and /avatar/heartbeat.
    pub brain_token: Option<String>,
    /// FXRADAR_AVATAR_VENDOR: default vendor for /avatar/session-token ("local" | "anam" | "heygen").
    pub vendor_default: String,
    /// FXRADAR_AVATAR_MAX_SESSIONS_MONTH (default 300).
    pub max_sessions_month: i64,
    /// FXRADAR_AVATAR_MAX_MINUTES_MONTH (default 600).
    pub max_minutes_month: f64,
    /// ANTHROPIC_API_KEY: enables the LLM path; unset → keyless FAQ fallback (tests, CI).
    pub anthropic_key: Option<String>,
    /// ANAM_API_KEY (vendor "anam"). Unset → 503 "anam not configured".
    pub anam_key: Option<String>,
    /// HEYGEN_API_KEY (vendor "heygen"). Unset → 503 "heygen not configured".
    pub heygen_key: Option<String>,
    /// Path to the versioned system prompt file (default prompts/avatar_system_v1.txt).
    pub system_prompt_path: PathBuf,
    /// FXRADAR_AVATAR_DEV=1 — DEV ONLY, never set in production: lets /avatar/session-token
    /// mint a "local" session WITHOUT an X-API-Key (still cost-capped and counted) so the
    /// widget can be demoed on a laptop. Non-local vendors always require a key.
    pub dev: bool,
    /// Honour `test_force_text` in the brain request body. True in debug builds, via
    /// FXRADAR_AVATAR_TEST=1, or set directly by tests. DEV/TEST ONLY — it exists so the
    /// planted-fabrication test can prove the gates block a fabricated number; it skips
    /// generation, never the gates.
    pub test_hook: bool,
}

impl Default for AvatarCfg {
    fn default() -> Self {
        AvatarCfg {
            enabled: false,
            brain_token: None,
            vendor_default: "local".into(),
            max_sessions_month: 300,
            max_minutes_month: 600.0,
            anthropic_key: None,
            anam_key: None,
            heygen_key: None,
            system_prompt_path: PathBuf::from("prompts/avatar_system_v1.txt"),
            dev: false,
            test_hook: cfg!(debug_assertions),
        }
    }
}

// ---------------------------------------------------------------------------------------------
// context pack (written by Python: data/avatar_context.json)
// ---------------------------------------------------------------------------------------------

#[derive(Debug, Clone, Deserialize, Default)]
pub struct Refusals {
    #[serde(default)]
    pub direction: String,
    #[serde(default)]
    pub advice: String,
    #[serde(default)]
    pub off_topic: String,
    #[serde(default)]
    pub not_in_pack: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct FaqEntry {
    pub q: String,
    #[serde(default)]
    pub keywords: Vec<String>,
    pub answer: String,
}

/// Parsed context pack plus derived views (allowed-number set, LLM context JSON).
#[derive(Debug, Clone)]
pub struct Pack {
    pub data_through: String,
    pub disclosure: String,
    pub greeting: String,
    pub refusals: Refusals,
    pub faq: Vec<FaqEntry>,
    /// Canonical allowed numbers (Python canonical form; see [`canon_number`]).
    pub allowed: HashSet<String>,
    /// Repo-relative path to docs/avatar_knowledge.md.
    pub knowledge_rel: String,
    /// The pack minus allowed_numbers/faq, serialized once for the LLM CONTEXT block.
    pub context_json: String,
}

/// mtime-keyed cache entry held in [`AppState`].
pub struct PackCache {
    pub modified: SystemTime,
    pub len: u64,
    pub pack: std::sync::Arc<Pack>,
}

#[derive(Deserialize)]
struct PackFile {
    #[serde(default)]
    data_through: String,
    #[serde(default)]
    disclosure: String,
    #[serde(default)]
    greeting: String,
    #[serde(default)]
    refusals: Refusals,
    #[serde(default)]
    faq: Vec<FaqEntry>,
    #[serde(default)]
    allowed_numbers: Vec<String>,
    #[serde(default)]
    knowledge_pack: String,
}

/// Load and parse the context pack. Errors are strings so the caller can map them to 503.
pub fn load_pack(path: &Path) -> Result<Pack, String> {
    let raw = std::fs::read_to_string(path)
        .map_err(|e| format!("avatar context unreadable ({}): {e}", path.display()))?;
    let mut v: Value =
        serde_json::from_str(&raw).map_err(|e| format!("avatar context is not valid JSON: {e}"))?;
    let pf: PackFile = serde_json::from_value(v.clone())
        .map_err(|e| format!("avatar context has a bad shape: {e}"))?;
    if let Some(obj) = v.as_object_mut() {
        obj.remove("allowed_numbers");
        obj.remove("faq");
    }
    Ok(Pack {
        data_through: pf.data_through,
        disclosure: pf.disclosure,
        greeting: pf.greeting,
        refusals: pf.refusals,
        faq: pf.faq,
        allowed: pf.allowed_numbers.into_iter().collect(),
        knowledge_rel: pf.knowledge_pack,
        context_json: v.to_string(),
    })
}

// ---------------------------------------------------------------------------------------------
// pure gate helpers
// ---------------------------------------------------------------------------------------------

fn num_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"\d+(?:\.\d+)?").expect("static regex"))
}

fn direction_intent_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(
            r"\b(rise|fall|go up|go down|drop|rally|bullish|bearish|target|forecast the (?:rate|price)|which way|higher or lower|appreciate|depreciate|strengthen|weaken)\b",
        )
        .expect("static regex")
    })
}

fn advice_intent_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        // "position siz\w*" so "position sizing"/"position size" both match the intent guard.
        Regex::new(
            r"\b(should i|buy|sell|hedge my|stop.?loss|position siz\w*|invest|portfolio|advice|what would you do)\b",
        )
        .expect("static regex")
    })
}

/// Canonicalise a numeric token EXACTLY like the Python side: parse as f64, format with four
/// decimals, trim trailing zeros then a trailing dot ("0" if that leaves nothing).
pub fn canon_number(tok: &str) -> String {
    let Ok(x) = tok.parse::<f64>() else {
        return tok.to_string();
    };
    if !x.is_finite() {
        return tok.to_string();
    }
    let s = format!("{x:.4}");
    let s = s.trim_end_matches('0').trim_end_matches('.');
    if s.is_empty() {
        "0".to_string()
    } else {
        s.to_string()
    }
}

/// Every number in `text`, canonicalised, deduplicated, in order of first appearance.
pub fn extract_numbers(text: &str) -> Vec<String> {
    let mut seen = HashSet::new();
    let mut out = Vec::new();
    for mat in num_re().find_iter(text) {
        let c = canon_number(mat.as_str());
        if seen.insert(c.clone()) {
            out.push(c);
        }
    }
    out
}

/// Word-boundary, case-insensitive scan for the shared direction-word list (rule 4/5).
fn has_direction_word(text: &str) -> bool {
    text.split(|c: char| !c.is_alphanumeric())
        .filter(|w| !w.is_empty())
        .any(|w| {
            let lw = w.to_ascii_lowercase();
            crate::alerts::DIRECTION_WORDS.contains(&lw.as_str())
        })
}

/// The two output gates, in order: direction lint, then numeric grounding. A number is grounded
/// if it is in the pack's allowed set OR literally appeared in the user's question (echoing the
/// user is not fabrication). Returns the failed gate's label for metrics.
///
/// `lint_direction` is false for verbatim pack content (template FAQ answers, the greeting):
/// that text is pre-linted by the Python build, and the bare word list would false-positive on
/// non-directional phrases like "data up to 2016". LLM output always gets the full lint.
pub fn gate(
    text: &str,
    allowed: &HashSet<String>,
    question_numbers: &HashSet<String>,
    lint_direction: bool,
) -> Result<(), &'static str> {
    if lint_direction && has_direction_word(text) {
        return Err("direction");
    }
    for mat in num_re().find_iter(text) {
        let c = canon_number(mat.as_str());
        if !allowed.contains(&c) && !question_numbers.contains(&c) {
            return Err("grounding");
        }
    }
    Ok(())
}

/// Best FAQ entry for a question by keyword overlap: an entry needs ≥2 keyword hits (≥1 when it
/// has ≤2 keywords); ties break on normalized score (hits / keyword count), then raw hits.
pub fn faq_best<'a>(faq: &'a [FaqEntry], question: &str) -> Option<&'a FaqEntry> {
    let q = question.to_lowercase();
    let mut best: Option<(f64, usize, &FaqEntry)> = None;
    for e in faq {
        if e.keywords.is_empty() {
            continue;
        }
        let hits = e
            .keywords
            .iter()
            .filter(|k| q.contains(&k.to_lowercase()))
            .count();
        let need = if e.keywords.len() <= 2 { 1 } else { 2 };
        if hits < need {
            continue;
        }
        let score = hits as f64 / e.keywords.len() as f64;
        let better = best
            .as_ref()
            .map(|(s, h, _)| (score, hits) > (*s, *h))
            .unwrap_or(true);
        if better {
            best = Some((score, hits, e));
        }
    }
    best.map(|(_, _, e)| e)
}

fn constant_time_eq(a: &str, b: &str) -> bool {
    a.len() == b.len()
        && a.bytes()
            .zip(b.bytes())
            .fold(0u8, |acc, (x, y)| acc | (x ^ y))
            == 0
}

fn random_hex(n_bytes: usize) -> String {
    let mut buf = vec![0u8; n_bytes];
    rand::thread_rng().fill_bytes(&mut buf);
    hex::encode(buf)
}

/// "YYYY-MM" for the current UTC month (cost-cap bucket).
fn current_month() -> String {
    crate::store::iso_from_unix(now_unix())[..7].to_string()
}

// ---------------------------------------------------------------------------------------------
// middleware + auth
// ---------------------------------------------------------------------------------------------

/// Outermost /avatar/* layer: 503 {"error":"avatar disabled"} while the feature flag is off.
pub async fn require_enabled(State(st): State<AppState>, req: Request, next: Next) -> Response {
    if !st.avatar.enabled {
        return (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(json!({"error": "avatar disabled"})),
        )
            .into_response();
    }
    next.run(req).await
}

/// X-Avatar-Token auth for /avatar/brain and /avatar/heartbeat: the static vendor token
/// (FXRADAR_AVATAR_BRAIN_TOKEN) OR a live short-lived session token minted by
/// /avatar/session-token. Anything else → 401; the route is never open.
fn brain_auth(st: &AppState, headers: &HeaderMap) -> Result<(), ApiError> {
    let tok = headers
        .get("x-avatar-token")
        .and_then(|v| v.to_str().ok())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| {
            ApiError(
                StatusCode::UNAUTHORIZED,
                "missing X-Avatar-Token header".into(),
            )
        })?;
    if let Some(expect) = st.avatar.brain_token.as_deref() {
        if constant_time_eq(tok, expect) {
            return Ok(());
        }
    }
    match st.store.avatar_session_valid(tok, now_unix()) {
        Ok(true) => Ok(()),
        _ => Err(ApiError(
            StatusCode::UNAUTHORIZED,
            "unknown or expired avatar token".into(),
        )),
    }
}

/// X-API-Key check for /avatar/session-token — same semantics as the `auth_paid` middleware
/// (401 unknown/revoked, 429 rate-limited, 403 free tier); done in-handler because the DEV flag
/// may skip it for the "local" vendor only.
fn require_paid_key(st: &AppState, headers: &HeaderMap) -> Result<(), ApiError> {
    let key = headers
        .get("x-api-key")
        .and_then(|v| v.to_str().ok())
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .ok_or_else(|| ApiError(StatusCode::UNAUTHORIZED, "missing X-API-Key header".into()))?;
    let rec = match st.store.lookup_plaintext(&key) {
        Ok(Some(r)) if !r.revoked => r,
        Ok(_) => {
            return Err(ApiError(
                StatusCode::UNAUTHORIZED,
                "unknown or revoked API key".into(),
            ))
        }
        Err(e) => return Err(e.into()),
    };
    if let Err(retry) = st.limiter.check(&rec.key_hash) {
        return Err(ApiError(
            StatusCode::TOO_MANY_REQUESTS,
            format!(
                "rate limit {} requests/min exceeded; retry in {retry}s",
                st.limiter.per_minute()
            ),
        ));
    }
    if !rec.tier.is_paid() {
        return Err(ApiError(
            StatusCode::FORBIDDEN,
            format!(
                "tier {} cannot use this route; pro or partner required",
                rec.tier
            ),
        ));
    }
    Ok(())
}

// ---------------------------------------------------------------------------------------------
// Anthropic Messages API (raw HTTP; Rust has no official SDK)
// ---------------------------------------------------------------------------------------------

fn http_client() -> &'static reqwest::Client {
    static CLIENT: OnceLock<reqwest::Client> = OnceLock::new();
    CLIENT.get_or_init(reqwest::Client::new)
}

/// Read the versioned system prompt file and append CONTEXT + KNOWLEDGE.
fn build_system(st: &AppState, pack: &Pack) -> String {
    let head = std::fs::read_to_string(&st.avatar.system_prompt_path).unwrap_or_else(|e| {
        warn!(path = %st.avatar.system_prompt_path.display(), error = %e,
            "avatar system prompt file unreadable; using the compiled-in fallback");
        FALLBACK_SYSTEM_PROMPT.to_string()
    });
    let knowledge_path = st
        .data_dir
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join(&pack.knowledge_rel);
    let knowledge = std::fs::read_to_string(&knowledge_path).unwrap_or_else(|e| {
        warn!(path = %knowledge_path.display(), error = %e, "avatar knowledge pack unreadable");
        String::new()
    });
    format!(
        "{head}\n\nCONTEXT:\n{}\nKNOWLEDGE:\n{knowledge}",
        pack.context_json
    )
}

/// One non-streaming Messages API call (10 s timeout). Network is allowed here only — tests
/// never take this path (no ANTHROPIC_API_KEY in test configs).
async fn call_anthropic(key: &str, system: &str, messages: &[Value]) -> Result<String, String> {
    let body = json!({
        "model": ANTHROPIC_MODEL,
        "max_tokens": ANTHROPIC_MAX_TOKENS,
        "temperature": ANTHROPIC_TEMPERATURE,
        "system": system,
        "messages": messages,
    });
    let resp = http_client()
        .post("https://api.anthropic.com/v1/messages")
        .header("x-api-key", key)
        .header("anthropic-version", "2023-06-01")
        .header("content-type", "application/json")
        .timeout(Duration::from_secs(10))
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("anthropic request failed: {e}"))?;
    let status = resp.status();
    let v: Value = resp
        .json()
        .await
        .map_err(|e| format!("anthropic response unreadable: {e}"))?;
    if !status.is_success() {
        let msg = v["error"]["message"].as_str().unwrap_or("unknown error");
        return Err(format!("anthropic {status}: {msg}"));
    }
    let text = v["content"]
        .as_array()
        .map(|blocks| {
            blocks
                .iter()
                .filter_map(|b| b.get("text").and_then(|t| t.as_str()))
                .collect::<Vec<_>>()
                .join("")
        })
        .unwrap_or_default();
    if text.trim().is_empty() {
        return Err("anthropic returned no text".into());
    }
    Ok(text)
}

// ---------------------------------------------------------------------------------------------
// request/response types
// ---------------------------------------------------------------------------------------------

#[derive(Deserialize, ToSchema)]
pub struct BrainMessage {
    /// "user" | "assistant"
    pub role: String,
    pub content: String,
}

#[derive(Deserialize, ToSchema)]
pub struct BrainRequest {
    #[serde(default)]
    pub session_id: String,
    /// Conversation so far; the last "user" message is the question.
    #[serde(default)]
    pub messages: Vec<BrainMessage>,
    /// DEV/TEST ONLY (honoured only in debug builds or with FXRADAR_AVATAR_TEST=1): skip
    /// generation and gate this text instead, so tests can prove the gates block fabricated
    /// numbers and direction words. Ignored in production.
    #[serde(default)]
    pub test_force_text: Option<String>,
}

#[derive(Serialize, ToSchema)]
pub struct BrainResponse {
    pub text: String,
    /// "llm" | "template" | "refusal"
    pub source: String,
    /// "pass" | "refused:<kind>" | "regenerated" | "blocked"
    pub gate: String,
    /// Canonical numbers cited in `text` (the widget renders them as receipts).
    pub numbers: Vec<String>,
    pub latency_ms: u64,
}

#[derive(Deserialize, Default, ToSchema)]
pub struct SessionTokenRequest {
    /// "local" | "anam" | "heygen" (default: server-side FXRADAR_AVATAR_VENDOR)
    #[serde(default)]
    pub vendor: Option<String>,
}

#[derive(Deserialize, ToSchema)]
pub struct HeartbeatRequest {
    #[serde(default)]
    pub session_id: String,
    /// Seconds of avatar session time consumed since the last heartbeat.
    pub seconds: f64,
}

// ---------------------------------------------------------------------------------------------
// handlers
// ---------------------------------------------------------------------------------------------

fn load_pack_or_503(st: &AppState) -> Result<std::sync::Arc<Pack>, ApiError> {
    st.avatar_pack()
        .map_err(|e| ApiError(StatusCode::SERVICE_UNAVAILABLE, e))
}

/// Build the final response: metrics, transcript row (after the response is decided; sqlite is
/// microseconds and never blocks generation), receipts.
fn finish(
    st: &AppState,
    session_id: &str,
    question: &str,
    text: String,
    source: &str,
    gate_label: &str,
    t0: Instant,
) -> Json<BrainResponse> {
    let latency_ms = t0.elapsed().as_millis() as u64;
    m::avatar_request(source);
    m::avatar_brain_latency(t0.elapsed().as_secs_f64());
    let numbers = extract_numbers(&text);
    if let Err(e) = st.store.add_transcript(
        session_id,
        question,
        &text,
        source,
        gate_label,
        latency_ms as i64,
    ) {
        warn!(error = %e, "avatar transcript write failed");
    }
    Json(BrainResponse {
        text,
        source: source.into(),
        gate: gate_label.into(),
        numbers,
        latency_ms,
    })
}

/// BYO-LLM brain endpoint: topic guard → generate (LLM, or keyless FAQ fallback) → direction
/// lint → numeric grounding → one corrective regeneration → refusal. Auth: X-Avatar-Token
/// (static vendor token or a live session token).
#[utoipa::path(post, path = "/avatar/brain", tag = "avatar",
    request_body = BrainRequest,
    responses((status = 200, description = "gated answer", body = BrainResponse),
              (status = 400, description = "no user message", body = ApiErrorBody),
              (status = 401, description = "missing/unknown X-Avatar-Token", body = ApiErrorBody),
              (status = 503, description = "avatar disabled or context pack missing", body = Object)))]
pub async fn brain(
    State(st): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<BrainRequest>,
) -> Result<Json<BrainResponse>, ApiError> {
    let t0 = Instant::now();
    brain_auth(&st, &headers)?;
    let pack = load_pack_or_503(&st)?;
    let question = req
        .messages
        .iter()
        .rev()
        .find(|msg| msg.role == "user")
        .map(|msg| msg.content.clone())
        .ok_or_else(|| ApiError(StatusCode::BAD_REQUEST, "no user message in body".into()))?;
    let q_lower = question.to_lowercase();
    let question_numbers: HashSet<String> = extract_numbers(&question).into_iter().collect();

    // (a) topic guard — direction/advice intent short-circuits to the pack's branded refusal.
    if direction_intent_re().is_match(&q_lower) {
        m::avatar_refusal("direction");
        let text = pack.refusals.direction.clone();
        return Ok(finish(
            &st,
            &req.session_id,
            &question,
            text,
            "refusal",
            "refused:direction",
            t0,
        ));
    }
    if advice_intent_re().is_match(&q_lower) {
        m::avatar_refusal("advice");
        let text = pack.refusals.advice.clone();
        return Ok(finish(
            &st,
            &req.session_id,
            &question,
            text,
            "refusal",
            "refused:advice",
            t0,
        ));
    }

    // (b) candidate answer.
    let use_test_hook = req.test_force_text.is_some()
        && (st.avatar.test_hook || std::env::var("FXRADAR_AVATAR_TEST").as_deref() == Ok("1"));
    let llm_messages: Vec<Value> = req
        .messages
        .iter()
        .filter(|msg| msg.role == "user" || msg.role == "assistant")
        .map(|msg| json!({"role": msg.role, "content": msg.content}))
        .collect();
    let mut source: &str;
    let mut candidate: String;
    let mut can_regen = false;
    // The system prompt (file + CONTEXT + KNOWLEDGE) is only needed on the LLM path.
    let system = if st.avatar.anthropic_key.is_some() && !use_test_hook {
        build_system(&st, &pack)
    } else {
        String::new()
    };
    if use_test_hook {
        candidate = req.test_force_text.clone().unwrap_or_default();
        source = "llm"; // gated exactly like a real generation
    } else {
        let llm_text = match st.avatar.anthropic_key.as_deref() {
            Some(key) => match call_anthropic(key, &system, &llm_messages).await {
                Ok(t) => Some(t),
                Err(e) => {
                    warn!(error = %e, "avatar LLM call failed; falling back to the FAQ template");
                    None
                }
            },
            None => None,
        };
        match llm_text {
            Some(t) => {
                candidate = t;
                source = "llm";
                can_regen = true;
            }
            None => match faq_best(&pack.faq, &question) {
                Some(entry) => {
                    candidate = entry.answer.clone();
                    source = "template";
                }
                None => {
                    m::avatar_refusal("off_topic");
                    let text = pack.refusals.off_topic.clone();
                    return Ok(finish(
                        &st,
                        &req.session_id,
                        &question,
                        text,
                        "refusal",
                        "refused:off_topic",
                        t0,
                    ));
                }
            },
        }
    }

    // (c)+(d) gates, with ONE corrective regeneration (LLM path only), then the refusal.
    let mut regenerated = false;
    let gate_label = loop {
        match gate(
            &candidate,
            &pack.allowed,
            &question_numbers,
            source != "template",
        ) {
            Ok(()) => break if regenerated { "regenerated" } else { "pass" },
            Err(reason) => {
                m::avatar_lint_rejection(reason);
                if can_regen && !regenerated {
                    regenerated = true;
                    let mut msgs = llm_messages.clone();
                    msgs.push(json!({"role": "assistant", "content": candidate}));
                    msgs.push(json!({"role": "user", "content": format!(
                        "Your previous answer failed a compliance gate ({reason}). Answer again \
                         using only numbers from CONTEXT and no direction words.")}));
                    if let Some(key) = st.avatar.anthropic_key.as_deref() {
                        if let Ok(t) = call_anthropic(key, &system, &msgs).await {
                            candidate = t;
                            continue;
                        }
                    }
                }
                m::avatar_refusal("not_in_pack");
                candidate = pack.refusals.not_in_pack.clone();
                source = "refusal";
                break "blocked";
            }
        }
    };
    Ok(finish(
        &st,
        &req.session_id,
        &question,
        candidate,
        source,
        gate_label,
        t0,
    ))
}

/// Session greeting: the pack's pre-gated greeting + disclosure. The grounding gate still runs
/// defensively — a failure means the pack is corrupt and answers 500 loudly.
#[utoipa::path(get, path = "/avatar/greeting", tag = "avatar",
    responses((status = 200, description = "greeting + disclosure", body = Object),
              (status = 500, description = "context pack failed its own grounding gate", body = ApiErrorBody),
              (status = 503, description = "avatar disabled or context pack missing", body = Object)))]
pub async fn greeting(State(st): State<AppState>) -> Result<Json<Value>, ApiError> {
    let pack = load_pack_or_503(&st)?;
    let empty = HashSet::new();
    if let Err(reason) = gate(&pack.greeting, &pack.allowed, &empty, false) {
        error!(
            gate = reason,
            "avatar greeting failed its own grounding gate — the context pack is corrupt"
        );
        return Err(ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "avatar context pack failed its own gate; regenerate data/avatar_context.json".into(),
        ));
    }
    Ok(Json(json!({
        "text": pack.greeting,
        "disclosure": pack.disclosure,
        "data_through": pack.data_through,
        "source": "template",
        "disclaimer": DISCLAIMER,
    })))
}

/// Vendor session token, cost-capped per month. "local" mints a short-lived (30 min) random
/// token stored in sqlite — the browser widget never holds a server secret. "anam"/"heygen"
/// proxy the vendor's session-token API (503 when the vendor key is unset — never invented).
#[utoipa::path(post, path = "/avatar/session-token", tag = "avatar", security(("api_key" = [])),
    request_body = SessionTokenRequest,
    responses((status = 200, description = "vendor + token", body = Object),
              (status = 401, description = "missing/unknown API key", body = ApiErrorBody),
              (status = 429, description = "monthly avatar budget reached", body = ApiErrorBody),
              (status = 502, description = "vendor call failed", body = ApiErrorBody),
              (status = 503, description = "avatar disabled or vendor not configured", body = Object)))]
pub async fn session_token(
    State(st): State<AppState>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<Json<Value>, ApiError> {
    // Lenient body: absent/empty → defaults (vendor from FXRADAR_AVATAR_VENDOR).
    let req: SessionTokenRequest = if body.is_empty() {
        SessionTokenRequest::default()
    } else {
        serde_json::from_slice(&body)
            .map_err(|e| ApiError(StatusCode::BAD_REQUEST, format!("bad json: {e}")))?
    };
    let vendor = req
        .vendor
        .map(|v| v.trim().to_ascii_lowercase())
        .filter(|v| !v.is_empty())
        .unwrap_or_else(|| st.avatar.vendor_default.clone());
    if !["local", "anam", "heygen"].contains(&vendor.as_str()) {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "vendor must be local | anam | heygen".into(),
        ));
    }
    // DEV ONLY: FXRADAR_AVATAR_DEV=1 skips the key for the "local" vendor (still cost-capped).
    if !(st.avatar.dev && vendor == "local") {
        require_paid_key(&st, &headers)?;
    }
    let month = current_month();
    let (sessions, minutes) = st.store.avatar_usage(&month)?;
    if sessions >= st.avatar.max_sessions_month || minutes >= st.avatar.max_minutes_month {
        return Err(ApiError(
            StatusCode::TOO_MANY_REQUESTS,
            "monthly avatar budget reached".into(),
        ));
    }
    let session_id = random_hex(8);
    let out = match vendor.as_str() {
        "local" => {
            // The widget talks to /avatar/brain directly with this short-lived token and uses
            // browser TTS + the orb — no external vendor, no per-minute cost.
            let token = st
                .store
                .create_avatar_session(&session_id, SESSION_TTL_SECS)?;
            json!({
                "vendor": "local",
                "brain": "/avatar/brain",
                "token": token,
                "session_id": session_id,
                "expires_in_s": SESSION_TTL_SECS,
                "disclaimer": DISCLAIMER,
            })
        }
        "anam" => {
            // Anam BYO-LLM session-token flow (schema per their docs at build time; if the
            // exact field names differ at runtime this is config-side — the call is proxied
            // as-is and never fakes success). UNVERIFIED without a live ANAM_API_KEY.
            let key = st.avatar.anam_key.as_deref().ok_or_else(|| {
                ApiError(
                    StatusCode::SERVICE_UNAVAILABLE,
                    "anam not configured".into(),
                )
            })?;
            let resp = http_client()
                .post("https://api.anam.ai/v1/auth/session-token")
                .header("Authorization", format!("Bearer {key}"))
                .timeout(Duration::from_secs(10))
                .json(&json!({"personaConfig": {
                    "name": "Radar presenter", "brainType": "CUSTOMER_CLIENT_V1"}}))
                .send()
                .await
                .map_err(|e| ApiError(StatusCode::BAD_GATEWAY, format!("anam: {e}")))?;
            let status = resp.status();
            let v: Value = resp.json().await.unwrap_or(Value::Null);
            if !status.is_success() {
                return Err(ApiError(StatusCode::BAD_GATEWAY, format!("anam {status}")));
            }
            let token = v
                .get("sessionToken")
                .or_else(|| v.get("session_token"))
                .or_else(|| v.get("token"))
                .cloned()
                .unwrap_or(Value::Null);
            json!({"vendor": "anam", "token": token, "session_id": session_id,
                   "disclaimer": DISCLAIMER})
        }
        _ => {
            // HeyGen streaming token flow. UNVERIFIED without a live HEYGEN_API_KEY.
            let key = st.avatar.heygen_key.as_deref().ok_or_else(|| {
                ApiError(
                    StatusCode::SERVICE_UNAVAILABLE,
                    "heygen not configured".into(),
                )
            })?;
            let resp = http_client()
                .post("https://api.heygen.com/v1/streaming.create_token")
                .header("X-Api-Key", key)
                .timeout(Duration::from_secs(10))
                .json(&json!({}))
                .send()
                .await
                .map_err(|e| ApiError(StatusCode::BAD_GATEWAY, format!("heygen: {e}")))?;
            let status = resp.status();
            let v: Value = resp.json().await.unwrap_or(Value::Null);
            if !status.is_success() {
                return Err(ApiError(
                    StatusCode::BAD_GATEWAY,
                    format!("heygen {status}"),
                ));
            }
            let token = v["data"]["token"].clone();
            json!({"vendor": "heygen", "token": token, "session_id": session_id,
                   "disclaimer": DISCLAIMER})
        }
    };
    st.store.add_avatar_session_count(&month)?;
    m::avatar_session();
    Ok(Json(out))
}

/// Session-time accounting for the monthly minutes cap. Auth: X-Avatar-Token (either kind).
#[utoipa::path(post, path = "/avatar/heartbeat", tag = "avatar",
    request_body = HeartbeatRequest,
    responses((status = 200, description = "accumulated minutes this month", body = Object),
              (status = 400, description = "bad seconds", body = ApiErrorBody),
              (status = 401, description = "missing/unknown X-Avatar-Token", body = ApiErrorBody),
              (status = 503, description = "avatar disabled", body = Object)))]
pub async fn heartbeat(
    State(st): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<HeartbeatRequest>,
) -> Result<Json<Value>, ApiError> {
    brain_auth(&st, &headers)?;
    if !(req.seconds.is_finite() && (0.0..=36_000.0).contains(&req.seconds)) {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "seconds must be between 0 and 36000".into(),
        ));
    }
    let minutes = req.seconds / 60.0;
    let month = current_month();
    st.store.add_avatar_minutes(&month, minutes)?;
    m::avatar_minutes(minutes);
    let (_, total) = st.store.avatar_usage(&month)?;
    Ok(Json(
        json!({"ok": true, "session_id": req.session_id, "minutes_month": total}),
    ))
}

// ---------------------------------------------------------------------------------------------
// tests (pure helpers; the HTTP surface is covered by tests/avatar.rs)
// ---------------------------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonical_number_matches_python_form() {
        assert_eq!(canon_number("0.01"), "0.01");
        assert_eq!(canon_number("73.000"), "73");
        assert_eq!(canon_number("0.4200"), "0.42");
        assert_eq!(canon_number("0"), "0");
        assert_eq!(canon_number("0.00"), "0");
        assert_eq!(canon_number("91.6"), "91.6");
        assert_eq!(canon_number("2026"), "2026");
        assert_eq!(canon_number("0.916"), "0.916");
    }

    #[test]
    fn number_extraction_dedupes_in_order() {
        assert_eq!(
            extract_numbers("band 0.00 to 0.51, siren 73 of 100 (0.51 again)"),
            vec!["0", "0.51", "73", "100"]
        );
        assert!(extract_numbers("no numbers here").is_empty());
    }

    #[test]
    fn gates_catch_direction_and_fabrication() {
        let allowed: HashSet<String> = ["0.01", "73"].iter().map(|s| s.to_string()).collect();
        let empty = HashSet::new();
        assert_eq!(
            gate("change risk 0.01, siren 73", &allowed, &empty, true),
            Ok(())
        );
        assert_eq!(
            gate("the euro will rally", &allowed, &empty, true),
            Err("direction")
        );
        assert_eq!(
            gate("Change risk is 0.42", &allowed, &empty, true),
            Err("grounding")
        );
        // echoing the user's own number is not fabrication
        let q: HashSet<String> = ["0.42".to_string()].into_iter().collect();
        assert_eq!(
            gate("you asked about 0.42; the risk is 0.01", &allowed, &q, true),
            Ok(())
        );
        // case-insensitive, word-boundary: "update" must not trip on "up"
        assert_eq!(gate("the daily update ran", &allowed, &empty, true), Ok(()));
        assert_eq!(
            gate("Bullish setups", &allowed, &empty, true),
            Err("direction")
        );
    }

    #[test]
    fn topic_guard_regexes() {
        assert!(direction_intent_re().is_match("will eurusd rise?"));
        assert!(direction_intent_re().is_match("which way is the franc going"));
        assert!(!direction_intent_re().is_match("what is the current regime?"));
        assert!(advice_intent_re().is_match("should i buy dollars?"));
        assert!(advice_intent_re().is_match("help with position sizing"));
        assert!(advice_intent_re().is_match("where do i put my stop-loss"));
        assert!(!advice_intent_re().is_match("what is the siren?"));
    }

    #[test]
    fn faq_matcher_thresholds() {
        let faq = vec![
            FaqEntry {
                q: "What is the siren?".into(),
                keywords: vec!["siren".into()],
                answer: "A".into(),
            },
            FaqEntry {
                q: "What is the change risk?".into(),
                keywords: vec!["change".into(), "risk".into(), "probability".into()],
                answer: "B".into(),
            },
        ];
        assert_eq!(faq_best(&faq, "what is the siren?").unwrap().answer, "A");
        // 3 keywords → needs ≥2 hits
        assert!(faq_best(&faq, "tell me about probability").is_none());
        assert_eq!(
            faq_best(&faq, "what is the change risk?").unwrap().answer,
            "B"
        );
        assert!(faq_best(&faq, "tell me a joke").is_none());
    }
}
