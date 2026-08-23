//! The operator trace: everything about how one turn was produced (phase 43).
//!
//! This module is the deliberate opposite of the customer surface. The widget shows almost nothing
//! about process and everything about where the numbers came from; this shows all of it — every
//! stage with its timing, the route and why, the slips submitted, each gate's verdict, the prompt
//! economics. Conflating the two is the failure this phase exists to prevent: an engineer reads a
//! step log as evidence of care, a customer reads it as evidence that something is slow and broken.
//!
//! Three properties are load-bearing:
//!
//! **Recording must not be plumbing.** A turn passes through a dozen decision points and ends at one
//! of fifteen `finish()` call sites. Threading a mutable builder through all of them would make
//! every future change to the handler a change to the trace layer too, and the trace layer would
//! rot within two phases. Instead the recorder is a task-local: `trace::stage(...)` works anywhere
//! inside the request and is a no-op outside one, so a turn that forgets to record simply has a
//! thinner trace rather than a compile error or a panic.
//!
//! **Traces hold no personal data.** The session id is hashed before storage, the question is kept
//! (promote-to-golden needs the exact words a user typed, and that is the whole point of the
//! feature) and nothing else of the user's free text is retained. Traces live in memory with a
//! retention window and never reach disk, so the retention window is the whole of the deletion
//! story rather than a promise about a cleanup job.
//!
//! **A trace that cannot be replayed is a bug report without a repro.** Every record carries the
//! pinned versions and the resolved question, which is exactly the input `eval/harness.py` needs to
//! re-run the turn against the frozen snapshot.

use serde::{Deserialize, Serialize};
use std::cell::RefCell;
use std::collections::{BTreeMap, VecDeque};
use std::sync::{Arc, Mutex};
use std::time::Instant;

/// How long a trace stays available to an operator, and how many are kept at once. Both are small
/// on purpose: traces are a debugging tool for something that just happened, not an archive.
#[derive(Clone, Debug)]
pub struct TraceCfg {
    pub retention_secs: i64,
    pub capacity: usize,
    /// FXRADAR_OPS_KEY. Unset → every `/ops/*` route is 401 for everyone, which is the correct
    /// default for a surface whose whole content is internal.
    pub operator_key: Option<String>,
}

impl Default for TraceCfg {
    fn default() -> Self {
        TraceCfg {
            retention_secs: 3 * 3600,
            capacity: 500,
            operator_key: None,
        }
    }
}

// ---------------------------------------------------------------------------------------------
// the record
// ---------------------------------------------------------------------------------------------

/// One stage of the turn, as a span rather than a duration, so the timeline can show overlap —
/// concurrent slips are the case where a list of durations would mislead.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Stage {
    pub name: String,
    pub start_ms: f64,
    pub end_ms: f64,
}

