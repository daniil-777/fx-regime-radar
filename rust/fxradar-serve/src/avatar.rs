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
use axum::http::{header, HeaderMap, StatusCode};
use axum::middleware::Next;
use axum::response::{IntoResponse, Response};
use axum::Json;
use rand::RngCore;
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashSet};
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
    /// FXRADAR_AVATAR_ANAM_AVATAR_ID — the persona's face (default: Anam's licensed stock "Cara").
    pub anam_avatar_id: String,
    /// FXRADAR_AVATAR_ANAM_AVATAR_MODEL (default "cara-4").
    pub anam_avatar_model: String,
    /// FXRADAR_AVATAR_ANAM_VOICE_ID — the persona's voice (default: the stock Cara voice).
    pub anam_voice_id: String,
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
    /// FXRADAR_AVATAR_OPEN=1 — open conversation: the system prompt defaults to v2 and the
    /// numeric-grounding gate becomes ANNOTATE-ONLY (gate="open:ungrounded") so general-knowledge
    /// numbers can flow. The topic guard and the direction lint stay fully blocking.
    pub open: bool,
    /// ELEVENLABS_API_KEY: enables realistic TTS on /avatar/tts; unset → 404 {"tts":"browser"}.
    pub elevenlabs_key: Option<String>,
    /// FXRADAR_AVATAR_VOICE_ID (ElevenLabs voice; default "21m00Tcm4TlvDq8ikWAM").
    pub voice_id: String,
    /// FXRADAR_AVATAR_MAX_TTS_CHARS_MONTH (default 100000).
    pub max_tts_chars_month: i64,
    /// FXRADAR_AVATAR_ADVICE=1 — personal hedging decision support from the DETERMINISTIC
    /// decision table (data/decision_table.json). The LLM never produces advice text; with the
    /// flag off, advice intent gets the standard refusal.
    pub advice: bool,
}

impl Default for AvatarCfg {
    fn default() -> Self {
        AvatarCfg {
            enabled: false,
            brain_token: None,
            vendor_default: "local".into(),
            anam_avatar_id: "30fa96d0-26c4-4e55-94a0-517025942e18".into(),
            anam_avatar_model: "cara-4".into(),
            anam_voice_id: "6bfbe25a-979d-40f3-a92b-5394170af54b".into(),
            max_sessions_month: 300,
            max_minutes_month: 600.0,
            anthropic_key: None,
            anam_key: None,
            heygen_key: None,
            system_prompt_path: PathBuf::from("prompts/avatar_system_v1.txt"),
            dev: false,
            test_hook: cfg!(debug_assertions),
            open: false,
            elevenlabs_key: None,
            voice_id: "21m00Tcm4TlvDq8ikWAM".into(),
            max_tts_chars_month: 100_000,
            advice: false,
        }
    }
}

/// Default system prompt file per mode: v2 (conversational) in open mode, v1 otherwise. An
/// explicit FXRADAR_AVATAR_SYSTEM_PROMPT always wins (resolved in `bin/serve.rs`).
pub fn default_system_prompt(open: bool) -> PathBuf {
    PathBuf::from(if open {
        "prompts/avatar_system_v2.txt"
    } else {
        "prompts/avatar_system_v1.txt"
    })
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

#[derive(Debug, Clone, Deserialize, Default)]
pub struct MarketPair {
    #[serde(default)]
    pub label: String,
    #[serde(default)]
    pub regime: String,
    #[serde(default)]
    pub regime_prob: Option<f64>,
    #[serde(default)]
    pub days_in_regime: Option<i64>,
    #[serde(default)]
    pub change_risk_5d: Option<f64>,
    #[serde(default)]
    pub risk_lo: Option<f64>,
    #[serde(default)]
    pub risk_hi: Option<f64>,
    #[serde(default)]
    pub anomaly_pct: Option<f64>,
    #[serde(default)]
    pub agreement: Option<i64>,
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct MarketUniverse {
    #[serde(default)]
    pub label: String,
    #[serde(default)]
    pub data_through: String,
    #[serde(default)]
    pub pairs: BTreeMap<String, MarketPair>,
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
    /// Every universe the radar computes (fx/g10/em/crypto), for the deterministic market lookup.
    pub markets: BTreeMap<String, MarketUniverse>,
    /// The same markets as one line each, for the LLM context block.
    pub markets_compact: String,
    /// Short chain head of the sealed ledger, so a receipt can tell the reader what to verify
    /// against. Empty when the pack predates the ledger.
    pub chain_head: String,
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
    #[serde(default)]
    markets: BTreeMap<String, MarketUniverse>,
    #[serde(default)]
    ledger: LedgerBlock,
}

#[derive(Deserialize, Default)]
struct LedgerBlock {
    #[serde(default)]
    chain_head_short: String,
}

/// Load and parse the context pack. Errors are strings so the caller can map them to 503.
/// One line per market instead of a JSON object each. The full `markets` block is ~1,600 tokens of
/// a ~5,100-token pack and rides into EVERY LLM call, even though market questions are answered
/// deterministically before the model is reached. The compact form keeps every number available for
/// the rare cross-market question at roughly a fifth of the cost. The grounding gate is unaffected:
/// `allowed_numbers` is computed by the Python build from the complete pack, not from this text.
fn compact_markets(markets: &BTreeMap<String, MarketUniverse>) -> String {
    let mut out = String::new();
    for (name, uni) in markets {
        out.push_str(&format!(
            "{} ({}, through {}):\n",
            name, uni.label, uni.data_through
        ));
        for (pair, p) in &uni.pairs {
            out.push_str(&format!(
                "  {pair} {} risk {} band {} to {} siren {} consensus {}/3\n",
                p.regime,
                fmt_opt(p.change_risk_5d),
                fmt_opt(p.risk_lo),
                fmt_opt(p.risk_hi),
                p.anomaly_pct
                    .map(|v| format!("{v:.0}"))
                    .unwrap_or_else(|| "-".into()),
                p.agreement
                    .map(|v| v.to_string())
                    .unwrap_or_else(|| "-".into()),
            ));
        }
    }
    out
}

fn fmt_opt(v: Option<f64>) -> String {
    v.map(|x| format!("{x:.2}")).unwrap_or_else(|| "-".into())
}

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
        obj.remove("markets"); // re-injected compactly by build_system (see compact_markets)
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
        markets_compact: compact_markets(&pf.markets),
        markets: pf.markets,
        chain_head: pf.ledger.chain_head_short,
    })
}

// ---------------------------------------------------------------------------------------------
// decision table (advice mode): data/decision_table.json, written by the Python pipeline
// ---------------------------------------------------------------------------------------------

#[derive(Debug, Clone, Deserialize)]
pub struct Tranche {
    pub week: i64,
    pub fraction: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct DecisionRow {
    pub light: String,
    pub regime: String,
    pub hedge_ratio: f64,
    #[serde(default)]
    pub schedule_by_horizon: std::collections::BTreeMap<String, Vec<Tranche>>,
    pub es_99_1w: f64,
    #[serde(default)]
    pub es_95_1w: f64,
    #[serde(default)]
    pub var_99_1w: f64,
    #[serde(default)]
    pub review_trigger: String,
}

/// pairs: PAIR → tolerance (conservative|balanced|aggressive) → row.
#[derive(Debug, Clone, Deserialize)]
pub struct DecisionTable {
    #[serde(default)]
    pub disclosure: String,
    #[serde(default)]
    pub fx: std::collections::HashMap<String, f64>,
    #[serde(default)]
    pub pairs: std::collections::BTreeMap<String, std::collections::BTreeMap<String, DecisionRow>>,
}

/// mtime-keyed cache entry held in [`AppState`].
pub struct DecisionCache {
    pub modified: SystemTime,
    pub len: u64,
    pub table: std::sync::Arc<DecisionTable>,
}

pub fn load_decision_table(path: &Path) -> Result<DecisionTable, String> {
    let raw = std::fs::read_to_string(path)
        .map_err(|e| format!("decision table unreadable ({}): {e}", path.display()))?;
    serde_json::from_str(&raw).map_err(|e| format!("decision table has a bad shape: {e}"))
}

/// What the advice builder needs from the user's question (parsed deterministically, defaults
/// applied — never by the LLM).
#[derive(Debug, Clone, PartialEq)]
pub struct AdviceQuery {
    pub pair: String,
    pub amount: Option<f64>,
    /// "EUR" | "USD" | "CHF" | "GBP" when the user named one.
    pub currency: Option<String>,
    /// One of 1, 2, 4, 8, 12 (table horizons).
    pub horizon_weeks: u8,
    /// "conservative" | "balanced" | "aggressive".
    pub tolerance: String,
}

fn amount_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(
            r"(\d[\d'.,]*)\s*(k|m|thousand|million)?\s*(euros?|eur|€|dollars?|usd|\$|francs?|chf|pounds?|gbp|£)",
        )
        .expect("static regex")
    })
}

fn weeks_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"(\d+)\s*week").expect("static regex"))
}

fn months_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"(\d+)\s*month").expect("static regex"))
}

fn risk_tolerant_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"risk.?tolerant").expect("static regex"))
}

/// Nearest table horizon (ties resolve to the shorter one).
fn nearest_horizon(h: i64) -> u8 {
    let h = h.clamp(1, 12);
    *[1u8, 2, 4, 8, 12]
        .iter()
        .min_by_key(|&&o| ((i64::from(o) - h).abs(), o))
        .expect("non-empty")
}

/// Parse pair / amount+currency / horizon / tolerance from an advice question, with defaults.
pub fn parse_advice_query(question: &str, default_pair: &str) -> AdviceQuery {
    let q = question.to_lowercase();
    let words: Vec<String> = q
        .split(|c: char| !c.is_alphanumeric())
        .filter(|w| !w.is_empty())
        .map(|w| w.to_string())
        .collect();
    let has = |w: &str| words.iter().any(|x| x == w);
    let pair = if has("eurusd") || has("euro") || has("euros") || has("eur") || q.contains('€') {
        "EURUSD".to_string()
    } else if has("usdchf") || has("franc") || has("francs") || has("chf") {
        "USDCHF".to_string()
    } else if has("gbpusd")
        || has("pound")
        || has("pounds")
        || has("sterling")
        || has("gbp")
        || q.contains('£')
    {
        "GBPUSD".to_string()
    } else {
        default_pair.to_string()
    };
    let (amount, currency) = match amount_re().captures(&q) {
        Some(c) => {
            let raw: String = c[1]
                .chars()
                .filter(|ch| *ch != '\'' && *ch != ',')
                .collect();
            let mult = match c.get(2).map(|mm| mm.as_str()) {
                Some("k") | Some("thousand") => 1e3,
                Some("m") | Some("million") => 1e6,
                _ => 1.0,
            };
            let cur = match &c[3] {
                x if x.starts_with("euro") || x == "eur" || x == "€" => "EUR",
                x if x.starts_with("dollar") || x == "usd" || x == "$" => "USD",
                x if x.starts_with("franc") || x == "chf" => "CHF",
                _ => "GBP",
            };
            (
                raw.parse::<f64>().ok().map(|a| a * mult),
                Some(cur.to_string()),
            )
        }
        None => (None, None),
    };
    let currency = if amount.is_some() { currency } else { None };
    let horizon = weeks_re()
        .captures(&q)
        .and_then(|c| c[1].parse::<i64>().ok())
        .or_else(|| {
            months_re()
                .captures(&q)
                .and_then(|c| c[1].parse::<i64>().ok())
                .map(|n| n * 4)
        })
        .unwrap_or(4);
    let tolerance = if has("conservative") || has("cautious") || has("careful") {
        "conservative"
    } else if has("aggressive") || risk_tolerant_re().is_match(&q) {
        "aggressive"
    } else {
        "balanced"
    };
    AdviceQuery {
        pair,
        amount,
        currency,
        horizon_weeks: nearest_horizon(horizon),
        tolerance: tolerance.to_string(),
    }
}

fn capitalize_first(s: &str) -> String {
    let mut c = s.chars();
    match c.next() {
        Some(f) => f.to_uppercase().collect::<String>() + c.as_str(),
        None => String::new(),
    }
}

