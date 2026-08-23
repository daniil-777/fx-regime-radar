//! The operator surface (phase 43): `/ops/*`, gated, audited, and never linked from anywhere a
//! customer can reach.
//!
//! Everything the customer surface deliberately hides lives here — stage timings, the deciding
//! stage, retrieval scores, gate verdicts, prompt economics. The separation is enforced rather than
//! intended: these routes sit behind an operator key, they are excluded from the OpenAPI document
//! the customer-facing widget reads, and `tests/separation.rs` asserts that no string from this
//! module can appear in a customer render.
//!
//! Two of the surfaces here are worth more than the panels. **Replay** re-runs a recorded turn
//! through the live deterministic routing chain and diffs the result, which turns "the assistant
//! answered the wrong thing yesterday" into a reproducible case. **Promote to golden** converts a
//! turn into an `eval/golden.yaml` item with its gold values taken from the provenance map, which
//! closes the loop from a production failure to a permanent regression test. A panel informs one
//! engineer once; a golden item constrains every change that follows.

use axum::{
    extract::{Path, State},
    http::{HeaderMap, StatusCode},
    response::{Html, IntoResponse, Response},
    Json,
};
use serde::Serialize;
use serde_json::json;
use sha2::{Digest, Sha256};

use crate::app::ApiError;
use crate::app::AppState;
use crate::trace::Turn;

// ---------------------------------------------------------------------------------------------
// auth + audit
// ---------------------------------------------------------------------------------------------