impl Stage {
    pub fn duration_ms(&self) -> f64 {
        (self.end_ms - self.start_ms).max(0.0)
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Candidate {
    pub id: String,
    pub score: f64,
    pub shown: bool,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Router {
    /// pack | paraphrase | archive | market | faq | visual | refusal | live | clarify
    pub path: String,
    /// Which stage actually decided — the answer to "why this path" that a path label alone hides.
    pub deciding_stage: String,
    /// The pre-router and a confident classifier disagreed; precedence resolved it.
    pub precedence_conflict: bool,
    pub candidates: Vec<Candidate>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Resolution {
    pub raw: String,
    pub state_applied: String,
    pub resolved: String,
    /// What the user was actually told we understood — the line that lets them catch a
    /// mis-resolution in one turn instead of five.
    pub echo: String,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Gate {
    pub name: String,
    /// pass | fail | regenerated | skipped
    pub outcome: String,
    pub reason: String,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Economics {
    pub prefix_hash: String,
    /// hit | miss | n/a (no model call was made — the pack and archive paths)
    pub cache: String,
    pub input_tokens: u64,
    pub cached_tokens: u64,
    pub output_tokens: u64,
    pub cost_chf: f64,
}

/// Everything known about one turn.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Turn {
    pub trace_id: String,
    pub started_unix: i64,
    /// sha256(session_id) truncated — enough to group a session's turns, never enough to identify
    /// the session to anyone who does not already hold its id.
    pub session_hash: String,
    pub locale: String,
    pub question: String,
    pub answer: String,
    pub source: String,
    pub gate: String,
    pub latency_ms: u64,
    pub deadline_ms: u64,
    pub resolution: Resolution,
    pub router: Router,
    pub stages: Vec<Stage>,
    pub slips: Vec<serde_json::Value>,
    pub gates: Vec<Gate>,
    pub provenance: Vec<serde_json::Value>,
    pub economics: Economics,
    pub board: Vec<String>,
    pub numbers: Vec<String>,
    pub versions: BTreeMap<String, String>,
}

// ---------------------------------------------------------------------------------------------
// the task-local recorder
// ---------------------------------------------------------------------------------------------

struct Recorder {
    turn: Turn,
    t0: Instant,
}

tokio::task_local! {
    static REC: RefCell<Recorder>;
}

/// Run `fut` with a recorder attached. Every `trace::*` call inside it records; outside, they are
/// no-ops, so tests and non-brain callers need no scaffolding.
pub async fn scope<F, T>(trace_id: String, session_id: &str, fut: F) -> T
where
    F: std::future::Future<Output = T>,
{
    let turn = Turn {
        trace_id,
        started_unix: now_unix(),
        session_hash: short_hash(session_id),
        ..Default::default()
    };
    REC.scope(
        RefCell::new(Recorder {
            turn,
            t0: Instant::now(),
        }),
        fut,
    )
    .await
}

fn with<R>(f: impl FnOnce(&mut Recorder) -> R) -> Option<R> {
    REC.try_with(|cell| f(&mut cell.borrow_mut())).ok()
}

/// Elapsed milliseconds since the turn began — the timeline's coordinate system.
pub fn elapsed_ms() -> f64 {
    with(|r| r.t0.elapsed().as_secs_f64() * 1000.0).unwrap_or(0.0)
}

/// Record a stage that ran from `start_ms` (a prior `elapsed_ms()`) until now.
pub fn stage(name: &str, start_ms: f64) {
    let end = elapsed_ms();
    with(|r| {
        r.turn.stages.push(Stage {
            name: name.into(),
            start_ms,
            end_ms: end,
        })
    });
}

/// Record a stage whose span is already known (a slip that ran concurrently, say).
pub fn span(name: &str, start_ms: f64, end_ms: f64) {
    with(|r| {
        r.turn.stages.push(Stage {
            name: name.into(),
            start_ms,
            end_ms,
        })
    });
}

pub fn route(path: &str, deciding_stage: &str) {
    with(|r| {
        r.turn.router.path = path.into();
        r.turn.router.deciding_stage = deciding_stage.into();
    });
}

pub fn precedence_conflict() {
    with(|r| r.turn.router.precedence_conflict = true);
}

pub fn candidates(items: Vec<Candidate>) {
    with(|r| r.turn.router.candidates = items);
}

pub fn resolution(raw: &str, state_applied: &str, resolved: &str, echo: &str) {
    with(|r| {
        r.turn.resolution = Resolution {
            raw: raw.into(),
            state_applied: state_applied.into(),
            resolved: resolved.into(),
            echo: echo.into(),
        }
    });
}

pub fn slip(value: serde_json::Value) {
    with(|r| r.turn.slips.push(value));
}

pub fn gate(name: &str, outcome: &str, reason: &str) {
    with(|r| {
        r.turn.gates.push(Gate {
            name: name.into(),
            outcome: outcome.into(),
            reason: reason.into(),
        })
    });
}

pub fn provenance(records: &[serde_json::Value]) {
    with(|r| r.turn.provenance.extend_from_slice(records));
}

pub fn economics(e: Economics) {
    with(|r| r.turn.economics = e);
}

pub fn locale(loc: &str) {
    with(|r| r.turn.locale = loc.into());
}

pub fn deadline(ms: u64) {
    with(|r| r.turn.deadline_ms = ms);
}

pub fn versions(v: BTreeMap<String, String>) {
    with(|r| r.turn.versions = v);
}

/// Close the turn and hand the finished record back for storage.
pub fn finish(
    question: &str,
    answer: &str,
    source: &str,
    gate_label: &str,
    latency_ms: u64,
    board: Vec<String>,
    numbers: Vec<String>,
) -> Option<Turn> {
    with(|r| {
        r.turn.question = question.into();
        r.turn.answer = answer.into();
        r.turn.source = source.into();
        r.turn.gate = gate_label.into();
        r.turn.latency_ms = latency_ms;
        r.turn.board = board;
        r.turn.numbers = numbers;
        if r.turn.router.path.is_empty() {
            r.turn.router.path = source.into();
            r.turn.router.deciding_stage = "unrecorded".into();
        }
        r.turn.clone()
    })
}

/// The trace id of the turn in flight, for handing to the response and the logs.
pub fn current_id() -> Option<String> {
    with(|r| r.turn.trace_id.clone())
}

// ---------------------------------------------------------------------------------------------
// storage
// ---------------------------------------------------------------------------------------------

/// A bounded, in-memory ring of recent turns. Nothing here reaches disk: the retention window is
/// enforced by the only copy expiring, not by a cleanup job that might not run.
#[derive(Clone)]
pub struct TraceStore {
    inner: Arc<Mutex<VecDeque<Turn>>>,
    cfg: TraceCfg,
}

impl TraceStore {
    pub fn new(cfg: TraceCfg) -> Self {
        TraceStore {
            inner: Arc::new(Mutex::new(VecDeque::new())),
            cfg,
        }
    }

    pub fn cfg(&self) -> &TraceCfg {
        &self.cfg
    }

    pub fn put(&self, turn: Turn) {
        let Ok(mut q) = self.inner.lock() else { return };
        q.push_back(turn);
        while q.len() > self.cfg.capacity {
            q.pop_front();
        }
        self.expire(&mut q);
    }

    fn expire(&self, q: &mut VecDeque<Turn>) {
        let cutoff = now_unix() - self.cfg.retention_secs;
        while q.front().is_some_and(|t| t.started_unix < cutoff) {
            q.pop_front();
        }
    }

    pub fn get(&self, trace_id: &str) -> Option<Turn> {
        let mut q = self.inner.lock().ok()?;
        self.expire(&mut q);
        q.iter().find(|t| t.trace_id == trace_id).cloned()
    }

    /// Newest first, for the operator's index page.
    pub fn recent(&self, limit: usize) -> Vec<Turn> {
        let Ok(mut q) = self.inner.lock() else {
            return Vec::new();
        };
        self.expire(&mut q);
        q.iter().rev().take(limit).cloned().collect()
    }

    pub fn len(&self) -> usize {
        self.inner.lock().map(|q| q.len()).unwrap_or(0)
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

// ---------------------------------------------------------------------------------------------
// promote to golden
// ---------------------------------------------------------------------------------------------

/// Turn a real turn into a well-formed `eval/golden.yaml` item.
///
/// This is the closed loop from a production failure to a regression test, and it is worth more
/// than every panel in the trace view: a panel tells one engineer what happened once, a golden item
/// tells every future change what must not happen again. Gold values take their `source_ref` from
/// the provenance map rather than from the spoken text, because the spoken number is the thing
/// under test — copying it in would enshrine today's answer as tomorrow's expectation, which is how
/// a regression suite quietly starts certifying a bug.
pub fn promote_to_golden(turn: &Turn) -> String {
    let mut out = String::new();
    let id = format!("promoted_{}", &turn.trace_id[..turn.trace_id.len().min(8)]);
    out.push_str(&format!("- id: {id}\n"));
    out.push_str(&format!("  question: {}\n", yaml_str(&turn.question)));
    let locale = if turn.locale.is_empty() {
        "en"
    } else {
        &turn.locale
    };
    out.push_str(&format!("  locale: {locale}\n"));
    out.push_str("  family: promoted_from_production\n");
    out.push_str(&format!("  intent_id: {}\n", yaml_str(&turn.router.path)));
    out.push_str("  precomputable: false\n");
    out.push_str(&format!(
        "  expected_route: {}\n",
        yaml_str(&turn.router.path)
    ));
    let primary = turn.board.first().cloned().unwrap_or_default();
    out.push_str(&format!(
        "  expected_primary_card: {}\n",
        yaml_str(&primary)
    ));
    if turn.board.len() > 1 {
        out.push_str("  expected_support_cards:\n");
        for c in &turn.board[1..] {
            out.push_str(&format!("    - {}\n", yaml_str(c)));
        }
    } else {
        out.push_str("  expected_support_cards: []\n");
    }
    // gold values from provenance, never from the spoken text
    let refs: Vec<&serde_json::Value> = turn
        .provenance
        .iter()
        .filter(|p| p.get("locator").is_some())
        .collect();
    if refs.is_empty() {
        out.push_str("  gold_values: []\n");
    } else {
        out.push_str("  gold_values:\n");
        for (i, p) in refs.iter().enumerate() {
            let label = p
                .get("display_label")
                .and_then(|v| v.as_str())
                .unwrap_or("value");
            let locator = p.get("locator").map(compact_locator).unwrap_or_default();
            out.push_str(&format!("    - name: value_{i}  # {label}\n"));
            out.push_str(&format!("      source_ref: {}\n", yaml_str(&locator)));
        }
    }
    out.push_str("  tolerance: 0.0\n");
    out.push_str("  must_not_contain: []\n");
    out.push_str(&format!(
        "  notes: {}\n",
        yaml_str(&format!(
            "promoted from trace {} ({}); REVIEW before merging — check the expected route and \
             cards are what SHOULD happen, not merely what did",
            turn.trace_id, turn.source
        ))
    ));
    out
}

fn compact_locator(v: &serde_json::Value) -> String {
    match v {
        serde_json::Value::String(s) => s.clone(),
        serde_json::Value::Object(map) => map
            .iter()
            .map(|(k, val)| {
                let s = match val {
                    serde_json::Value::String(s) => s.clone(),
                    other => other.to_string(),
                };
                format!("{k}={s}")
            })
            .collect::<Vec<_>>()
            .join(":"),
        other => other.to_string(),
    }
}

fn yaml_str(s: &str) -> String {
    format!("\"{}\"", s.replace('\\', "\\\\").replace('"', "\\\""))
}

// ---------------------------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------------------------

/// A trace id: the clock for readability, a counter for uniqueness.
///
/// The clock alone is not enough — two turns inside the same nanosecond tick are rare but a
/// collision would silently show one operator another turn's trace, which is the kind of bug that
/// destroys trust in the whole surface. The counter makes uniqueness a property of the process
/// rather than of the timer's resolution.
pub fn new_trace_id() -> String {
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::time::{SystemTime, UNIX_EPOCH};
    static SEQ: AtomicU64 = AtomicU64::new(0);
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos() as u64)
        .unwrap_or(0);
    let seq = SEQ.fetch_add(1, Ordering::Relaxed);
    format!("{:012x}{:04x}", nanos & 0xffff_ffff_ffff, seq & 0xffff)
}

fn short_hash(s: &str) -> String {
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new();
    h.update(s.as_bytes());
    format!("{:x}", h.finalize())[..12].to_string()
}

fn now_unix() -> i64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample() -> Turn {
        Turn {
            trace_id: "abcdef1234567890".into(),
            started_unix: now_unix(),
            session_hash: short_hash("sess-1"),
            locale: "de".into(),
            question: "wie viele Krisentage hatte EURUSD dieses Jahr?".into(),
            answer: "Keine.".into(),
            source: "archive".into(),
            gate: "pass".into(),
            latency_ms: 412,
            router: Router {
                path: "archive".into(),
                deciding_stage: "pre_router".into(),
                precedence_conflict: true,
                candidates: vec![Candidate {
                    id: "regime_history_table".into(),
                    score: 12.4,
                    shown: true,
                }],
            },
            board: vec!["regime_history_table".into()],
            provenance: vec![serde_json::json!({
                "kind": "artifact_cell",
                "display_label": "the published regime record",
                "locator": {"file": "regimes.parquet", "column": "regime", "date": "2026-08-20"},
            })],
            ..Default::default()
        }
    }

    #[test]
    fn session_id_never_stored_raw() {
        let t = sample();
        assert_ne!(t.session_hash, "sess-1");
        assert_eq!(t.session_hash.len(), 12);
    }

    #[test]
    fn promoted_item_takes_gold_from_provenance_not_from_the_answer() {
        let yaml = promote_to_golden(&sample());
        assert!(yaml.contains("source_ref: \"column=regime:date=2026-08-20:file=regimes.parquet\""));
        // the spoken answer must not become the expectation
        assert!(!yaml.contains("gold_value: \"Keine.\""));
        assert!(yaml.contains("REVIEW before merging"));
        assert!(yaml.contains("locale: de"));
        assert!(yaml.contains("expected_primary_card: \"regime_history_table\""));
    }

    #[test]
    fn store_evicts_by_capacity_and_by_age() {
        let store = TraceStore::new(TraceCfg {
            retention_secs: 3600,
            capacity: 3,
            operator_key: None,
        });
        for i in 0..5 {
            let mut t = sample();
            t.trace_id = format!("id{i}");
            store.put(t);
        }
        assert_eq!(store.len(), 3);
        assert!(store.get("id0").is_none(), "oldest evicted by capacity");
        assert!(store.get("id4").is_some());

        let mut old = sample();
        old.trace_id = "ancient".into();
        old.started_unix = now_unix() - 7200;
        let store2 = TraceStore::new(TraceCfg {
            retention_secs: 3600,
            capacity: 10,
            operator_key: None,
        });
        store2.put(old);
        assert!(
            store2.get("ancient").is_none(),
            "a trace past its retention window is gone, not merely hidden"
        );
    }

    #[tokio::test]
    async fn recording_outside_a_scope_is_a_noop_not_a_panic() {
        stage("classifier", 0.0);
        route("pack", "classifier");
        gate("direction_lint", "pass", "");
        assert!(current_id().is_none());
    }

    #[tokio::test]
    async fn a_scoped_turn_records_its_stages_and_route() {
        let t = scope("t-1".into(), "sess-9", async {
            let s = elapsed_ms();
            stage("resolution", s);
            route("archive", "pre_router");
            precedence_conflict();
            gate("numeric_grounding", "pass", "3 numbers checked");
            finish(
                "how many crisis days?",
                "None so far in 2026.",
                "archive",
                "pass",
                42,
                vec!["regime_history_table".into()],
                vec!["2026".into()],
            )
        })
        .await
        .expect("inside a scope finish returns the record");
        assert_eq!(t.trace_id, "t-1");
        assert_eq!(t.router.path, "archive");
        assert_eq!(t.router.deciding_stage, "pre_router");
        assert!(t.router.precedence_conflict);
        assert_eq!(t.stages.len(), 1);
        assert_eq!(t.gates.len(), 1);
        assert_eq!(t.session_hash, short_hash("sess-9"));
    }

    #[test]
    fn trace_ids_do_not_repeat() {
        let ids: std::collections::HashSet<String> = (0..200).map(|_| new_trace_id()).collect();
        assert_eq!(ids.len(), 200);
    }
}