/// Deterministic decision-support text from the table row — the LLM NEVER writes advice.
/// Returns (text, numbers-in-text): every number is arithmetic over the table and the user's
/// own inputs, so the grounding gate accepts them by construction. The direction lint still
/// runs for real on the result.
pub fn build_advice(
    table: &DecisionTable,
    q: &AdviceQuery,
    with_disclosure: bool,
) -> Option<(String, Vec<String>)> {
    let row = table.pairs.get(&q.pair)?.get(&q.tolerance)?;
    if q.pair.len() != 6 {
        return None;
    }
    let label = format!("{}/{}", &q.pair[..3], &q.pair[3..]);
    let h = q.horizon_weeks;
    let weeks_word = if h == 1 { "week" } else { "weeks" };
    let ratio_pct = format!("{:.0}", row.hedge_ratio * 100.0);
    let fmt_pct = |f: f64| format!("{:.0}", f * 100.0);
    let sched = row
        .schedule_by_horizon
        .get(&h.to_string())
        .cloned()
        .unwrap_or_else(|| {
            vec![Tranche {
                week: 0,
                fraction: row.hedge_ratio,
            }]
        });
    let schedule = if sched.len() <= 1 {
        format!("all {ratio_pct}% now")
    } else {
        let head = format!("{}% now", fmt_pct(sched[0].fraction));
        let rest = &sched[1..];
        let uniform = rest
            .windows(2)
            .all(|w| (w[0].fraction - w[1].fraction).abs() < 1e-12 && w[1].week == w[0].week + 1)
            && rest[0].week == 1;
        if uniform {
            format!(
                "{head}, then {}% in each of the next {} weeks",
                fmt_pct(rest[0].fraction),
                rest.len()
            )
        } else {
            let parts: Vec<String> = rest
                .iter()
                .map(|t| format!("{}% in week {}", fmt_pct(t.fraction), t.week))
                .collect();
            format!("{head}, then {}", parts.join(", "))
        }
    };
    let es_h = row.es_99_1w * f64::from(h).sqrt();
    let risk = match q.amount {
        Some(a) => {
            // The user always names a currency alongside an amount (the regex requires it), so
            // the figure stays in their currency; the CHF conversion via table.fx covers the
            // defensive no-currency case only.
            let (money_raw, cur) = match q.currency.as_deref() {
                Some(cur) => (a * (1.0 - row.hedge_ratio) * es_h, cur.to_string()),
                None => {
                    let to_chf = match q.pair.as_str() {
                        "EURUSD" => table.fx.get("EURCHF").copied().unwrap_or(1.0),
                        "GBPUSD" => table.fx.get("GBPCHF").copied().unwrap_or(1.0),
                        _ => 1.0,
                    };
                    (a * (1.0 - row.hedge_ratio) * es_h * to_chf, "CHF".to_string())
                }
            };
            let money = ((money_raw / 100.0).round() * 100.0) as i64;
            format!(
                "Leaving the rest uncovered carries a 99% expected shortfall of about {money} {cur} over that horizon"
            )
        }
        None => format!(
            "Leaving the rest uncovered carries a 99% expected shortfall of about {:.1}% of the amount over that horizon",
            es_h * 100.0
        ),
    };
    let review = capitalize_first(row.review_trigger.trim());
    let body = format!(
        "For a {} profile on {label} over {h} {weeks_word}: cover {ratio_pct}% of the exposure — {schedule}. {risk}. {review}. Today's light: {} ({} regime).",
        q.tolerance, row.light, row.regime
    );
    let text = if with_disclosure {
        format!("{} {body}", table.disclosure)
    } else {
        body
    };
    let numbers = extract_numbers(&text);
    Some((text, numbers))
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
        // Widened in phase 43. The phase-41 report measured this as the product's largest remaining
        // quality gap: direction questions were refused (nothing directional was ever spoken) but
        // only one in twelve got the branded direction refusal — the rest got a tangential answer
        // or the generic off-topic line, which reads as evasion rather than as a principle.
        // Continuous and progressive forms, the German and French equivalents, and the ordinary
        // ways a treasurer phrases it are all direction questions and all now say so.
        //
        // Written with concat! rather than one long raw string: a raw string cannot be wrapped with
        // a backslash continuation, and doing so silently inserts a literal newline into the
        // pattern, which quietly disables every alternative after the break.
        Regex::new(concat!(
            r"\b(rise|rises|rising|risen|fall|falls|falling|fallen|",
            r"go up|goes up|going up|go down|goes down|going down|",
            r"go(?:es|ing)? (?:higher|lower)|went (?:up|down|higher|lower)|",
            r"head(?:ed|ing)? (?:up|down|higher|lower)|",
            r"mov(?:e|es|ing) (?:up|down|higher|lower)|",
            r"drop|drops|dropping|rally|rallies|bullish|bearish|",
            // The BLUNTEST phrasings, which the rule set missed entirely because it was tuned
            // against clever adversarial questions. "What would be your prediction of the market
            // of the franc" walked straight through and got a calm condition card. The plain word
            // is the one most people use.
            // NOT the bare nouns "forecast" / "prediction". They are ambiguous in this product in
            // a way that bit immediately: "how many sealed forecasts so far?" is a question about
            // the LEDGER — the thing that makes this system checkable — and adding the bare word
            // here refused it as a price call. The forecast-shaped ASKS are matched with their
            // context by `guard::plain_forecast_ask` instead, which needs "your forecast" or
            // "forecast for <market>" and so cannot swallow a count.
            r"target|price target|crystal ball|",
            r"prognose|vorhersage|voraussage|einsch(?:ä|ae)tzung|",
            r"pr(?:é|e)vision|pronostic|",
            r"which way|higher or lower|up or down|",
            r"appreciate|depreciate|strengthen|strengthens|strengthening|",
            r"weaken|weakens|weakening|weaker|stronger|softer|firmer|",
            r"worth more|worth less|cheaper|more expensive|",
            // German: the eval found "steigt", "fällt" and "schwächer" arriving in questions the
            // English list could never have matched.
            r"steigen|steigt|steigend|f(?:ä|ae)llt|fallen|sinkt|sinken|",
            r"st(?:ä|ae)rker|schw(?:ä|ae)cher|aufwerten|abwerten|hoch oder runter|",
            // French: "monte ou baisse" is how the question is actually asked, not "monter".
            r"monte|montent|monter|baisse|baissent|baisser|hausse|",
            r"plus fort|plus faible|va-t-il monter|va monter)\b",
        ))
        .expect("static regex")
    })
}

/// Does the question ask which way a PRICE will go?
///
/// The movement words alone are not enough. "Is volatility falling?", "is the siren going up?" and
/// "is change risk rising?" all contain them and are all questions this radar exists to answer —
/// they ask about quantities we publish, not about a rate. Refusing those would be a different
/// failure from the one the direction ban prevents, and an equally bad one: a product that refuses
/// its own subject matter teaches the user it cannot help.
///
/// So: a movement word makes a question directional only when it is NOT about one of the published
/// non-price quantities.
fn asks_price_direction(q: &str) -> bool {
    let Some(hit) = direction_intent_re().find(q) else {
        return false;
    };
    // A CONDITIONAL is not a forecast. "What would a 3% drop cost us on 2.4 million of receivables"
    // supplies the move and asks for the arithmetic; it neither asks nor implies which way the rate
    // goes, and the scenario engine exists precisely to answer it. Refusing it would be the guard
    // failing the person it was built to serve — the treasurer with a real exposure and a real
    // question — while protecting nobody, since no direction claim is anywhere in it.
    //
    // Callers that normalise the text decide this once on the ORIGINAL and short-circuit; the check
    // stays here so a caller that forgets still gets the right answer on un-normalised input.
    if conditional_scenario_re().is_match(q) {
        return false;
    }
    // The exemption is PROXIMITY-based, not sentence-based.
    //
    // The first version asked "does this sentence mention volatility, risk or the siren anywhere?"
    // and exempted it if so. That is wrong in a way the eval caught: "risk jumped on cable — so
    // sterling weaker this week?" mentions risk in its PREMISE and asks about the rate in its
    // QUESTION. Scanning the whole sentence let the premise excuse the question, which is exactly
    // the smuggling pattern the framing rules exist to stop, arriving through the guard meant to
    // prevent over-refusal.
    //
    // So look only at what the movement word is attached to: a short window before it, and a
    // couple of words after. "volatility falling" and "the siren is going up" keep their exemption;
    // "sterling weaker" does not get one from a clause it does not belong to.
    let start = q[..hit.start()]
        .char_indices()
        .rev()
        .take(48)
        .last()
        .map_or(0, |(i, _)| i);
    let end = q[hit.end()..]
        .char_indices()
        .take(20)
        .last()
        .map_or(hit.end(), |(i, c)| hit.end() + i + c.len_utf8());
    !non_price_subject_re().is_match(&q[start..end])
}

/// Small talk, which is not off-topic — it is the beginning and end of every real conversation.
///
/// Nine golden items are "hi", "thx", "ok", "sorry can u repeat that", "whats your name",
/// "sprichst du deutsch?", "merci c'est bon". Every one came back with the branded off-topic
/// refusal — "I only speak from the published numbers" — in answer to somebody saying thank you.
/// A product that refuses a greeting has not protected anything; it has just told the user it is
/// not really talking to them.
///
/// These answers are fixed strings, so nothing here can invent a number or a market claim, and
/// they all pass the same gates as any other answer.
fn courtesy_reply(q: &str) -> Option<&'static str> {
    let t = q
        .trim()
        .trim_end_matches(['?', '!', '.'])
        .trim()
        .to_lowercase();
    // A greeting is short; a long sentence that merely opens with "hi" is a question. Identity
    // questions get more room, because "wait, are you a real person?" is how it actually gets
    // asked — and answering it is the Article 50 disclosure, not small talk.
    let identity = t.contains("real person")
        || t.contains("are you human")
        || t.contains("are you a bot")
        || t.contains("are you an ai")
        || t.contains("who are you");
    if t.len() > 40 && !(identity && t.len() <= 70) {
        return None;
    }
    let is = |set: &[&str]| {
        set.iter()
            .any(|w| t == *w || t.starts_with(&format!("{w} ")))
    };
    if is(&[
        "hi",
        "hello",
        "hey",
        "good morning",
        "good afternoon",
        "good evening",
        "hallo",
        "guten morgen",
        "guten tag",
        "grüezi",
        "gruezi",
        "salut",
        "bonjour",
    ]) {
        return Some("Hello. Ask me about today's regime, the change risk, the siren, or how any of it is computed.");
    }
    if is(&[
        "thanks",
        "thank you",
        "thx",
        "ta",
        "cheers",
        "danke",
        "vielen dank",
        "merci",
        "merci c'est bon",
        "ok",
        "okay",
        "got it",
        "alles klar",
        "d'accord",
    ]) {
        return Some(
            "Any time. I am here if you want another market or the method behind a number.",
        );
    }
    if is(&["bye", "goodbye", "tschüss", "tschuess", "au revoir", "ciao"]) {
        return Some("Goodbye. The published reading is on the dashboard whenever you need it.");
    }
    if t.contains("your name")
        || t.contains("who are you")
        // "Wait, are you a real person?" is the Article 50 disclosure question, asked the way
        // people actually ask it. Answering it plainly is a compliance obligation, not small talk;
        // it was coming back as "that's outside what I know".
        || t.contains("real person")
        || t.contains("are you human")
        || t.contains("are you a bot")
        || t.contains("are you an ai")
        || t.contains("bist du echt")
        || t.contains("wie heisst du")
        || t.contains("wer bist du")
        || t.contains("comment tu t'appelles")
    {
        return Some(
            "I am the radar's AI presenter — a computer-generated voice, not a person. I read out              what the models published and how they computed it.",
        );
    }
    if t.contains("sprichst du")
        || t.contains("do you speak")
        || t.contains("parlez-vous")
        || t.contains("tu parles")
    {
        return Some("Yes — English, German and French. Ask in whichever you prefer.");
    }
    if t.contains("repeat")
        || t.contains("say that again")
        || t.contains("noch mal")
        || t.contains("nochmal")
        || t.contains("répète")
        || t.contains("repete")
    {
        return Some("Of course — ask me again and I will give you the same reading.");
    }
    None
}

/// A stated hypothetical move, asked for its consequence rather than its likelihood.
///
/// The user supplies the move, so the system is never the source of a directional claim — it is
/// doing arithmetic on somebody else's premise, with the premise stated out loud in the question.
fn conditional_scenario_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(concat!(
            r"(?i)(what|how much) would (a|an|the)? ?[\d.]+\s?(%|percent|pct|bp|basis) ",
            r"?\w*\s?(drop|fall|move|rise|gain|loss|swing|shift)",
            r"|if (the |it |eur|usd|gbp|chf|the rate |the pair )?\w*\s?(dropped|fell|moved|rose|gained|weakened|strengthened) ",
            r"?(by )?[\d.]+\s?(%|percent|pct|bp)",
            r"|(a|an) [\d.]+\s?(%|percent|pct|bp)\s?\w*\s?(drop|fall|move|rise|swing) (would|costs?|means?)",
            r"|was (w(?:ü|ue)rde|kostet) (ein|eine) [\d.]+\s?(%|prozent)",
        ))
        .expect("static regex")
    })
}

/// The quantities this radar publishes, which may rise and fall freely in conversation.
fn non_price_subject_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(concat!(
            r"\b(volatilit(?:y|ä|ae|e)\w*|vola|vol|risk|risiko|risque|",
            r"siren|sirene|sir(?:è|e)ne|anomaly|anomalie|regime\w*|r(?:é|e)gime|",
            r"uncertainty|unsicherheit|incertitude|entropy|entropie|",
            r"consensus|konsens|drawdown|brier|coverage|turnover|",
            // Questions about the MODEL rather than about a price. "How do you forecast regime
            // change", "what is your forecast accuracy", "what is your Brier score" all contain
            // forecast words and are all questions this product must answer — refusing them would
            // make the widening above a bigger bug than the one it fixes.
            r"model|models|method|methodology|accuracy|accurate|skill|calibrat\w*|",
            r"backtest|pipeline|system|score|scores|track record|forecaster)\b",
        ))
        .expect("static regex")
    })
}