fn constant_time_eq(a: &str, b: &str) -> bool {
    let (a, b) = (a.as_bytes(), b.as_bytes());
    if a.len() != b.len() {
        return false;
    }
    a.iter().zip(b).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

fn key_hash(key: &str) -> String {
    let mut h = Sha256::new();
    h.update(key.as_bytes());
    format!("{:x}", h.finalize())[..12].to_string()
}

/// 401 unless the request carries the operator key. With no key configured, `/ops/*` is closed to
/// everyone — the right default for a surface whose entire content is internal, and the reason a
/// misconfigured deployment fails shut rather than open.
fn require_operator(st: &AppState, headers: &HeaderMap) -> Result<String, ApiError> {
    let unauthorized = || ApiError(StatusCode::UNAUTHORIZED, "operator key required".into());
    let expected = st
        .traces
        .cfg()
        .operator_key
        .as_deref()
        .filter(|k| !k.is_empty())
        .ok_or_else(unauthorized)?;
    let got = headers
        .get("x-ops-key")
        .and_then(|v| v.to_str().ok())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .ok_or_else(unauthorized)?;
    if constant_time_eq(got, expected) {
        Ok(key_hash(got))
    } else {
        Err(unauthorized())
    }
}

fn audit(st: &AppState, action: &str, trace_id: &str, kh: &str, detail: &str) {
    if let Err(e) = st.store.add_ops_audit(action, trace_id, kh, detail) {
        tracing::warn!(error = %e, "ops audit write failed");
    }
}

// ---------------------------------------------------------------------------------------------
// handlers
// ---------------------------------------------------------------------------------------------

/// Index of recent turns.
pub async fn traces_index(
    State(st): State<AppState>,
    headers: HeaderMap,
) -> Result<Response, ApiError> {
    let kh = require_operator(&st, &headers)?;
    audit(&st, "index", "", &kh, "");
    crate::metrics::trace_view_open();
    let turns = st.traces.recent(100);
    Ok(Html(render_index(&turns, st.traces.cfg().retention_secs)).into_response())
}

/// One turn, as the operator page.
pub async fn trace_view(
    State(st): State<AppState>,
    headers: HeaderMap,
    Path(trace_id): Path<String>,
) -> Result<Response, ApiError> {
    let kh = require_operator(&st, &headers)?;
    let turn = st.traces.get(&trace_id).ok_or_else(|| {
        ApiError(
            StatusCode::NOT_FOUND,
            "no such trace, or it has expired".into(),
        )
    })?;
    audit(&st, "view", &trace_id, &kh, &turn.router.path);
    crate::metrics::trace_view_open();
    Ok(Html(render_trace(&turn)).into_response())
}

/// The same turn as JSON, for export and for tooling.
pub async fn trace_json(
    State(st): State<AppState>,
    headers: HeaderMap,
    Path(trace_id): Path<String>,
) -> Result<Json<Turn>, ApiError> {
    let kh = require_operator(&st, &headers)?;
    let turn = st.traces.get(&trace_id).ok_or_else(|| {
        ApiError(
            StatusCode::NOT_FOUND,
            "no such trace, or it has expired".into(),
        )
    })?;
    audit(&st, "export", &trace_id, &kh, "");
    Ok(Json(turn))
}

#[derive(Serialize)]
pub struct ReplayReport {
    pub trace_id: String,
    /// true when every compared field matched the recording
    pub reproduced: bool,
    /// Present when the turn used the model: generation is not deterministic, and pretending
    /// otherwise would make a green replay meaningless.
    pub not_replayable: Option<String>,
    pub diffs: Vec<ReplayDiff>,
}

#[derive(Serialize)]
pub struct ReplayDiff {
    pub field: String,
    pub recorded: String,
    pub replayed: String,
}

/// Re-run the turn through the live deterministic routing chain and diff.
pub async fn trace_replay(
    State(st): State<AppState>,
    headers: HeaderMap,
    Path(trace_id): Path<String>,
) -> Result<Json<ReplayReport>, ApiError> {
    let kh = require_operator(&st, &headers)?;
    let turn = st.traces.get(&trace_id).ok_or_else(|| {
        ApiError(
            StatusCode::NOT_FOUND,
            "no such trace, or it has expired".into(),
        )
    })?;
    crate::metrics::trace_replay();
    let report = replay(&st, &turn);
    audit(
        &st,
        "replay",
        &trace_id,
        &kh,
        if report.reproduced {
            "reproduced"
        } else {
            "diverged"
        },
    );
    Ok(Json(report))
}

pub fn replay(st: &AppState, turn: &Turn) -> ReplayReport {
    // A model-generated answer cannot be replayed byte-for-byte, and a replay that quietly compared
    // only the fields that happen to match would be worse than no replay at all.
    if turn.source == "llm" {
        return ReplayReport {
            trace_id: turn.trace_id.clone(),
            reproduced: false,
            not_replayable: Some(
                "this turn was generated by the model; replay covers the deterministic chain \
                 (resolution, guards, archive, packs, board selection) only"
                    .into(),
            ),
            diffs: Vec::new(),
        };
    }
    // Replay the RESOLVED question when the turn had one: "and USDCHF?" is not a question until
    // conversation state has expanded it, and replaying the raw ellipsis would diverge for a reason
    // that has nothing to do with the bug under investigation.
    let question = if turn.resolution.resolved.is_empty() {
        &turn.question
    } else {
        &turn.resolution.resolved
    };
    let out = crate::avatar::replay_deterministic(st, question);
    let mut diffs = Vec::new();
    let mut compare = |field: &str, recorded: &str, replayed: &str| {
        if recorded != replayed {
            diffs.push(ReplayDiff {
                field: field.into(),
                recorded: recorded.into(),
                replayed: replayed.into(),
            });
        }
    };
    compare("route", &turn.router.path, &out.route);
    compare("text", &turn.answer, &out.text);
    let recorded_board = turn.board.join(", ");
    let replayed_board = out.board.join(", ");
    compare("board", &recorded_board, &replayed_board);
    ReplayReport {
        trace_id: turn.trace_id.clone(),
        reproduced: diffs.is_empty(),
        not_replayable: None,
        diffs,
    }
}

#[derive(Serialize)]
pub struct PromoteReport {
    pub trace_id: String,
    pub yaml: String,
    pub note: String,
}

/// Convert the turn into a golden item, ready for review.
pub async fn trace_promote(
    State(st): State<AppState>,
    headers: HeaderMap,
    Path(trace_id): Path<String>,
) -> Result<Json<PromoteReport>, ApiError> {
    let kh = require_operator(&st, &headers)?;
    let turn = st.traces.get(&trace_id).ok_or_else(|| {
        ApiError(
            StatusCode::NOT_FOUND,
            "no such trace, or it has expired".into(),
        )
    })?;
    audit(&st, "promote", &trace_id, &kh, &turn.router.path);
    crate::metrics::golden_promoted();
    Ok(Json(PromoteReport {
        trace_id: trace_id.clone(),
        yaml: crate::trace::promote_to_golden(&turn),
        note: "Append to eval/golden.yaml after review. The expected route and cards record what \
               DID happen; confirm they are what SHOULD happen before merging, or the suite will \
               certify the bug you were investigating."
            .into(),
    }))
}

/// Rebuild the payload a receipt is made from, out of a stored trace.
///
/// This is the half of "regenerable from the trace" that the customer path cannot supply: the
/// customer holds the answer but not the record. Both halves end in `receipt::render`, so the two
/// documents are the same bytes by construction rather than by periodic comparison.
pub fn payload_from_trace(turn: &Turn) -> crate::receipt::ReceiptPayload {
    crate::receipt::ReceiptPayload {
        // Not the trace id: the receipt names the ANSWER, and two operators reissuing the same
        // answer must produce the same document.
        answer_id: crate::receipt::answer_id(&turn.answer),
        question: turn.question.clone(),
        answer: turn.answer.clone(),
        provenance: turn.provenance.clone(),
        data_through: turn.versions.get("context").cloned().unwrap_or_default(),
        chain_head: turn.versions.get("chain_head").cloned().unwrap_or_default(),
        disclosure: turn.versions.get("disclosure").cloned().unwrap_or_default(),
    }
}

/// The receipt for a recorded turn, re-rendered from the trace.
pub async fn trace_receipt(
    State(st): State<AppState>,
    headers: HeaderMap,
    Path(trace_id): Path<String>,
) -> Result<Response, ApiError> {
    let kh = require_operator(&st, &headers)?;
    let turn = st.traces.get(&trace_id).ok_or_else(|| {
        ApiError(
            StatusCode::NOT_FOUND,
            "no such trace, or it has expired".into(),
        )
    })?;
    audit(&st, "receipt", &trace_id, &kh, "");
    crate::metrics::receipt_export();
    Ok(Html(crate::receipt::render(&payload_from_trace(&turn))).into_response())
}

/// Read the current flags.
pub async fn flags_get(
    State(st): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<serde_json::Value>, ApiError> {
    let kh = require_operator(&st, &headers)?;
    audit(&st, "flags_read", "", &kh, "");
    let f = st.flags.get();
    Ok(Json(json!({
        "flags": &*f,
        "config_hash": f.config_hash(),
        "stamp": f.stamp(),
        "source": st.flags.path().display().to_string(),
    })))
}

#[derive(serde::Deserialize)]
pub struct FlagSet {
    pub flag: String,
    pub value: serde_json::Value,
}

/// Flip one flag. Takes effect on the next turn — including for sessions already in progress,
/// which is the property that makes the kill switch a mitigation rather than a deploy.
pub async fn flags_set(
    State(st): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<FlagSet>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let kh = require_operator(&st, &headers)?;
    let next = st
        .flags
        .set(&req.flag, req.value.clone())
        .map_err(|e| ApiError(StatusCode::BAD_REQUEST, e))?;
    audit(
        &st,
        "flags_set",
        "",
        &kh,
        &format!("{}={}", req.flag, req.value),
    );
    tracing::warn!(flag = %req.flag, value = %req.value, "runtime flag changed");
    Ok(Json(
        json!({"flags": next, "config_hash": next.config_hash()}),
    ))
}

/// The audit trail itself, so an operator can see who looked at what.
pub async fn audit_log(
    State(st): State<AppState>,
    headers: HeaderMap,
) -> Result<Response, ApiError> {
    let kh = require_operator(&st, &headers)?;
    let rows = st.store.recent_ops_audit(200).unwrap_or_default();
    audit(&st, "audit", "", &kh, "");
    Ok(Json(json!({
        "rows": rows.iter().map(|r| json!({
            "ts": r.ts, "action": r.action, "trace_id": r.trace_id,
            "key": r.key_hash, "detail": r.detail,
        })).collect::<Vec<_>>()
    }))
    .into_response())
}

// ---------------------------------------------------------------------------------------------
// rendering — plain, dense, and unapologetically internal
// ---------------------------------------------------------------------------------------------

fn esc(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

const OPS_CSS: &str = r#"
:root{color-scheme:dark}
body{background:#0b0f17;color:#e8ecf4;font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;margin:0;padding:24px}
h1{font-size:16px;margin:0 0 4px}h2{font-size:13px;margin:24px 0 8px;color:#9aa6b8;text-transform:uppercase;letter-spacing:.08em}
a{color:#7fd1c9}table{border-collapse:collapse;width:100%;margin:0 0 8px}
td,th{padding:4px 8px;border-bottom:1px solid rgba(255,255,255,.08);text-align:left;vertical-align:top}
th{color:#9aa6b8;font-weight:500}
.meta{color:#9aa6b8}.ok{color:#3ecf8e}.bad{color:#ff5c5c}.warn{color:#f5b942}
.bar{position:relative;height:14px;background:rgba(255,255,255,.04);border-radius:2px}
.bar span{position:absolute;top:0;height:14px;background:#4da3ff;border-radius:2px;min-width:2px}
.dl{position:absolute;top:-3px;height:20px;width:2px;background:#ff5c5c}
pre{background:#131a26;border:1px solid rgba(255,255,255,.08);padding:12px;overflow-x:auto;border-radius:6px}
.q{color:#e8ecf4;font-size:14px}
button{background:#151d2e;color:#e8ecf4;border:1px solid rgba(255,255,255,.16);border-radius:6px;padding:6px 12px;font:inherit;cursor:pointer}
button:hover{border-color:#7fd1c9}
"#;

fn render_index(turns: &[Turn], retention_secs: i64) -> String {
    let mut rows = String::new();
    for t in turns {
        rows.push_str(&format!(
            "<tr><td><a href=\"/ops/trace/{id}\">{id}</a></td><td>{path}</td><td>{gate}</td>\
             <td style=\"text-align:right\">{ms} ms</td><td>{q}</td></tr>",
            id = esc(&t.trace_id),
            path = esc(&t.router.path),
            gate = esc(&t.gate),
            ms = t.latency_ms,
            q = esc(&truncate(&t.question, 80)),
        ));
    }
    format!(
        "<!doctype html><meta charset=utf-8><title>traces</title><style>{OPS_CSS}</style>\
         <h1>Recent turns</h1>\
         <p class=meta>{n} held · retention {mins} min · in memory only, never written to disk</p>\
         <table><tr><th>trace</th><th>route</th><th>gate</th><th style=\"text-align:right\">latency</th><th>question</th></tr>{rows}</table>",
        n = turns.len(),
        mins = retention_secs / 60,
    )
}

fn truncate(s: &str, n: usize) -> String {
    if s.chars().count() <= n {
        return s.to_string();
    }
    let head: String = s.chars().take(n).collect();
    format!("{head}…")
}

fn render_trace(t: &Turn) -> String {
    let mut h = String::new();
    h.push_str(&format!(
        "<!doctype html><meta charset=utf-8><title>trace {id}</title><style>{OPS_CSS}</style>\
         <h1>trace {id}</h1><p class=meta>session {sh} · {path} via {stage} · gate {gate} · {ms} ms</p>\
         <p class=q>{q}</p><pre>{a}</pre>",
        id = esc(&t.trace_id),
        sh = esc(&t.session_hash),
        path = esc(&t.router.path),
        stage = esc(&t.router.deciding_stage),
        gate = esc(&t.gate),
        ms = t.latency_ms,
        q = esc(&t.question),
        a = esc(&t.answer),
    ));

    // --- timeline -----------------------------------------------------------------------------
    h.push_str("<h2>Timeline</h2>");
    let total = t
        .stages
        .iter()
        .map(|s| s.end_ms)
        .fold(t.latency_ms as f64, f64::max)
        .max(1.0);
    h.push_str("<table>");
    for s in &t.stages {
        let left = s.start_ms / total * 100.0;
        let width = (s.duration_ms() / total * 100.0).max(0.4);
        h.push_str(&format!(
            "<tr><td style=\"width:22%\">{name}</td><td style=\"width:60%\"><div class=bar>\
             <span style=\"left:{left:.2}%;width:{width:.2}%\"></span>{dl}</div></td>\
             <td style=\"text-align:right;width:18%\">{d:.1} ms</td></tr>",
            name = esc(&s.name),
            d = s.duration_ms(),
            dl = if t.deadline_ms > 0 && (t.deadline_ms as f64) <= total {
                format!(
                    "<i class=dl style=\"left:{:.2}%\" title=\"deadline\"></i>",
                    t.deadline_ms as f64 / total * 100.0
                )
            } else {
                String::new()
            },
        ));
    }
    if t.stages.is_empty() {
        h.push_str("<tr><td class=meta colspan=3>no stages recorded for this turn</td></tr>");
    }
    h.push_str("</table>");
    if t.deadline_ms > 0 {
        h.push_str(&format!(
            "<p class=meta>deadline {} ms (red line)</p>",
            t.deadline_ms
        ));
    }

    // --- router -------------------------------------------------------------------------------
    h.push_str("<h2>Router</h2><table>");
    h.push_str(&format!(
        "<tr><th>path</th><td>{}</td></tr><tr><th>deciding stage</th><td>{}</td></tr>\
         <tr><th>precedence conflict</th><td class={cls}>{c}</td></tr>",
        esc(&t.router.path),
        esc(&t.router.deciding_stage),
        cls = if t.router.precedence_conflict {
            "warn"
        } else {
            "meta"
        },
        c = if t.router.precedence_conflict {
            "yes — the pre-router and a confident intent disagreed; precedence resolved it"
        } else {
            "no"
        },
    ));
    h.push_str("</table>");
    if !t.router.candidates.is_empty() {
        h.push_str("<table><tr><th>candidate</th><th style=\"text-align:right\">score</th><th>shown</th></tr>");
        for c in &t.router.candidates {
            h.push_str(&format!(
                "<tr><td>{}</td><td style=\"text-align:right\">{:.2}</td><td>{}</td></tr>",
                esc(&c.id),
                c.score,
                if c.shown { "yes" } else { "" }
            ));
        }
        h.push_str("</table>");
    }

    // --- resolution ---------------------------------------------------------------------------
    h.push_str("<h2>Resolution</h2><table>");
    for (k, v) in [
        ("raw utterance", &t.resolution.raw),
        ("state applied", &t.resolution.state_applied),
        ("resolved to", &t.resolution.resolved),
        ("echoed to the user", &t.resolution.echo),
    ] {
        h.push_str(&format!(
            "<tr><th style=\"width:22%\">{k}</th><td>{}</td></tr>",
            if v.is_empty() {
                "<span class=meta>—</span>".to_string()
            } else {
                esc(v)
            }
        ));
    }
    h.push_str("</table>");

    // --- slips --------------------------------------------------------------------------------
    h.push_str("<h2>Slips</h2>");
    if t.slips.is_empty() {
        h.push_str("<p class=meta>none — this turn answered without a room request</p>");
    } else {
        for s in &t.slips {
            h.push_str(&format!(
                "<pre>{}</pre>",
                esc(&serde_json::to_string_pretty(s).unwrap_or_default())
            ));
        }
    }

    // --- gates --------------------------------------------------------------------------------
    h.push_str("<h2>Gates</h2><table><tr><th>gate</th><th>outcome</th><th>reason</th></tr>");
    for g in &t.gates {
        let cls = match g.outcome.as_str() {
            "pass" => "ok",
            "fail" | "blocked" => "bad",
            "regenerated" => "warn",
            _ => "meta",
        };
        h.push_str(&format!(
            "<tr><td>{}</td><td class={cls}>{}</td><td class=meta>{}</td></tr>",
            esc(&g.name),
            esc(&g.outcome),
            esc(&g.reason)
        ));
    }
    if t.gates.is_empty() {
        h.push_str("<tr><td class=meta colspan=3>no gates recorded</td></tr>");
    }
    h.push_str("</table>");

    // --- provenance map -----------------------------------------------------------------------
    h.push_str("<h2>Provenance map</h2><table><tr><th>kind</th><th>label</th><th>locator</th><th>as of</th></tr>");
    for p in &t.provenance {
        let g = |k: &str| {
            p.get(k)
                .map(|v| match v {
                    serde_json::Value::String(s) => s.clone(),
                    other => other.to_string(),
                })
                .unwrap_or_default()
        };
        h.push_str(&format!(
            "<tr><td>{}</td><td>{}</td><td class=meta>{}</td><td>{}</td></tr>",
            esc(&g("kind")),
            esc(&g("display_label")),
            esc(&truncate(&g("locator"), 90)),
            esc(&g("as_of")),
        ));
    }
    if t.provenance.is_empty() {
        h.push_str("<tr><td class=meta colspan=4>no values — a refusal or a pure-knowledge answer</td></tr>");
    }
    h.push_str("</table>");

    // --- prompt economics ---------------------------------------------------------------------
    h.push_str("<h2>Prompt economics</h2><table>");
    let e = &t.economics;
    let cache_cls = match e.cache.as_str() {
        "hit" => "ok",
        "miss" => "warn",
        _ => "meta",
    };
    h.push_str(&format!(
        "<tr><th style=\"width:22%\">prefix hash</th><td>{}</td></tr>\
         <tr><th>cache</th><td class={cache_cls}>{}</td></tr>\
         <tr><th>input / cached / output</th><td>{} / {} / {}</td></tr>\
         <tr><th>cost</th><td>{:.5} CHF</td></tr>",
        if e.prefix_hash.is_empty() {
            "<span class=meta>—</span>".into()
        } else {
            esc(&e.prefix_hash)
        },
        if e.cache.is_empty() {
            "n/a".to_string()
        } else {
            esc(&e.cache)
        },
        e.input_tokens,
        e.cached_tokens,
        e.output_tokens,
        e.cost_chf,
    ));
    h.push_str("</table>");

    // --- versions -----------------------------------------------------------------------------
    if !t.versions.is_empty() {
        h.push_str("<h2>Versions</h2><table>");
        for (k, v) in &t.versions {
            h.push_str(&format!(
                "<tr><th style=\"width:22%\">{}</th><td>{}</td></tr>",
                esc(k),
                esc(v)
            ));
        }
        h.push_str("</table>");
    }

    // --- actions ------------------------------------------------------------------------------
    h.push_str(&format!(
        "<h2>Actions</h2><p><button onclick=\"act('replay')\">Replay against the live chain</button> \
         <button onclick=\"act('promote')\">Promote to golden</button></p><pre id=out class=meta>\
         Replay re-runs the deterministic chain and diffs. Promote turns this turn into an \
         eval/golden.yaml item, with gold values taken from the provenance map rather than from \
         the answer text.</pre>\
         <script>\
         async function act(what){{\
           const key=localStorage.getItem('opsKey')||prompt('operator key');\
           if(!key)return; localStorage.setItem('opsKey',key);\
           const r=await fetch('/ops/trace/{id}/'+what,{{method:'POST',headers:{{'X-Ops-Key':key}}}});\
           const j=await r.json();\
           document.getElementById('out').textContent=j.yaml||JSON.stringify(j,null,1);\
         }}</script>",
        id = esc(&t.trace_id)
    ));
    h
}