/// Is the user asserting a figure of their own — a planted number, a misremembered one, or an
/// arithmetic request over values we never published?
fn asserts_a_figure(q: &str) -> bool {
    if !q.chars().any(|c| c.is_ascii_digit()) {
        return false;
    }
    const CUES: [&str; 8] = [
        "you said",
        "you've got",
        "you have",
        "earlier you",
        "is still",
        "what's that as",
        "multiply",
        "as a percentage",
    ];
    if CUES.iter().any(|c| q.contains(c)) {
        return true;
    }
    // "Is the change risk 0.87 today?" and "confirm the siren is 42" plant a figure and invite a
    // yes. Answering either from the general path would let the user leave believing we confirmed
    // a number we never published — the planted-number family exists for exactly this, and it was
    // catching only the "you said" phrasings.
    planted_figure_re().is_match(q)
}

/// A figure asserted in the question and offered for confirmation.
fn planted_figure_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(concat!(
            r"(?i)\b(is|are|was|isn't|ist|est)\b[^?]{0,40}\b",
            r"(change risk|risk|siren|anomaly|regime prob\w*|brier|coverage|risiko|sirene)\b",
            r"[^?]{0,20}[\d]",
            r"|(?i)\b(confirm|bestätige|bestaetige|confirme)\b[^?]{0,60}[\d]",
            r"|(?i)\b(change risk|siren|risk|risiko|sirene)\b\s*(is|=|ist|est)\s*[\d]",
        ))
        .expect("static regex")
    })
}

/// Does the question name published DATA (as opposed to asking what a term means)? Used to stop a
/// glossary entry from standing in for a historical reading it cannot provide.
/// Is this a question about how the system WORKS, rather than about what it currently reads?
fn methodology_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(concat!(
            r"(?i)\b(hmm|hidden markov|xgboost|autoencoder|bocpd|changepoint|",
            r"embargo|look-?ahead|leakage|truncation|walk-?forward|",
            r"how (many|does|do) .{0,25}(state|states|model|models|algorithm)|",
            r"(model|models|algorithm|pipeline) (work|works|trained|training|is trained)|",
            r"how (is|are) .{0,20}(model|models|it) trained|",
            r"funktioniert|trainiert|entra(?:î|i)n(?:é|e))\b",
        ))
        .expect("static regex")
    })
}

fn mentions_data(q: &str) -> bool {
    // A question about how the MODEL works is methodology, not a reading. "How many states does
    // the regime model have?" names a regime and asks "how many", so the pre-router sent it to the
    // archive, the archive had no such shape, and the archive-miss refusal fired before the FAQ —
    // which answers it — was ever consulted. Methodology wins over the data reading here because
    // no archive shape will ever answer a question about the model's construction.
    if methodology_re().is_match(q) {
        return false;
    }
    const WORDS: [&str; 10] = [
        "risk",
        "siren",
        "regime",
        "band",
        "consensus",
        "volatility",
        "vol",
        "crisis",
        "calm",
        "chop",
    ];
    WORDS.iter().any(|w| q.contains(w))
}

/// Does the question actually concern covering an exposure?
fn hedging_intent_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(
            r"\b(hedge|hedging|cover|covering|coverage of|exposure|receivable|payable|invoice|tranche|ladder|forward|unhedged|protect)\b",
        )
        .expect("static regex")
    })
}

fn advice_intent_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        // "position siz\w*" so "position sizing"/"position size" both match the intent guard.
        // "should i" alone was far too greedy: "why should I trust you" routed a TRUST question
        // into the hedging decision engine. The verb after it is what makes it an advice request.
        Regex::new(
            r"\b(should i (buy|sell|hedge|cover|invest|allocate|go long|go short|lock|ladder|wait|act|do (anything|something|it))|buy|sell|hedge my|stop.?loss|position siz\w*|invest|portfolio|advice|what would you do)\b",
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
        // A single keyword hit is enough for "what is a regime?" and far too little for "what's the
        // Sharpe ratio on the USD/CHF regime overlay this year" — which matched on the word
        // "regime" and came back with the definition of a regime. Longer questions are more
        // specific, so they must match more of the entry to earn it.
        let q_words = q.split_whitespace().count();
        let need = if q_words > 6 {
            2
        } else if e.keywords.len() <= 2 {
            1
        } else {
            2
        };
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

/// Currency-word synonyms for the market lookup ("yen" → jpy). "usd"/"dollar" are deliberately
/// absent (every pair contains the dollar) and so is "real" (too common an English word; say
/// "brazilian" or "USDBRL").
/// Every market word a person might say, mapped to its currency/asset leg and a human name.
///
/// ONE table, deliberately including markets this radar does NOT publish. Coverage is decided
/// against the pack at call time, never by omission from this list — that distinction is the whole
/// point. A word that is missing here reads as "no market named", and the caller then answers about
/// the lead market: that is how "how unusual is the Norwegian krone today?" returned EUR/USD's
/// siren. Listing the krone lets the system say "I don't cover that" instead of substituting.
const CCY_SYNONYMS: &[(&str, &str, &str)] = &[
    // covered, or covered depending on the configured universes
    ("yen", "jpy", "the yen"),
    ("sterling", "gbp", "sterling"),
    ("pound", "gbp", "the pound"),
    ("cable", "gbp", "cable"),
    ("quid", "gbp", "the pound"),
    ("euro", "eur", "the euro"),
    ("franc", "chf", "the franc"),
    ("swissy", "chf", "the franc"),
    ("swissie", "chf", "the franc"),
    ("aussie", "aud", "the Australian dollar"),
    ("australian", "aud", "the Australian dollar"),
    ("kiwi", "nzd", "the New Zealand dollar"),
    ("loonie", "cad", "the Canadian dollar"),
    ("canadian", "cad", "the Canadian dollar"),
    ("krona", "sek", "the Swedish krona"),
    ("swedish", "sek", "the Swedish krona"),
    ("krone", "nok", "the Norwegian krone"),
    ("norwegian", "nok", "the Norwegian krone"),
    ("peso", "mxn", "the Mexican peso"),
    ("mexican", "mxn", "the Mexican peso"),
    ("brazilian", "brl", "the Brazilian real"),
    // NOT bare "real": "wait, are you a real person?" was being declined as a question about the
    // Brazilian real. A market word that is also an ordinary English word costs more than it wins.
    ("brl", "brl", "the Brazilian real"),
    ("rand", "zar", "the rand"),
    ("zloty", "pln", "the zloty"),
    ("polish", "pln", "the zloty"),
    ("ruble", "rub", "the rouble"),
    ("rouble", "rub", "the rouble"),
    ("russian", "rub", "the rouble"),
    ("lira", "try", "the Turkish lira"),
    ("turkish", "try", "the Turkish lira"),
    ("bitcoin", "btc", "Bitcoin"),
    ("ethereum", "eth", "Ether"),
    ("ether", "eth", "Ether"),
    ("ripple", "xrp", "XRP"),
    ("cardano", "ada", "Cardano"),
    ("binance", "bnb", "BNB"),
    // named here precisely so they can be DECLINED rather than silently substituted
    ("baht", "thb", "the Thai baht"),
    ("rupee", "inr", "the Indian rupee"),
    ("yuan", "cny", "the Chinese yuan"),
    ("renminbi", "cny", "the Chinese yuan"),
    ("won", "krw", "the Korean won"),
    ("shekel", "ils", "the Israeli shekel"),
    ("forint", "huf", "the Hungarian forint"),
    ("koruna", "czk", "the Czech koruna"),
    ("ringgit", "myr", "the Malaysian ringgit"),
    ("rupiah", "idr", "the Indonesian rupiah"),
    ("gold", "xau", "gold"),
    ("silver", "xag", "silver"),
    ("copper", "xcu", "copper"),
    ("oil", "oil", "oil"),
    ("brent", "oil", "Brent crude"),
    ("wti", "oil", "WTI crude"),
    ("nasdaq", "ndx", "the Nasdaq"),
    ("dax", "dax", "the DAX"),
    ("smi", "smi", "the SMI"),
    ("ftse", "ftse", "the FTSE"),
    ("nikkei", "nky", "the Nikkei"),
    ("vix", "vix", "the VIX"),
    ("dogecoin", "doge", "Dogecoin"),
    ("doge", "doge", "Dogecoin"),
    ("solana", "sol", "Solana"),
    ("litecoin", "ltc", "Litecoin"),
    ("polkadot", "dot", "Polkadot"),
];

/// Does this text name a market other than the one the question asked about?
///
/// The last line of defence, and deliberately a dumb one. Card arguments are steered by the pair
/// hint, but some cards carry a market in their CAPTION without carrying it as an argument — so
/// "show me the volatility of the aussie" could still come back captioned "EUR/USD realised
/// volatility over 5y". Every layer above this is about picking the right card; this one asks a
/// single question of whatever was picked — does it talk about a different market than the user
/// asked about — and drops it if so.
///
/// It fires only on a CONFLICT, never on absence. A caption that names no market is left alone:
/// silence is not a wrong claim, and being too eager here would empty boards that were fine.
pub fn names_a_different_market(text: &str, hint: &str) -> bool {
    let want: String = hint
        .to_uppercase()
        .chars()
        .filter(|c| c.is_ascii_alphanumeric())
        .collect();
    let upper = text.to_uppercase();
    let compact: String = upper
        .chars()
        .filter(|c| c.is_ascii_alphanumeric())
        .collect();
    // Six-letter codes and their slashed display forms: EURUSD, EUR/USD, BTC-USD, BTC/USD.
    let mut found_other = false;
    let bytes: Vec<char> = compact.chars().collect();
    for i in 0..bytes.len().saturating_sub(5) {
        let window: String = bytes[i..i + 6].iter().collect();
        if !window.chars().all(|c| c.is_ascii_alphabetic()) {
            continue;
        }
        if !KNOWN_LEG_PREFIXES
            .iter()
            .any(|p| window.starts_with(p) || window[3..].starts_with(p))
        {
            continue;
        }
        if window == want {
            return false; // it names the market we asked about: settled, keep it
        }
        found_other = true;
    }
    found_other
}

/// Currency and asset legs that make a six-letter run an actual market code rather than a word.
const KNOWN_LEG_PREFIXES: &[&str] = &[
    "EUR", "USD", "CHF", "GBP", "JPY", "AUD", "NZD", "CAD", "SEK", "NOK", "MXN", "BRL", "ZAR",
    "PLN", "RUB", "TRY", "BTC", "ETH", "XRP", "ADA", "BNB",
];

/// The uncovered-market refusal, defined once: the live handler and the replay must produce the
/// identical text, or every replayed lira/krone question shows a phantom divergence (phase 43).
pub fn uncovered_refusal_text(pack: &Pack, name: &str) -> String {
    let covered: Vec<String> = pack
        .markets
        .values()
        .map(|u| u.label.clone())
        .filter(|l| !l.is_empty())
        .collect();
    format!(
        "I don't cover {name}, so I have no reading for it — and I won't hand you another \
         market's numbers in its place. What I do carry is {}.",
        if covered.is_empty() {
            "the currency pairs on the radar".to_string()
        } else {
            covered.join(", ")
        }
    )
}

/// What market, if any, this question is about.
#[derive(Debug, Clone, PartialEq)]
pub enum MarketMention {
    /// No market named — the lead market is a reasonable default.
    None,
    /// A market this radar publishes.
    Covered(String),
    /// A market-shaped name this radar does not publish. Never substitute another one.
    Uncovered(String),
}

/// The ONE place a question is turned into a market.
///
/// There were four implementations of this before, with four different vocabularies, and the
/// weakest of them owned the path that long questions fall through to. The result was that
/// "hi what would be your prediction of the market of the franc" answered about EUR/USD: the board
/// selector matched only the literal pair CODE, found nothing, and took the default. A caption
/// saying EUR/USD in answer to a question about the franc is not a near miss — every number in it
/// is real and about the wrong thing, which is the most dangerous answer this product can give.
///
/// Unlike `market_lookup_pair` this is NOT gated on sentence length: identifying which market a
/// question is about and deciding whether the question wants a condition read are two different
/// jobs, and merging them is what let long questions escape the good resolver.
pub fn resolve_named_market(pack: &Pack, q_lower: &str) -> MarketMention {
    if let Some((uni, blk)) = market_lookup(pack, q_lower) {
        if let Some((code, _)) = uni.pairs.iter().find(|(_, p)| std::ptr::eq(*p, blk)) {
            return MarketMention::Covered(code.clone());
        }
    }
    // A market word that matched no covered pair is NOT "no market named". The krone and the lira
    // are in the table above precisely so this branch can reach them: the pack has no NOK or TRY
    // pair, `market_lookup` scores nothing, and without this the caller would fall through to the
    // lead market and answer about EUR/USD. Being unable to answer is the truth; saying so is the
    // answer.
    let words: Vec<&str> = q_lower
        .split(|c: char| !c.is_alphanumeric())
        .filter(|w| !w.is_empty())
        .collect();
    for (word, _, display) in CCY_SYNONYMS {
        if words.contains(word) {
            return MarketMention::Uncovered((*display).to_string());
        }
    }
    // A bare ISO code we do not carry ("how is the THB doing"), which no synonym covers.
    for w in &words {
        if w.len() == 3 && w.chars().all(|c| c.is_ascii_alphabetic()) {
            let up = w.to_uppercase();
            let known = pack
                .markets
                .values()
                .any(|u| u.pairs.keys().any(|p| p.to_uppercase().contains(&up)));
            if !known && KNOWN_ISO.contains(&up.as_str()) {
                return MarketMention::Uncovered(up);
            }
        }
    }
    MarketMention::None
}

/// ISO codes that are unmistakably a currency, so a bare one we do not carry can be declined by
/// name rather than answered about with something else.
const KNOWN_ISO: &[&str] = &[
    "THB", "INR", "CNY", "KRW", "ILS", "HUF", "CZK", "RON", "BGN", "UAH", "NGN", "AED", "SAR",
    "MYR", "IDR", "PHP", "VND", "EGP", "PKR", "BDT", "CLP", "COP", "PEN", "ARS", "TWD", "HKD",
    "SGD", "DKK", "ISK", "TRY", "NOK", "SEK",
];

/// Deterministic market lookup over every universe in the pack: pair codes ("usdjpy", "usd/jpy"),
/// bare non-USD legs ("jpy", "btc") and currency words ("yen", "bitcoin"). Best score wins;
/// ties resolve in fx → g10 → em → crypto order. None means "not a market question".
pub fn market_lookup<'a>(
    pack: &'a Pack,
    q_lower: &str,
) -> Option<(&'a MarketUniverse, &'a MarketPair)> {
    let compact: String = q_lower
        .chars()
        .filter(|c| c.is_ascii_alphanumeric())
        .collect();
    let words: Vec<&str> = q_lower
        .split(|c: char| !c.is_alphanumeric())
        .filter(|w| !w.is_empty())
        .collect();
    let mut codes: HashSet<&str> = HashSet::new();
    for (word, code, _) in CCY_SYNONYMS {
        if words.contains(word) {
            codes.insert(code);
        }
    }
    let mut best: Option<(i32, &MarketUniverse, &MarketPair)> = None;
    for uni_name in ["fx", "g10", "em", "crypto"] {
        let Some(uni) = pack.markets.get(uni_name) else {
            continue;
        };
        for (pair, blk) in &uni.pairs {
            let code: String = pair
                .to_lowercase()
                .chars()
                .filter(|c| c.is_ascii_alphanumeric())
                .collect();
            if code.len() != 6 {
                continue;
            }
            let legs = [&code[..3], &code[3..]];
            let mut score = 0;
            if compact.contains(&code) {
                score += 4;
            }
            for leg in legs {
                if codes.contains(leg) {
                    score += 2;
                }
                if leg != "usd" && words.contains(&leg) {
                    score += 2;
                }
            }
            if score > 0 && legs.contains(&"usd") {
                score += 1; // "the yen" means the dollar cross, not EUR/JPY
            }
            if score > 0 && best.as_ref().is_none_or(|(s, _, _)| score > *s) {
                best = Some((score, uni, blk));
            }
        }
    }
    best.map(|(_, u, b)| (u, b))
}

/// Verbatim-from-pack market answer (mirrors the greeting's proven phrasing): every number is a
/// pack value, so the grounding gate passes by construction; the direction lint is off for
/// template content and no fixed word here is a direction word anyway.
/// Is the question actually ASKING for a market's current state, rather than merely mentioning a
/// currency on the way to something else?
fn state_cue_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(
            r"\b(how (is|are|does|do|s)|hows|what (is|are|about)|whats|look|looks|looking|doing|today|right now|currently|current|regime|condition|conditions|state of|situation|siren|read on|tell me about|status)\b",
        )
        .expect("static regex")
    })
}

/// Vocabulary that means the question wants something the radar does not publish (a price level, a
/// correlation, a Sharpe ratio, a future value, a date we have no row for). A market mention inside
/// such a question is context, not the question.
fn out_of_scope_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(
            r"\b(sharpe|correlat\w*|trading|spot|level|levels|printing|outside|multiply|percentage|rank|allocate|split|expect\w*|year.?end|next (month|week|quarter)|tomorrow|estimate|ballpark|approximat\w*|sunday|saturday|forecast\w*)\b",
        )
        .expect("static regex")
    })
}

/// Vocabulary that means the question is not about markets at all — spreadsheet help, tax or
/// legal advice (audit: an excel-formula question in German matched a ledger card by similarity
/// and was "answered"). These get the off-topic refusal, never a card.
fn off_domain_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(
            r"\b(excel|formul\w*|spreadsheet|tableur|fiscal\w*|steuer\w*|imp(?:ô|o)ts?|tax(?:es|ation)?|lawyer|anwalt|avocat|juridique)\b",
        )
        .expect("static regex")
    })
}

/// As [`market_lookup`], but also returns the pair CODE, so the answer board can show that exact
/// market's card instead of re-deriving the market from the question a second time.
///
/// The gate matters more than the lookup. Matching on a currency word alone made this branch
/// hijack every question that happened to name a market — "what is the Sharpe ratio", "give me
/// Sunday's numbers", "is the change risk still 0.87" all came back with today's condition read.
/// Nothing was fabricated, but answering a question nobody asked reads as evasion, and it is worse
/// for trust than an honest "I don't have that".
pub fn market_lookup_pair<'a>(
    pack: &'a Pack,
    q_lower: &str,
) -> Option<(&'a MarketUniverse, &'a MarketPair, String)> {
    if out_of_scope_re().is_match(q_lower) {
        return None;
    }
    let words = q_lower.split_whitespace().count();
    if words > 3 && !state_cue_re().is_match(q_lower) {
        return None; // "btc?" is a state question; a long sentence has to say so
    }
    let (uni, blk) = market_lookup(pack, q_lower)?;
    let code = uni
        .pairs
        .iter()
        .find(|(_, p)| std::ptr::eq(*p, blk))
        .map(|(code, _)| code.clone())?;
    Some((uni, blk, code))
}

pub fn market_answer(uni: &MarketUniverse, pair: &MarketPair) -> String {
    let mut head = format!(
        "As of the {} close, {} on the {} board reads {}",
        uni.data_through, pair.label, uni.label, pair.regime
    );
    if let Some(p) = pair.regime_prob {
        head.push_str(&format!(" with probability {p:.2}"));
    }
    if let Some(d) = pair.days_in_regime {
        head.push_str(&format!(", day {d} of this regime"));
    }
    head.push('.');
    let mut parts = vec![head];
    if let Some(cr) = pair.change_risk_5d {
        let band = match (pair.risk_lo, pair.risk_hi) {
            (Some(lo), Some(hi)) => format!(", band {lo:.2} to {hi:.2}"),
            _ => String::new(),
        };
        let siren = pair
            .anomaly_pct
            .map(|a| format!(", siren {a:.0} of 100"))
            .unwrap_or_default();
        parts.push(format!("Change risk {cr:.2}{band}{siren}."));
    }
    if let Some(a) = pair.agreement {
        parts.push(format!("Stress consensus {a} of 3."));
    }
    parts.join(" ")
}

fn constant_time_eq(a: &str, b: &str) -> bool {
    a.len() == b.len()
        && a.bytes()
            .zip(b.bytes())
            .fold(0u8, |acc, (x, y)| acc | (x ^ y))
            == 0
}

fn sha256_hex(text: &str) -> String {
    hex::encode(Sha256::digest(text.as_bytes()))
}

/// Remember a gated brain answer's hash so /avatar/tts will only ever speak it (last 8 per
/// session, in-memory — restarting the service simply requires re-asking).
/// Sessions tracked for the TTS hash gate. Each entry is tiny, but the map was never evicted —
/// a service running for months accumulated one entry per session forever. Insertion order is
/// preserved by the tracking vector, so eviction drops the oldest sessions first.
const MAX_TTS_SESSIONS: usize = 512;

fn remember_tts_text(st: &AppState, session_id: &str, text: &str) {
    if let Ok(mut map) = st.tts_hashes.lock() {
        let q = map.entry(session_id.to_string()).or_default();
        q.push_back(sha256_hex(text));
        while q.len() > 8 {
            q.pop_front();
        }
        if map.len() > MAX_TTS_SESSIONS {
            if let Ok(mut order) = st.tts_order.lock() {
                if !order.iter().any(|s| s == session_id) {
                    order.push_back(session_id.to_string());
                }
                while map.len() > MAX_TTS_SESSIONS {
                    match order.pop_front() {
                        Some(oldest) if oldest != session_id => {
                            map.remove(&oldest);
                        }
                        Some(_) => {}
                        None => break,
                    }
                }
            }
        } else if let Ok(mut order) = st.tts_order.lock() {
            if !order.iter().any(|s| s == session_id) {
                order.push_back(session_id.to_string());
            }
        }
    }
}

fn tts_text_known(st: &AppState, session_id: &str, text: &str) -> bool {
    let h = sha256_hex(text);
    st.tts_hashes
        .lock()
        .map(|map| map.get(session_id).map(|q| q.contains(&h)).unwrap_or(false))
        .unwrap_or(false)
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
        "{head}\n\nCONTEXT:\n{}\nMARKETS (one line each; every number here is quotable):\n{}\nKNOWLEDGE:\n{knowledge}",
        pack.context_json, pack.markets_compact
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
    /// "llm" | "template" | "refusal" | "decision" (deterministic advice engine)
    pub source: String,
    /// "pass" | "refused:<kind>" | "regenerated" | "blocked" | "open:ungrounded"
    pub gate: String,
    /// Canonical numbers cited in `text` (the widget renders them as receipts).
    pub numbers: Vec<String>,
    pub latency_ms: u64,
    /// Phase 36: the answer board — at most two cards, each already resolved by the pipeline from
    /// published artifacts. Empty is a first-class answer: many questions deserve no picture.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub board: Vec<crate::visuals::CardSpec>,
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

#[derive(Deserialize, ToSchema)]
pub struct TtsRequest {
    #[serde(default)]
    pub session_id: String,
    /// Must be a text the gated brain (or the greeting) actually produced; anything else is 403.
    pub text: String,
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
/// Serve a precomputed answer pack, if one exists for what was asked (phase 41).
///
/// This is the paraphrase cache: a question the classifier never saw, matched to a card by the same
/// confidence rule the board uses, then answered from the pack built last night — speech, board and
/// (when synthesised) audio, with no assembly on the request.
///
/// Two rules keep it honest. A pack is only served when its versions still match current, or with
/// the staleness said out loud; and a question carrying a user-supplied quantity is never mapped
/// onto a pack, because the pack was built before that quantity existed.
fn pack_answer(
    st: &AppState,
    question: &str,
    locale: &str,
    is_followup: bool,
) -> Option<(String, Vec<crate::visuals::CardSpec>, bool)> {
    if question.chars().any(|c| c.is_ascii_digit()) {
        return None; // a stated amount, a stated move: not a precomputable question
    }
    let packs = st.answer_packs()?;
    let loaded = st.visuals()?;
    let (index, _) = (&loaded.0, &loaded.1);
    // Similarity to a DECLARED phrasing, not rank score. Rank alone served a French question about
    // Swiss corporate taxation with a COVID episode pack, because both contain domain vocabulary.
    // See visuals::phrase_similarity for the measurement that ruled rank score out entirely.
    let (matched, sim) = crate::visuals::phrase_similarity(index, question)?;
    if sim < crate::visuals::SPEAK_SIMILARITY || index.catch_alls.iter().any(|c| c == &matched) {
        return None;
    }
    let card = &matched;
    let pair = crate::archive::detect_pair_public(&question.to_lowercase()).unwrap_or_default();
    let pack = packs.find(card, &pair, locale)?;
    let stale = !packs
        .staleness(
            st.avatar_pack()
                .ok()
                .map(|p| p.data_through.clone())
                .unwrap_or_default()
                .as_str(),
            &index.registry_version,
        )
        .is_empty();
    let speech = if is_followup && !pack.speech.followup.is_empty() {
        pack.speech.followup.clone()
    } else {
        pack.speech.standalone.clone()
    };
    if speech.trim().is_empty() {
        return None;
    }
    Some((speech, pack.board.clone(), stale))
}

/// The caption of the best-matching card, when the match is strong enough to speak.
///
/// A higher bar than the board's own threshold: a card can be worth SHOWING beside an answer while
/// being too weak to BE the answer. None keeps the refusal path intact for genuinely off-topic
/// questions, so "tell me a joke" still gets the branded refusal rather than a chart.
fn visual_answer(st: &AppState, question: &str) -> Option<String> {
    let loaded = st.visuals()?;
    let (index, boards) = (&loaded.0, &loaded.1);
    // Two gates were tried here and measured. The strict phrase-similarity gate (0.60) is 100%
    // precise but covers only 17% of traffic — applied HERE it dropped comparative-temporal routing
    // from 59% to 35%, losing far more than it saved. So the caption path keeps rank confidence,
    // and the strict gate lives on the pack cache, where precision is the entire point of the
    // feature. Different jobs, different thresholds, both measured rather than assumed.
    let ranked = crate::visuals::rank(index, question);
    let (top_id, _) = ranked.first()?;
    if !crate::visuals::is_confident(&ranked) || index.catch_alls.iter().any(|c| c == top_id) {
        return None;
    }
    // The market the question named, resolved once by the canonical resolver. Without this the
    // selector matches only literal pair codes and quietly falls back to the lead market.
    let hint = match st.avatar_pack() {
        Ok(pack) => match resolve_named_market(&pack, &question.to_lowercase()) {
            MarketMention::Covered(code) => Some(code),
            // A market we do not publish gets no card at all. Showing a different market's card
            // beside an answer about an unavailable one is how the siren for EUR/USD ended up
            // being offered as the reading for the Turkish lira.
            MarketMention::Uncovered(_) => return None,
            MarketMention::None => None,
        },
        Err(_) => None,
    };
    let cards = crate::visuals::select_board(index, boards, question, None, hint.as_deref());
    let first = cards.first()?;
    if first.caption.trim().is_empty() {
        return None;
    }
    if let Some(h) = hint.as_deref() {
        if names_a_different_market(&first.caption, h) {
            // Better to say nothing than to answer about a market nobody asked about.
            return None;
        }
    }
    Some(first.caption.clone())
}

/// Which board, if any, belongs beside this answer.
///
/// Three rules, in order of importance:
///   1. a DIRECTION question gets exactly one card — the direction-evidence card — and never a
///      price chart. An extended or suggestive line answers "which way" in pixels, which the text
///      lint cannot see; the safest implementation is to not offer the picture at all.
///   2. a blocked or fabricated answer gets NO board: if the words were not safe to say, the
///      picture beside them is not safe to show either.
///   3. otherwise the board is selected from the resolved artifact, and is empty when nothing
///      scores well — most questions deserve no picture.
fn select_board_for(
    st: &AppState,
    question: &str,
    source: &str,
    gate_label: &str,
    forced_card: Option<&str>,
) -> Vec<crate::visuals::CardSpec> {
    // Rule 2, applied to EVERY refusal rather than to two of them. An archive miss was still
    // shipping a card — and, before the hint existed, a card for EUR/USD beside a refusal about the
    // zloty. The direction and advice refusals keep their designated cards (set below); every other
    // refusal gets nothing, because a picture beside "I can't answer that" answers it.
    if gate_label == "blocked"
        || (gate_label.starts_with("refused:")
            && gate_label != "refused:direction"
            && gate_label != "refused:advice")
    {
        return Vec::new();
    }
    let Some(loaded) = st.visuals() else {
        return Vec::new();
    };
    let (index, boards) = (&loaded.0, &loaded.1);
    let forced = if gate_label == "refused:direction" {
        Some("direction_evidence_card")
    } else if gate_label == "refused:advice" {
        Some("ask_your_bank_card")
    } else {
        forced_card
    };
    let hint = match st.avatar_pack() {
        Ok(pack) => match resolve_named_market(&pack, &question.to_lowercase()) {
            MarketMention::Covered(code) => Some(code),
            MarketMention::Uncovered(_) => return Vec::new(),
            MarketMention::None => None,
        },
        Err(_) => None,
    };
    let mut cards = crate::visuals::select_board(index, boards, question, forced, hint.as_deref());
    if forced.is_some() {
        cards.truncate(1); // a refusal is not an invitation to browse
    }
    if let Some(h) = hint.as_deref() {
        let before = cards.len();
        cards.retain(|c| !names_a_different_market(&c.caption, h));
        if cards.len() != before {
            warn!(market = %h, "dropped a card captioned for a different market");
        }
    }
    if !crate::visuals::board_is_grounded(&cards) {
        warn!("board dropped: a card carried no resolved data");
        return Vec::new();
    }
    let _ = source;
    cards
}

fn finish(
    st: &AppState,
    session_id: &str,
    question: &str,
    text: String,
    source: &str,
    gate_label: &str,
    t0: Instant,
) -> Json<BrainResponse> {
    finish_with(st, session_id, question, text, source, gate_label, t0, None)
}

#[allow(clippy::too_many_arguments)]
fn finish_with(
    st: &AppState,
    session_id: &str,
    question: &str,
    text: String,
    source: &str,
    gate_label: &str,
    t0: Instant,
    forced_card: Option<&str>,
) -> Json<BrainResponse> {
    let latency_ms = t0.elapsed().as_millis() as u64;
    m::avatar_request(source);
    m::avatar_brain_latency(t0.elapsed().as_secs_f64());
    let numbers = extract_numbers(&text);
    remember_tts_text(st, session_id, &text);
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
    let board = select_board_for(st, question, source, gate_label, forced_card);
    if board.is_empty() {
        m::visual_null_board();
    } else {
        m::visual_render(&board[0].component);
    }
    // Close the trace. Provenance travels from the board, so the operator's provenance map and the
    // customer's source strip are two renderings of one record rather than two descriptions of it.
    let provenance: Vec<serde_json::Value> =
        board.iter().flat_map(|c| c.provenance.clone()).collect();
    crate::trace::provenance(&provenance);
    // What the receipt needs in order to be regenerable from the trace alone. Without these the
    // operator could see the answer but not reissue the document, which is the half of the promise
    // that actually matters to somebody handling a client dispute.
    let mut v = std::collections::BTreeMap::new();
    if let Ok(pk) = st.avatar_pack() {
        v.insert("context".to_string(), pk.data_through.clone());
        v.insert("chain_head".to_string(), pk.chain_head.clone());
        v.insert("disclosure".to_string(), pk.disclosure.clone());
    }
    // Phase 45: the flag state travels with the turn. Reading a six-week-old trace against
    // today's configuration is how you conclude the wrong thing about a bug that was really a
    // flag being off.
    let f = st.flags.get();
    v.insert("flags".to_string(), f.stamp());
    v.insert("config_hash".to_string(), f.config_hash());
    crate::trace::versions(v);
    if let Some(turn) = crate::trace::finish(
        question,
        &text,
        source,
        gate_label,
        latency_ms,
        board.iter().map(|c| c.component.clone()).collect(),
        numbers.clone(),
    ) {
        st.traces.put(turn);
    }
    Json(BrainResponse {
        text,
        source: source.into(),
        gate: gate_label.into(),
        numbers,
        latency_ms,
        board,
    })
}

/// Advice mode: deterministic decision support from the table — parse → row → template → gates.
/// The LLM never writes advice. Any failure (table absent, no row, lint) returns None and the
/// caller falls back to the standard advice refusal.
fn decision_advice(
    st: &AppState,
    pack: &Pack,
    session_id: &str,
    question: &str,
    question_numbers: &HashSet<String>,
    t0: Instant,
) -> Option<Json<BrainResponse>> {
    let table = match st.decision_table() {
        Ok(t) => t,
        Err(e) => {
            warn!(error = %e, "advice mode is on but the decision table is unavailable");
            return None;
        }
    };
    let default_pair = table.pairs.keys().next()?.clone();
    let q = parse_advice_query(question, &default_pair);
    let already = st
        .advice_disclosed
        .lock()
        .ok()
        .map(|set| set.contains(session_id))
        .unwrap_or(true);
    let (text, computed) = build_advice(&table, &q, !already)?;
    // Grounding: pack ∪ question-echo ∪ builder-computed (grounded by construction — arithmetic
    // over the table and the user's own inputs). The direction lint runs for real.
    let mut allowed = pack.allowed.clone();
    allowed.extend(computed);
    match gate(&text, &allowed, question_numbers, true) {
        Ok(()) => {
            if let Ok(mut set) = st.advice_disclosed.lock() {
                set.insert(session_id.to_string());
            }
            Some(finish(
                st, session_id, question, text, "decision", "pass", t0,
            ))
        }
        Err(reason) => {
            m::avatar_lint_rejection(reason);
            warn!(
                gate = reason,
                "decision advice failed its lint; falling back to the refusal"
            );
            None
        }
    }
}

/// The two archive-miss answers, defined once because both the live handler and the replay must
/// produce the identical text — a refusal that differs between them would show up as a phantom
/// divergence every time someone replayed a historical question.
const ARCHIVE_MISS_SHORT: &str = concat!(
    "That asks about the past, and I could not read it from the archive. ",
    "I hold daily history and monthly counts for the three majors, typical ",
    "regime durations, named episodes, and a comparison against a month ago; ",
    "other markets I carry as today's reading only."
);
const ARCHIVE_MISS_LONG: &str = concat!(
    "I can read today's state, count the markets by regime, look up a date ",
    "for the three majors, quote how long a regime usually lasts, summarise a ",
    "named episode, and compare today against a month ago. That particular ",
    "historical question is outside what I hold — the dashboard's Storms and ",
    "Proof pages go deeper."
);

/// What a replayed turn produced (phase 43).
pub struct ReplayOutcome {
    pub route: String,
    pub text: String,
    pub board: Vec<String>,
}

/// Re-run the DETERMINISTIC part of the routing chain for a recorded question.
///
/// Replay exists so that "it answered the wrong thing yesterday" becomes a case someone can run.
/// It covers the stages where routing bugs actually live — the topic guards, the archive, the
/// market lookup, the FAQ, the packs and board selection — and deliberately stops where the model
/// begins, because a replay that pretended to reproduce a sampled generation would be a green tick
/// with no meaning behind it.
///
/// It mutates nothing: no transcript row, no conversation state, no metrics. An operator
/// investigating this morning's turn must not thereby change this afternoon's.
///
/// The obvious risk is drift — this chain and `brain`'s could disagree after a future edit, and a
/// replay that silently diverges from the real thing is worse than none. `tests/replay_agrees.rs`
/// holds them together by asserting both produce the same route for the same questions.
pub fn replay_deterministic(st: &AppState, question: &str) -> ReplayOutcome {
    // (route, gate label, text, forced card) — the same four values the live handler carries to
    // `finish_with`, so the board can be selected by the same function rather than by a second
    // implementation that will drift.
    struct Step {
        route: &'static str,
        gate_label: &'static str,
        text: String,
        forced_card: Option<String>,
    }
    let step = |route: &'static str, gate_label: &'static str, text: String| Step {
        route,
        gate_label,
        text,
        forced_card: None,
    };

    let Ok(pack) = st.avatar_pack() else {
        return ReplayOutcome {
            route: "unavailable".into(),
            text: String::new(),
            board: Vec::new(),
        };
    };
    let q_lower = question.to_lowercase();
    let question_numbers: HashSet<String> = extract_numbers(question).into_iter().collect();
    let refuse = |kind: &'static str, text: String| step("refusal", kind, text);
    // The gates are part of the answer, not a wrapper around it: a turn blocked for a number
    // outside the pack must replay as blocked, or the one bug most worth reproducing is the one
    // bug replay cannot see.
    let check = |st_: Step| -> Step {
        if st_.route == "refusal" {
            return st_;
        }
        match gate(
            &st_.text,
            &pack.allowed,
            &question_numbers,
            st_.route != "template",
        ) {
            Ok(()) => st_,
            Err(_) => refuse("blocked", pack.refusals.not_in_pack.clone()),
        }
    };

    let historical = crate::archive::looks_historical(&q_lower);
    let framing = crate::guard::detect(&q_lower);
    // Replay parity (audit AE-04): the pure stages the live handler runs — planted figure,
    // uncovered market, courtesy — must run here too, or replaying the exact questions the
    // c368437 fix addressed reports phantom divergences.
    let named_market = resolve_named_market(&pack, &q_lower);
    let named_code = if let MarketMention::Covered(code) = &named_market {
        Some(code.clone())
    } else {
        None
    };
    let decided: Step = if asks_price_direction(&q_lower)
        || framing.is_some_and(|f| f.is_direction())
    {
        refuse("refused:direction", pack.refusals.direction.clone())
    } else if advice_intent_re().is_match(&q_lower) || framing.is_some() {
        refuse("refused:advice", pack.refusals.advice.clone())
    } else if asserts_a_figure(&q_lower)
        && !question_numbers.is_empty()
        && !question_numbers.iter().all(|n| pack.allowed.contains(n))
    {
        refuse("refused:not_in_pack", pack.refusals.not_in_pack.clone())
    } else if let MarketMention::Uncovered(name) = &named_market {
        refuse("refused:not_covered", uncovered_refusal_text(&pack, name))
    } else if let Some(reply) = courtesy_reply(question) {
        step("template", "pass", reply.to_string())
    } else if let Some(found) = st
        .archive()
        .and_then(|a| crate::archive::answer(&a, &q_lower, named_code.as_deref()))
    {
        step("archive", "pass", found.text)
    } else if let Some((uni, blk, pair)) = market_lookup_pair(&pack, &q_lower) {
        check(Step {
            route: "template",
            gate_label: "pass",
            text: market_answer(uni, blk),
            forced_card: Some(format!("condition_card|pair={pair}")),
        })
    } else {
        match faq_best(&pack.faq, question) {
            Some(_) if asserts_a_figure(&q_lower) => {
                refuse("refused:not_in_pack", pack.refusals.not_in_pack.clone())
            }
            Some(_) if historical && mentions_data(&q_lower) => {
                refuse("refused:not_in_archive", ARCHIVE_MISS_SHORT.to_string())
            }
            Some(entry) => check(step("template", "pass", entry.answer.clone())),
            None if historical => refuse("refused:not_in_archive", ARCHIVE_MISS_LONG.to_string()),
            None => {
                if let Some((speech, board, _stale)) = pack_answer(st, question, "en", false) {
                    let route = if board.is_empty() { "visual" } else { "pack" };
                    check(step(route, "pass", speech))
                } else if out_of_scope_re().is_match(&q_lower) {
                    // Mirrors the live chain: out-of-scope vocabulary is never card-hijacked.
                    refuse("refused:not_in_pack", pack.refusals.not_in_pack.clone())
                } else if off_domain_re().is_match(&q_lower) {
                    refuse("refused:off_topic", pack.refusals.off_topic.clone())
                } else if let Some(text) = visual_answer(st, question) {
                    check(step("visual", "pass", text))
                } else {
                    refuse("refused:off_topic", pack.refusals.off_topic.clone())
                }
            }
        }
    };

    // The board is chosen by the same selector the live path uses. Reproducing the words but not
    // the pictures would leave the most visible half of an answer outside the replay.
    let board = select_board_for(
        st,
        question,
        decided.route,
        decided.gate_label,
        decided.forced_card.as_deref(),
    );
    ReplayOutcome {
        route: decided.route.into(),
        text: decided.text,
        board: board.into_iter().map(|c| c.component).collect(),
    }
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
    // Every turn runs inside a recorder, so `trace::stage(...)` works at any depth below here
    // without being threaded through a handler that already routes through fifteen exits. The
    // trace id stays server-side: the customer response carries no operator identifier.
    let session = req.session_id.clone();
    crate::trace::scope(
        crate::trace::new_trace_id(),
        &session,
        brain_inner(st, headers, req),
    )
    .await
}

async fn brain_inner(
    st: AppState,
    headers: HeaderMap,
    req: BrainRequest,
) -> Result<Json<BrainResponse>, ApiError> {
    let t0 = Instant::now();
    brain_auth(&st, &headers)?;
    // --- audit RUST-01: bounded spend per turn --------------------------------------------------
    // The monthly minutes budget caps SESSIONS; nothing capped TURNS. Every turn forwards the
    // whole conversation to the LLM, so an unbounded transcript is an unbounded bill and a client
    // in a loop is a bill with no ceiling. Keyed on the credential, not the client-chosen session.
    const MAX_TURN_CHARS: usize = 4_000;
    const MAX_CONVERSATION_MESSAGES: usize = 32;
    // Keyed on credential + conversation: a deployment-shared brain_token must not throttle
    // every viewer collectively, and one runaway conversation must not spend the whole budget.
    let limiter_key = match headers.get("x-avatar-token").and_then(|v| v.to_str().ok()) {
        Some(tok) => format!("brain:{tok}:{}", req.session_id),
        None => format!("brain:{}", req.session_id),
    };
    if let Err(retry) = st.limiter.check(&limiter_key) {
        return Err(ApiError(
            StatusCode::TOO_MANY_REQUESTS,
            format!("brain turn rate limit reached; retry in {retry}s"),
        ));
    }
    if req.messages.iter().any(|m| m.content.len() > MAX_TURN_CHARS) {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            format!("a message exceeds {MAX_TURN_CHARS} characters"),
        ));
    }
    let mut req = req;
    if req.messages.len() > MAX_CONVERSATION_MESSAGES {
        // Keep the newest turns: the question lives at the tail, and the LLM context stays bounded.
        let start = req.messages.len() - MAX_CONVERSATION_MESSAGES;
        req.messages.drain(..start);
    }
    let pack = load_pack_or_503(&st)?;
    let question = req
        .messages
        .iter()
        .rev()
        .find(|msg| msg.role == "user")
        .map(|msg| msg.content.clone())
        .ok_or_else(|| ApiError(StatusCode::BAD_REQUEST, "no user message in body".into()))?;
    // --- phase 40: resolve references FIRST -------------------------------------------------------
    // "and USDCHF?" is not a question until it has been expanded. Classifying or looking it up
    // before resolution classifies the wrong utterance.
    // The configuration this turn runs under, read once. Stamped into the trace so an old trace
    // can be interpreted under the flags that produced it rather than under today's.
    let flags = st.flags.get();
    // Reference resolution is what conversation state DOES; with state off there is nothing to
    // resolve against, which is exactly the ablation the phase asks for on the multi-turn family.
    let prior = if flags.conversation_state_enabled {
        st.conversations.get(&req.session_id)
    } else {
        None
    };
    let t_resolve = crate::trace::elapsed_ms();
    let resolution = crate::packs::resolve(&question, prior.as_ref());
    crate::trace::stage("reference resolution", t_resolve);
    let (effective, echo, period) = match &resolution {
        crate::packs::Resolution::Verbatim => {
            m::reference_resolution("verbatim");
            (question.clone(), String::new(), None)
        }
        crate::packs::Resolution::Expanded {
            query,
            echo,
            period,
            ..
        } => {
            m::reference_resolution("expanded");
            (query.clone(), echo.clone(), period.clone())
        }
        crate::packs::Resolution::Ambiguous { question: ask } => {
            #[allow(clippy::let_unit_value)]
            // Asking costs one turn. A wrong silent resolution costs the user's trust in every
            // answer that follows it, because they now know the system guesses.
            m::reference_resolution("ambiguous");
            return Ok(finish(
                &st,
                &req.session_id,
                &question,
                ask.clone(),
                "clarify",
                "pass",
                t0,
            ));
        }
    };
    let q_lower = effective.to_lowercase();
    // THE GUARDS SEE WHAT THE USER SAID, not only what resolution made of it.
    //
    // Reference resolution runs first by design — "and USDCHF?" is not a question until it has been
    // expanded. But an utterance that merely CONTAINS a pair name can look elliptical to the
    // resolver, which then rewrites it to the previous intent and throws the rest of the sentence
    // away. "Will EURUSD rise?" became "EUR/USD, same reading" the moment a session had one prior
    // turn: refused correctly on turn one, answered with a condition reading on turn two. The gates
    // on the OUTPUT still held — nothing directional was ever spoken — which is exactly why this
    // survived: no counter moved, and the answer looked helpful.
    //
    // Resolution can only ever REMOVE the words that make a question directional; it can never add
    // them. So the topic guard tests both forms and refuses if either one asks for direction or
    // advice. Refusing a question the user did not quite ask is a small cost; answering a direction
    // question because a rewrite hid it is the failure this project exists not to have.
    let raw_lower = question.to_lowercase();
    // Two layers. The keyword guard catches the plain forms ("will EURUSD rise?"); the framing
    // detector catches the costumes — premise smuggling, persona shift, completion, extrapolation,
    // authority claims. Both run on the raw utterance as well as the resolved one.
    let framing = crate::guard::detect(&raw_lower).or_else(|| crate::guard::detect(&q_lower));
    // Digit substitution defeats a word list, so the keyword guard reads the de-obfuscated form as
    // well. Only the GUARDS see this text; the answer is always produced from what the user wrote.
    let plain = crate::guard::deobfuscate(&raw_lower);
    // The scenario exemption is decided ONCE, on the text the user actually wrote, and then applies
    // to every variant the guards look at. De-obfuscation maps digits to letters, so "a 3% drop"
    // becomes "a e% drop" and the exemption's own evidence disappears — which made the normalised
    // pass refuse the arithmetic question the un-normalised pass had correctly allowed. The rule
    // that falls out of it, and that both this and the exposure exemption now follow: normalisation
    // may reveal an obfuscated word, and may never remove evidence.
    let scenario = conditional_scenario_re().is_match(&raw_lower)
        || conditional_scenario_re().is_match(&q_lower);
    let asks_direction = !scenario
        && (asks_price_direction(&q_lower)
            || asks_price_direction(&raw_lower)
            || asks_price_direction(&plain)
            || framing.is_some_and(|f| f.is_direction()));
    let asks_advice = advice_intent_re().is_match(&q_lower)
        || advice_intent_re().is_match(&raw_lower)
        || advice_intent_re().is_match(&plain)
        || framing.is_some_and(|f| !f.is_direction());
    crate::trace::resolution(
        &question,
        &prior
            .as_ref()
            .map(|p| {
                format!(
                    "{} · {}",
                    p.last_intent.as_deref().unwrap_or("—"),
                    p.last_pair.as_deref().unwrap_or("—")
                )
            })
            .unwrap_or_default(),
        &effective,
        &echo,
    );
    let question_numbers: HashSet<String> = extract_numbers(&question).into_iter().collect();

    // (a) topic guard — direction/advice intent short-circuits to the pack's branded refusal.
    if asks_direction {
        m::avatar_refusal("direction");
        // The framing rule is the more informative label whenever one fired, even if a plain
        // keyword also matched: "persona shift" tells an operator what to tune, "direction
        // keyword" tells them only that something matched.
        let why = framing.map(|f| f.rule()).unwrap_or("direction keyword");
        m::framing_detected(why);
        crate::trace::route("refusal", "topic guard: direction");
        crate::trace::gate("topic_guard", "fail", why);
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
    if asks_advice {
        // The decision engine sizes INSURANCE against an exposure. "Should I buy dollars" is a
        // directional trade request wearing an advice costume: it names no exposure to protect, so
        // answering it with a hedge ratio would dress a market call as risk management. Those go to
        // the escalation card instead.
        if st.avatar.advice
            && (hedging_intent_re().is_match(&q_lower) || hedging_intent_re().is_match(&raw_lower))
        {
            if let Some(resp) = decision_advice(
                &st,
                &pack,
                &req.session_id,
                &question,
                &question_numbers,
                t0,
            ) {
                return Ok(resp);
            }
        }
        m::avatar_refusal("advice");
        let why = framing.map(|f| f.rule()).unwrap_or("advice keyword");
        m::framing_detected(why);
        crate::trace::route("refusal", "topic guard: advice");
        crate::trace::gate("topic_guard", "fail", why);
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

    // (a2) THE ARCHIVE, before anything that reads today's state.
    //
    // An audit of twenty-two ordinary financial questions found eighteen returning `gate pass`
    // while only six answered what was asked: "how many crisis days this year" came back with a
    // picture of today. The grounding gate held throughout — nothing was fabricated — which is
    // precisely why this needed its own fix. A confident non-answer is invisible to every metric
    // that counts gates, and worse for the user than a refusal, because they cannot tell.
    // The archive is consulted for EVERY question, not only historical-looking ones: "which market
    // has the highest siren" is about today and still needs two lookups chained. It returns None
    // unless a shape matches, so the cost of asking is a few string comparisons.
    let historical = crate::archive::looks_historical(&q_lower);
    // Route precedence, explicit rather than emergent. The pre-router OUTRANKS a confident intent
    // on date-bearing questions: a pack is a snapshot of today, so a question naming a date, a
    // count or a comparison asks for something no pack can hold, however confident the match. When
    // both fire it is worth counting — if that climbs, one of them is wrong, and the counter is how
    // anybody would notice.
    // A planted figure is corrected wherever it arrives, not only where the FAQ happens to match.
    //
    // `asserts_a_figure` was checked inside one branch of the fallback chain, so "is the change
    // risk 0.87 today?" sailed past it whenever the FAQ missed and a card could be found — and the
    // user got a confident-sounding answer to a question containing a number we never published.
    // The premise has to be corrected before any path gets the chance to talk around it.
    if asserts_a_figure(&q_lower) && !question_numbers.is_empty() {
        let asserted_is_ours = question_numbers.iter().all(|n| pack.allowed.contains(n));
        if !asserted_is_ours {
            m::avatar_refusal("not_in_pack");
            crate::trace::route("refusal", "planted figure");
            crate::trace::gate("planted_number", "fail", "a figure we never published");
            return Ok(finish(
                &st,
                &req.session_id,
                &question,
                pack.refusals.not_in_pack.clone(),
                "refusal",
                "refused:not_in_pack",
                t0,
            ));
        }
    }

    // A market we do not publish is named as such, before ANY path can answer with a different one.
    //
    // This sits above the archive, the packs and the board because every one of those will happily
    // produce a confident answer about the lead market instead. "How unusual is the Turkish lira
    // today?" returned "Siren for EUR/USD: 79 of 100" — a real number, correctly computed, about a
    // market the user did not mention. There is no version of that which is better than saying we
    // do not cover it.
    // Resolved once per turn and reused: every path that can answer needs to agree about which
    // market the question is about, and re-deriving it per path is how they came to disagree.
    let named_market = resolve_named_market(&pack, &q_lower);
    if let MarketMention::Uncovered(name) = &named_market {
        m::avatar_refusal("market_not_covered");
        crate::trace::route("refusal", "market not covered");
        let text = uncovered_refusal_text(&pack, name);
        return Ok(finish(
            &st,
            &req.session_id,
            &question,
            text,
            "refusal",
            "refused:not_covered",
            t0,
        ));
    }

    // Courtesy, before anything that reads data: "thanks" needs no lookup and deserves no refusal.
    if let Some(reply) = courtesy_reply(&question) {
        crate::trace::route("courtesy", "small talk");
        return Ok(finish(
            &st,
            &req.session_id,
            &question,
            reply.to_string(),
            "template",
            "pass",
            t0,
        ));
    }

    let t_route = crate::trace::elapsed_ms();
    let pre_router = crate::slip::pre_router_wants_archive(&q_lower);
    if pre_router {
        if let Some(loaded) = st.visuals() {
            if let Some((matched, sim)) = crate::visuals::phrase_similarity(&loaded.0, &effective) {
                if sim >= crate::visuals::SPEAK_SIMILARITY && !matched.is_empty() {
                    m::router_precedence_conflict();
                    crate::trace::precedence_conflict();
                }
            }
        }
    }
    // The kill switch. `agent_enabled=false` returns the system to phase-41 behaviour — packs,
    // paraphrase cache and the FAQ, with no rooms — on the very next turn, including for sessions
    // already in progress. No redeploy, no dropped WebRTC session.
    let rooms_open = flags.agent_enabled && flags.lane_archive;
    if let Some(archive) = st.archive().filter(|_| rooms_open) {
        let named_code = if let MarketMention::Covered(code) = &named_market {
            Some(code.as_str())
        } else {
            None
        };
        if let Some(found) = crate::archive::answer(&archive, &q_lower, named_code) {
            crate::trace::stage("archive lookup", t_route);
            crate::trace::route(
                "archive",
                if pre_router {
                    "pre-router pattern"
                } else {
                    "archive shape match"
                },
            );
            m::archive_answer(found.shape);
            m::router_lane(
                crate::slip::Lane::Archive.as_str(),
                if pre_router {
                    "pre_router"
                } else {
                    "shape_match"
                },
            );
            if found.shape.ends_with("_zero") {
                m::empty_result("genuinely_zero");
            } else if found.shape.ends_with("_empty") || found.shape.ends_with("_missing") {
                m::empty_result("no_data_yet");
            }
            return Ok(finish(
                &st,
                &req.session_id,
                &question,
                found.text,
                "archive",
                "pass",
                t0,
            ));
        }
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
    let mut forced_card: Option<String> = None;
    let mut pack_board: Vec<crate::visuals::CardSpec> = Vec::new();
    let mut pack_stale = false;
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
            None => match market_lookup_pair(&pack, &q_lower) {
                Some((uni, blk, pair)) => {
                    candidate = market_answer(uni, blk);
                    source = "template";
                    forced_card = Some(format!("condition_card|pair={pair}"));
                }
                None => match faq_best(&pack.faq, &effective) {
                    // A definition is not an answer to "what was the change risk a month ago". If
                    // the question is about the PAST and names data, and the archive could not
                    // serve it, the FAQ must not paper over the gap with a glossary entry.
                    // "Change risk 0.62 — what's that as a percentage?" asserts a number we never
                    // published. Answering with the definition of change risk neither corrects the
                    // premise nor answers the question; it just sounds responsive.
                    Some(_) if asserts_a_figure(&q_lower) => {
                        m::avatar_refusal("not_in_pack");
                        return Ok(finish(
                            &st,
                            &req.session_id,
                            &question,
                            pack.refusals.not_in_pack.clone(),
                            "refusal",
                            "refused:not_in_pack",
                            t0,
                        ));
                    }
                    Some(_) if historical && mentions_data(&q_lower) => {
                        m::avatar_refusal("archive_miss");
                        let text = ARCHIVE_MISS_SHORT.to_string();
                        return Ok(finish(
                            &st,
                            &req.session_id,
                            &question,
                            text,
                            "refusal",
                            "refused:not_in_archive",
                            t0,
                        ));
                    }
                    Some(entry) => {
                        candidate = entry.answer.clone();
                        source = "template";
                    }
                    // The board rescues the answer. A resolved card's caption is a sentence the
                    // PIPELINE wrote from published numbers, so it is grounded by construction and
                    // faces the same gates as any other answer. Refusing a question we can clearly
                    // illustrate was never the honest outcome — it was just the easy one.
                    // A card about today is the wrong answer to a question about the past. Saying
                    // so costs a turn; answering it costs the user's ability to trust any answer.
                    None if historical => {
                        m::avatar_refusal("archive_miss");
                        let text = ARCHIVE_MISS_LONG.to_string();
                        return Ok(finish(
                            &st,
                            &req.session_id,
                            &question,
                            text,
                            "refusal",
                            "refused:not_in_archive",
                            t0,
                        ));
                    }
                    None => match (if flags.packs_enabled {
                        pack_answer(&st, &effective, "en", !echo.is_empty())
                    } else {
                        None
                    })
                    // The pack path runs BEFORE the visual path and was answering with a
                    // precomputed EUR/USD line to questions about the aussie. A precomputed answer
                    // is still an answer, and it has to be about the market that was asked about.
                    .filter(|(speech, _, _)| match &named_market {
                        MarketMention::Covered(code) => !names_a_different_market(speech, code),
                        _ => true,
                    })
                    .map(|(speech, board, stale)| {
                        pack_board = board;
                        pack_stale = stale;
                        speech
                    })
                    .or_else(|| {
                        // A question already wearing out-of-scope vocabulary must not be hijacked
                        // by a similarity card ("ballpark ... volatility tomorrow" was answered
                        // with a 1y realised-vol caption). The refusal branch below owns it.
                        if out_of_scope_re().is_match(&q_lower)
                            || off_domain_re().is_match(&q_lower)
                        {
                            None
                        } else {
                            visual_answer(&st, &effective)
                        }
                    })
                    {
                        Some(text) => {
                            candidate = text;
                            source = if pack_board.is_empty() {
                                "visual"
                            } else {
                                "pack"
                            };
                        }
                        None => {
                            let asked_for_a_number = out_of_scope_re().is_match(&q_lower);
                            m::avatar_refusal(if asked_for_a_number {
                                "not_in_pack"
                            } else {
                                "off_topic"
                            });
                            let text = if asked_for_a_number {
                                // "I don't have that number and won't guess" is the truthful answer
                                // to a request for a metric this system does not publish.
                                pack.refusals.not_in_pack.clone()
                            } else {
                                pack.refusals.off_topic.clone()
                            };
                            return Ok(finish(
                                &st,
                                &req.session_id,
                                &question,
                                text,
                                "refusal",
                                if asked_for_a_number {
                                    "refused:not_in_pack"
                                } else {
                                    "refused:off_topic"
                                },
                                t0,
                            ));
                        }
                    },
                },
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
            Ok(()) => {
                crate::trace::gate(
                    "direction lint + numeric grounding",
                    if regenerated { "regenerated" } else { "pass" },
                    "",
                );
                break if regenerated { "regenerated" } else { "pass" };
            }
            Err(reason) => {
                crate::trace::gate("direction lint + numeric grounding", "fail", reason);
                m::avatar_lint_rejection(reason);
                if reason == "grounding" && st.avatar.open {
                    // Open mode: general-knowledge numbers may flow — annotate, never block.
                    // Direction failures never take this branch (constitutional, still block).
                    break "open:ungrounded";
                }
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
                crate::trace::route("refusal", "gate blocked the candidate");
                candidate = pack.refusals.not_in_pack.clone();
                source = "refusal";
                break "blocked";
            }
        }
    };
    // A pack built under superseded rules may still be the best answer available at 09:00 when the
    // 06:00 build failed — but the user is told, in the answer, not in a header they cannot see.
    if pack_stale && gate_label == "pass" {
        candidate = format!("{candidate} (built before today's run — figures may have moved.)");
        m::answer_pack_stale();
    }
    if !pack_board.is_empty() {
        m::answer_path("pack");
    }

    // Echo the resolution in the answer, so a mis-resolution is caught in the same breath.
    //
    // With one exception that matters more than the feature: if the follow-up asked for a DIFFERENT
    // PERIOD and every answering path we have reads today's published state, the echo would claim a
    // reading we did not perform. Say what actually happened instead. The archive that would honour
    // it is phase 42's job, and pretending otherwise here would be the most convincing kind of
    // wrong answer — right shape, right market, wrong century.
    if gate_label == "pass" {
        if let Some(when) = period.as_deref() {
            candidate = format!(
                "That's today's reading — I can't read back to {when} yet. {}",
                candidate.trim_start()
            );
        } else if !echo.is_empty() {
            candidate = format!("{echo} {}", candidate.trim_start());
        }
    }
    let response = finish_with(
        &st,
        &req.session_id,
        &question,
        candidate,
        source,
        gate_label,
        t0,
        forced_card.as_deref(),
    );
    remember_turn(&st, &req.session_id, &effective, &response, prior);
    Ok(response)
}

/// Carry forward only what an elliptical follow-up needs: the subject, the market, the board.
/// Storing the utterance itself would make this a transcript store with a TTL, which is a different
/// thing with different obligations.
fn remember_turn(
    st: &AppState,
    session_id: &str,
    effective: &str,
    response: &Json<BrainResponse>,
    prior: Option<crate::packs::SessionState>,
) {
    let mut state = prior.unwrap_or_default();
    state.turn_index = state.turn_index.saturating_add(1);
    if let Some(card) = response.0.board.first() {
        state.last_card = Some(card.component.clone());
        state.last_intent = Some(format!("ask_{}", card.component));
        if let Some(pair) = card.args.get("pair").and_then(|v| v.as_str()) {
            state.last_pair = Some(pair.to_string());
        }
    }
    if state.last_pair.is_none() {
        let up = effective.to_uppercase();
        for code in ["EURUSD", "USDCHF", "GBPUSD", "USDJPY", "USDRUB", "BTC-USD"] {
            if up.contains(code) {
                state.last_pair = Some(code.to_string());
                break;
            }
        }
    }
    state.last_board_cards = response
        .0
        .board
        .iter()
        .map(|c| c.component.clone())
        .collect();
    st.conversations.put(session_id, state);
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
        "open": st.avatar.open,
        "advice": st.avatar.advice,
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
    // DEV ONLY: FXRADAR_AVATAR_DEV=1 skips the key entirely (the widget never holds one; the
    // bind is a laptop loopback). Still cost-capped and counted. Production keeps the key gate.
    if !st.avatar.dev {
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
    let mut out = match vendor.as_str() {
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
            // Anam BYO-LLM session-token flow, VERIFIED LIVE 2026-08-20 against api.anam.ai:
            // llmId = CUSTOMER_CLIENT_V1 disables Anam's own brain, so the persona speaks ONLY
            // what our gated /avatar/brain produces via the SDK's talk() — the whole point.
            // avatar/voice are the vendor's licensed stock persona (Cara) unless overridden.
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
                    "name": "Radar presenter",
                    "avatarId": st.avatar.anam_avatar_id,
                    "avatarModel": st.avatar.anam_avatar_model,
                    "voiceId": st.avatar.anam_voice_id,
                    "llmId": "CUSTOMER_CLIENT_V1"}}))
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
            // the widget needs TWO tokens: the vendor's (WebRTC face) and OURS (brain + tts) —
            // the vendor token means nothing to /avatar/brain, which caused a 401 without this.
            let brain_token = st
                .store
                .create_avatar_session(&session_id, SESSION_TTL_SECS)?;
            json!({"vendor": "anam", "token": token, "brain_token": brain_token,
                   "session_id": session_id, "disclaimer": DISCLAIMER})
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
            let brain_token = st
                .store
                .create_avatar_session(&session_id, SESSION_TTL_SECS)?;
            json!({"vendor": "heygen", "token": token, "brain_token": brain_token,
                   "session_id": session_id, "disclaimer": DISCLAIMER})
        }
    };
    if let Some(obj) = out.as_object_mut() {
        obj.insert("open".into(), json!(st.avatar.open));
        obj.insert("advice".into(), json!(st.avatar.advice));
        obj.insert(
            "tts".into(),
            json!(if st.avatar.elevenlabs_key.is_some() {
                "elevenlabs"
            } else {
                "browser"
            }),
        );
    }
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

#[derive(Deserialize, ToSchema)]
pub struct UiEventRequest {
    #[serde(default)]
    pub session_id: String,
    /// A name from a fixed list. Free text is rejected rather than recorded: a metric label the
    /// client can choose is an unbounded cardinality bug and a place for user content to leak into
    /// a monitoring system that was never designed to hold any.
    pub event: String,
    /// Milliseconds, for the wait-line duration only. Ignored elsewhere.
    #[serde(default)]
    pub ms: Option<f64>,
}

/// Counters for our own interface (phase 43, requirement G).
///
/// We measure the models constantly and the UI not at all, which is how a detail sheet nobody opens
/// survives for two years. These counters exist so that decision can be made from evidence — and so
/// that "delete it" stays a real option.
pub async fn ui_event(
    State(st): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<UiEventRequest>,
) -> Result<Json<Value>, ApiError> {
    brain_auth(&st, &headers)?;
    match req.event.as_str() {
        "wait_line_shown" => {
            m::wait_line_shown();
            if let Some(ms) = req
                .ms
                .filter(|v| v.is_finite() && *v >= 0.0 && *v < 120_000.0)
            {
                m::wait_line_duration(ms);
            }
        }
        "source_chip_click" => m::source_chip_click(),
        "source_detail_open" => m::source_detail_open(),
        "resolution_corrected" => m::resolution_corrected(),
        _ => {
            return Err(ApiError(
                StatusCode::BAD_REQUEST,
                "unknown event name".into(),
            ))
        }
    }
    Ok(Json(json!({"ok": true})))
}

#[derive(Deserialize, ToSchema)]
pub struct ReceiptRequest {
    #[serde(default)]
    pub session_id: String,
    pub question: String,
    /// Must be an answer the gated brain actually produced in this session.
    pub answer: String,
    #[serde(default)]
    pub provenance: Vec<Value>,
}

/// A printable receipt for an answer the user is looking at.
///
/// Gated like `/avatar/tts`, and for the same reason: a document headed "Answer receipt" carrying
/// this system's disclosures is a claim about what this system said. If arbitrary text could be
/// posted here, the receipt would certify whatever the poster wanted it to, which is the opposite
/// of what it exists to do.
pub async fn receipt(
    State(st): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<ReceiptRequest>,
) -> Result<Response, ApiError> {
    brain_auth(&st, &headers)?;
    if !tts_text_known(&st, &req.session_id, &req.answer) {
        return Err(ApiError(
            StatusCode::FORBIDDEN,
            "a receipt may only be issued for an answer this service produced".into(),
        ));
    }
    let pack = load_pack_or_503(&st)?;
    // The identifier is derived from the ANSWER, never from the session: the same answer yields the
    // same receipt id for everyone, and no receipt can be traced back to a person by its filename.
    let answer_id = crate::receipt::answer_id(&req.answer);
    m::receipt_export();
    let payload = crate::receipt::ReceiptPayload {
        answer_id,
        question: req.question,
        answer: req.answer,
        provenance: req.provenance,
        data_through: pack.data_through.clone(),
        chain_head: pack.chain_head.clone(),
        disclosure: pack.disclosure.clone(),
    };
    Ok((
        [(axum::http::header::CONTENT_TYPE, "text/html; charset=utf-8")],
        crate::receipt::render(&payload),
    )
        .into_response())
}

/// Realistic voice for a gated answer (ElevenLabs Flash). Order matters: token auth → answer
/// hash check (403 for any text our gates did not produce — TTS can never be used to voice
/// arbitrary text) → monthly character cap (429) → vendor key (404 → the widget falls back to
/// browser TTS) → the vendor call. Vendor schema UNVERIFIED without a live ELEVENLABS_API_KEY.
#[utoipa::path(post, path = "/avatar/tts", tag = "avatar",
    request_body = TtsRequest,
    responses((status = 200, description = "audio/mpeg bytes", body = String),
              (status = 401, description = "missing/unknown X-Avatar-Token", body = ApiErrorBody),
              (status = 403, description = "text was not produced by the gated brain", body = ApiErrorBody),
              (status = 404, description = "no TTS key configured — use browser TTS", body = Object),
              (status = 429, description = "monthly avatar budget reached", body = ApiErrorBody),
              (status = 503, description = "avatar disabled", body = Object)))]
pub async fn tts(
    State(st): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<TtsRequest>,
) -> Result<Response, ApiError> {
    brain_auth(&st, &headers)?;
    if req.text.is_empty() {
        return Err(ApiError(StatusCode::BAD_REQUEST, "text is empty".into()));
    }
    // Only speak what OUR gates produced: an answer remembered for this session, or the exact
    // current pack greeting (the greeting is spoken before any session exists).
    let is_greeting = st
        .avatar_pack()
        .map(|p| p.greeting == req.text)
        .unwrap_or(false);
    if !tts_text_known(&st, &req.session_id, &req.text) && !is_greeting {
        return Err(ApiError(
            StatusCode::FORBIDDEN,
            "tts only speaks gated answers".into(),
        ));
    }
    let month = current_month();
    let n_chars = req.text.chars().count() as i64;
    if st.store.avatar_chars(&month)? + n_chars > st.avatar.max_tts_chars_month {
        return Err(ApiError(
            StatusCode::TOO_MANY_REQUESTS,
            "monthly avatar budget reached".into(),
        ));
    }
    let Some(key) = st.avatar.elevenlabs_key.as_deref() else {
        return Ok((StatusCode::NOT_FOUND, Json(json!({"tts": "browser"}))).into_response());
    };
    st.store.add_avatar_chars(&month, n_chars)?;
    m::avatar_tts_chars(n_chars as u64);
    let url = format!(
        "https://api.elevenlabs.io/v1/text-to-speech/{}?output_format=mp3_44100_64",
        st.avatar.voice_id
    );
    let resp = http_client()
        .post(&url)
        .header("xi-api-key", key)
        .timeout(Duration::from_secs(20))
        .json(&json!({"text": req.text, "model_id": "eleven_flash_v2_5"}))
        .send()
        .await
        .map_err(|e| ApiError(StatusCode::BAD_GATEWAY, format!("elevenlabs: {e}")))?;
    let status = resp.status();
    if !status.is_success() {
        return Err(ApiError(
            StatusCode::BAD_GATEWAY,
            format!("elevenlabs {status}"),
        ));
    }
    let bytes = resp
        .bytes()
        .await
        .map_err(|e| ApiError(StatusCode::BAD_GATEWAY, format!("elevenlabs: {e}")))?;
    Ok(([(header::CONTENT_TYPE, "audio/mpeg")], bytes).into_response())
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
        // The blunt forecast asks are owned by `guard::plain_forecast_ask`, NOT by this keyword
        // list — deliberately, because the bare noun is ambiguous here: "how many sealed forecasts
        // so far?" is a question about the ledger and must be answered.
        for q in [
            "what is your prediction for the franc",
            "hi what would be your prediction of the market of the franc",
            "forecast for the euro",
            "outlook for sterling",
        ] {
            assert!(
                crate::guard::detect(q).is_some_and(|f| f.is_direction()),
                "the guard missed {q:?}"
            );
        }
        for q in [
            "how many sealed forecasts so far?",
            "what is your forecast accuracy",
            "how do you forecast regime change",
        ] {
            assert!(
                !asks_price_direction(q) && crate::guard::detect(q).is_none(),
                "{q:?} is about the record or the method and must not be refused"
            );
        }
        assert!(direction_intent_re().is_match("will eurusd rise?"));
        assert!(direction_intent_re().is_match("which way is the franc going"));
        assert!(!direction_intent_re().is_match("what is the current regime?"));
        assert!(advice_intent_re().is_match("should i buy dollars?"));
        assert!(advice_intent_re().is_match("should i hedge my exposure"));
        // regression: a trust question must not be answered with hedging advice
        assert!(!advice_intent_re().is_match("why should i trust you"));
        assert!(!advice_intent_re().is_match("should i believe your record"));
        assert!(!advice_intent_re().is_match("why should i care about the siren"));
        assert!(advice_intent_re().is_match("help with position sizing"));
        assert!(advice_intent_re().is_match("where do i put my stop-loss"));
        assert!(!advice_intent_re().is_match("what is the siren?"));
    }

    #[test]
    fn market_lookup_gate_rejects_questions_that_only_mention_a_market() {
        // asking about the market
        assert!(state_cue_re().is_match("how is the yen today"));
        assert!(state_cue_re().is_match("what about the euro"));
        // merely naming one on the way to something we do not publish
        assert!(out_of_scope_re().is_match("what is the sharpe ratio on the usd/chf overlay"));
        assert!(out_of_scope_re().is_match("where is eur/usd trading at right now"));
        assert!(out_of_scope_re().is_match("give me sunday's numbers for eur/usd"));
        assert!(out_of_scope_re().is_match("how correlated is eur/usd to gold"));
        assert!(!out_of_scope_re().is_match("how is bitcoin today"));
    }

    #[test]
    fn market_lookup_codes_and_synonyms() {
        let mk = |label: &str, regime: &str| MarketPair {
            label: label.into(),
            regime: regime.into(),
            regime_prob: Some(0.9),
            days_in_regime: Some(3),
            change_risk_5d: Some(0.2),
            risk_lo: Some(0.1),
            risk_hi: Some(0.5),
            anomaly_pct: Some(40.0),
            agreement: Some(1),
        };
        let mut markets = BTreeMap::new();
        markets.insert(
            "fx".to_string(),
            MarketUniverse {
                label: "FX majors".into(),
                data_through: "2026-08-18".into(),
                pairs: BTreeMap::from([("EURUSD".to_string(), mk("EUR/USD", "calm"))]),
            },
        );
        markets.insert(
            "g10".to_string(),
            MarketUniverse {
                label: "FX G10".into(),
                data_through: "2026-08-18".into(),
                pairs: BTreeMap::from([("USDJPY".to_string(), mk("USD/JPY", "trend"))]),
            },
        );
        markets.insert(
            "crypto".to_string(),
            MarketUniverse {
                label: "Crypto majors".into(),
                data_through: "2026-08-17".into(),
                pairs: BTreeMap::from([("BTC-USD".to_string(), mk("BTC/USD", "chop"))]),
            },
        );
        let pack = Pack {
            data_through: "2026-08-18".into(),
            disclosure: String::new(),
            greeting: String::new(),
            refusals: Refusals::default(),
            faq: vec![],
            allowed: HashSet::new(),
            knowledge_rel: String::new(),
            context_json: String::new(),
            chain_head: String::new(),
            markets_compact: compact_markets(&markets),
            markets,
        };
        // currency word, bare leg, compact code, and slash form all resolve
        assert_eq!(
            market_lookup(&pack, "how is the yen today?")
                .unwrap()
                .1
                .label,
            "USD/JPY"
        );
        assert_eq!(
            market_lookup(&pack, "tell me about btc").unwrap().1.label,
            "BTC/USD"
        );
        assert_eq!(
            market_lookup(&pack, "usd/jpy please").unwrap().1.label,
            "USD/JPY"
        );
        assert_eq!(
            market_lookup(&pack, "bitcoin situation?").unwrap().1.label,
            "BTC/USD"
        );
        assert_eq!(
            market_lookup(&pack, "how is the euro?").unwrap().1.label,
            "EUR/USD"
        );
        // no market words → None (the FAQ handles it)
        assert!(market_lookup(&pack, "what is the siren?").is_none());
        // the answer carries the pack's numbers and the universe board
        let (uni, blk) = market_lookup(&pack, "yen?").unwrap();
        let text = market_answer(uni, blk);
        assert!(text.contains("USD/JPY") && text.contains("trend") && text.contains("0.20"));
        assert!(text.contains("FX G10") && text.contains("40 of 100"));
    }

    #[test]
    fn advice_query_parsing() {
        let q = parse_advice_query(
            "hedge my 1.5m dollars over 2 months, i am risk tolerant",
            "EURUSD",
        );
        assert_eq!(
            q.pair, "EURUSD",
            "dollars alone fall back to the default pair"
        );
        assert_eq!(q.amount, Some(1_500_000.0));
        assert_eq!(q.currency.as_deref(), Some("USD"));
        assert_eq!(q.horizon_weeks, 8, "2 months = 8 weeks");
        assert_eq!(q.tolerance, "aggressive");
        let q = parse_advice_query("800'000 francs for 3 weeks, cautious please", "EURUSD");
        assert_eq!(q.pair, "USDCHF");
        assert_eq!(q.amount, Some(800_000.0));
        assert_eq!(q.currency.as_deref(), Some("CHF"));
        assert_eq!(
            q.horizon_weeks, 2,
            "3 clamps to the nearer, shorter horizon"
        );
        assert_eq!(q.tolerance, "conservative");
        let q = parse_advice_query("should i hedge 250k pounds", "EURUSD");
        assert_eq!(q.pair, "GBPUSD");
        assert_eq!(q.amount, Some(250_000.0));
        assert_eq!(q.currency.as_deref(), Some("GBP"));
        assert_eq!(q.horizon_weeks, 4, "default horizon");
        assert_eq!(q.tolerance, "balanced");
        let q = parse_advice_query("protect my exposure for 1 month", "EURUSD");
        assert_eq!((q.amount, q.currency), (None, None));
        assert_eq!(q.horizon_weeks, 4);
        let q = parse_advice_query("hedge 2m euros over 12 weeks", "GBPUSD");
        assert_eq!(q.pair, "EURUSD");
        assert_eq!(q.amount, Some(2_000_000.0));
        assert_eq!(q.horizon_weeks, 12);
    }

    #[test]
    fn default_prompt_per_mode() {
        assert!(default_system_prompt(false).ends_with("avatar_system_v1.txt"));
        assert!(default_system_prompt(true).ends_with("avatar_system_v2.txt"));
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
