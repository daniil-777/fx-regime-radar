//! The answer receipt (phase 43, requirement D): one page, printable, auditable.
//!
//! A screenshot of a chat window proves nothing. A fiduciary who forwards a client an answer from
//! this system should be forwarding a document that says what was claimed, where each number came
//! from, what it was true as of, that a machine produced it, and how to check the ledger without
//! trusting us. That is the difference between a product a regulated professional can use in front
//! of a client and one they can only use privately.
//!
//! **One renderer, two callers.** The customer path posts the answer it is holding; the operator
//! path rebuilds the same payload from a trace. Both call `render`, so "regeneration from the trace
//! is byte-identical" is a property of the design rather than a claim a test has to keep chasing.
//!
//! **Deterministic.** Nothing here reads the clock. Every date on the page comes from the data's own
//! as-of stamps, so the same answer renders the same bytes today and next year — which is the only
//! way a receipt can be re-issued to settle a dispute about what was said.

use serde::{Deserialize, Serialize};

/// Everything a receipt states. Built by the widget from the answer it holds, or by the operator
/// surface from a stored trace — the two must produce the same struct for the same turn.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ReceiptPayload {
    /// Stable id for this answer. Never a session id, a user id or anything derived from one.
    pub answer_id: String,
    pub question: String,
    pub answer: String,
    /// The provenance records behind the answer, in render order.
    #[serde(default)]
    pub provenance: Vec<serde_json::Value>,
    /// The data date the answer speaks about.
    #[serde(default)]
    pub data_through: String,
    /// Short chain head of the sealed ledger, for independent verification.
    #[serde(default)]
    pub chain_head: String,
    /// The AI-presenter disclosure, taken from the context pack so it cannot drift from the spoken
    /// one.
    #[serde(default)]
    pub disclosure: String,
}

const DISCLAIMER: &str = "Educational tool. Not investment advice.";

/// The design tokens, compiled in from the file `scripts/gen_tokens.py` generates.
///
/// `design/tokens.json` is the single source for every colour in this project, and a printed
/// receipt is no more exempt than a screen is. Compiling the file in rather than reading it at
/// runtime means a stale palette is a build-time fact, not a surprise on a customer's printout.
const TOKENS: &str = include_str!("../static/tokens.json");

struct Palette {
    bg: String,
    card: String,
    line: String,
    text: String,
    dim: String,
    accent: String,
}

fn palette() -> Palette {
    let v: serde_json::Value = serde_json::from_str(TOKENS).unwrap_or(serde_json::Value::Null);
    let pick = |group: &str, key: &str, fallback: &str| {
        v.get(group)
            .and_then(|g| g.get(key))
            .and_then(|c| c.as_str())
            .unwrap_or(fallback)
            .to_string()
    };
    Palette {
        bg: pick("light", "bg", "#FFFFFF"),
        card: pick("light", "card", "#F4F6FA"),
        line: pick("light", "line", "#E1E6EE"),
        text: pick("light", "text", "#0E1420"),
        dim: pick("light", "text_dim", "#6B7785"),
        // The one accent, used exactly twice: the answer's edge and the presenter badge.
        accent: pick("accent", "beacon", "#7FD1C9"),
    }
}

fn esc(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

fn field(v: &serde_json::Value, key: &str) -> String {
    match v.get(key) {
        Some(serde_json::Value::String(s)) => s.clone(),
        Some(serde_json::Value::Null) | None => String::new(),
        Some(other) => other.to_string(),
    }
}

/// Render the locator as something a person can act on rather than a JSON blob.
fn locator_text(v: &serde_json::Value) -> String {
    match v.get("locator") {
        Some(serde_json::Value::Object(map)) => map
            .iter()
            .map(|(k, val)| {
                let s = match val {
                    serde_json::Value::String(s) => s.clone(),
                    other => other.to_string(),
                };
                format!("{k} {s}")
            })
            .collect::<Vec<_>>()
            .join(" · "),
        Some(serde_json::Value::String(s)) => s.clone(),
        Some(other) => other.to_string(),
        None => String::new(),
    }
}

/// The receipt's identifier: derived from the ANSWER, never from the session.
///
/// The same answer yields the same id for every reader, which is what makes a receipt re-issuable
/// and comparable — and it means no filename or URL can be traced back to a person.
pub fn answer_id(answer: &str) -> String {
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new();
    h.update(answer.as_bytes());
    format!("a_{}", &format!("{:x}", h.finalize())[..12])
}

/// The receipt, as a self-contained printable page.
pub fn render(p: &ReceiptPayload) -> String {
    let pal = palette();
    let mut rows = String::new();
    for rec in &p.provenance {
        let label = field(rec, "display_label");
        let kind = field(rec, "kind");
        let as_of = field(rec, "as_of");
        let tier = field(rec, "source_tier");
        rows.push_str(&format!(
            "<tr><td>{}</td><td class=mono>{}</td><td class=mono>{}</td><td class=mono>{}</td>\
             <td class=mono>{}</td></tr>",
            esc(&label),
            esc(&kind),
            esc(&locator_text(rec)),
            esc(&as_of),
            esc(&tier),
        ));
    }
    if p.provenance.is_empty() {
        rows.push_str(
            "<tr><td colspan=5 class=quiet>This answer used no published figure — it is a \
             refusal or an explanation of method.</td></tr>",
        );
    }

    let versions = p
        .provenance
        .first()
        .and_then(|r| r.get("versions"))
        .and_then(|v| v.as_object())
        .map(|m| {
            m.iter()
                .map(|(k, v)| {
                    format!(
                        "{k} {}",
                        match v {
                            serde_json::Value::String(s) => s.clone(),
                            other => other.to_string(),
                        }
                    )
                })
                .collect::<Vec<_>>()
                .join(" · ")
        })
        .unwrap_or_default();

    let verify = if p.chain_head.is_empty() {
        String::new()
    } else {
        format!(
            "<h2>Verify this independently</h2>\
             <p>Every forecast is written to an append-only, hash-chained ledger before its outcome \
             is known. The chain head at the time of this answer was <span class=mono>{head}</span>. \
             Recompute the chain from the published ledger file and compare: if a single past row \
             had been edited, the head would not match. You do not have to trust this page — you \
             can check it.</p>",
            head = esc(&p.chain_head)
        )
    };

    format!(
        r#"<!doctype html><html lang=en><head><meta charset=utf-8>
<title>Answer receipt {id}</title>
<style>
:root{{color-scheme:light}}
body{{background:{bg};color:{text};font:14px/1.55 "IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;margin:0;padding:40px;max-width:760px}}
h1{{font-size:17px;margin:0 0 2px;font-family:"Space Grotesk",Georgia,serif;font-weight:500}}
h2{{font-size:12px;margin:26px 0 8px;text-transform:uppercase;letter-spacing:.09em;color:{dim}}}
.mono{{font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;font-variant-numeric:tabular-nums;font-size:12px}}
.quiet{{color:{dim}}}
.q{{color:{dim};margin:0 0 4px}}
.a{{font-size:15px;background:{card};border:1px solid {line};border-left:3px solid {accent};border-radius:6px;padding:14px 16px;margin:0}}
table{{border-collapse:collapse;width:100%}}
td,th{{padding:6px 8px;border-bottom:1px solid {line};text-align:left;vertical-align:top;font-size:12px}}
th{{color:{dim};font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.06em}}
td.mono{{text-align:left}}
footer{{margin-top:28px;padding-top:14px;border-top:2px solid {text};font-size:12px}}
.badge{{display:inline-block;border:1px solid {text};color:{text};border-radius:4px;padding:1px 7px;font-size:11px;font-weight:600}}
@media print{{body{{padding:0}}@page{{margin:18mm}}}}
</style></head><body>
<h1>Answer receipt</h1>
<p class="mono quiet">{id} · data through {through}</p>

<h2>Question</h2><p class=q>{q}</p>
<h2>Answer</h2><p class=a>{a}</p>

<h2>Where every figure came from</h2>
<table><tr><th>value</th><th>kind</th><th>source</th><th>as of</th><th>tier</th></tr>{rows}</table>
{versions_block}
{verify}

<footer>
<p><span class=badge>AI PRESENTER</span> {disclosure}</p>
<p><strong>{disclaimer}</strong> This document reports what the system computed and published. It
describes market conditions and the risk of those conditions changing. It contains no forecast of
price direction and no personal recommendation.</p>
</footer>
</body></html>"#,
        bg = pal.bg,
        card = pal.card,
        line = pal.line,
        text = pal.text,
        dim = pal.dim,
        accent = pal.accent,
        id = esc(&p.answer_id),
        through = esc(&p.data_through),
        q = esc(&p.question),
        a = esc(&p.answer),
        rows = rows,
        versions_block = if versions.is_empty() {
            String::new()
        } else {
            format!(
                "<h2>Rules in force when this answer was produced</h2><p class=mono>{}</p>",
                esc(&versions)
            )
        },
        verify = verify,
        disclosure = esc(if p.disclosure.is_empty() {
            "This answer was produced and voiced by a computer, not a person."
        } else {
            &p.disclosure
        }),
        disclaimer = DISCLAIMER,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn payload() -> ReceiptPayload {
        ReceiptPayload {
            answer_id: "a_9f31c2".into(),
            question: "how unusual is today?".into(),
            answer: "EURUSD reads calm; the siren is 73 of 100.".into(),
            provenance: vec![json!({
                "kind": "artifact_cell",
                "display_label": "today's published state",
                "locator": {"file": "regimes.parquet", "column": "anomaly_pct", "date": "2026-08-18"},
                "as_of": "2026-08-18",
                "source_tier": "published artifact",
                "versions": {"registry": "3.1.0", "gate_rules": "1.2.0"},
            })],
            data_through: "2026-08-18".into(),
            chain_head: "9f2c41ab".into(),
            disclosure: "I am the radar's AI presenter.".into(),
        }
    }

    #[test]
    fn the_receipt_is_deterministic() {
        assert_eq!(render(&payload()), render(&payload()));
    }

    #[test]
    fn it_carries_the_disclosures_and_the_verification_route() {
        let html = render(&payload());
        assert!(html.contains("Educational tool. Not investment advice."));
        assert!(html.contains("AI PRESENTER"));
        assert!(html.contains("9f2c41ab"));
        assert!(html.contains("Verify this independently"));
        assert!(html.contains("anomaly_pct"));
        assert!(html.contains("gate_rules 1.2.0"));
    }

    #[test]
    fn no_personal_data_reaches_the_page_or_its_identifier() {
        let mut p = payload();
        p.answer_id = "a_9f31c2".into();
        let html = render(&p);
        for leak in ["session", "s-ops", "user_id", "email"] {
            assert!(!html.contains(leak), "{leak:?} appears in the receipt");
        }
        // An address, not the "@" character: the print stylesheet legitimately contains @media and
        // @page, and a check that cannot tell those from an e-mail address would be switched off
        // the first time someone touched the CSS.
        let address_like = html
            .split_whitespace()
            .any(|w| w.contains('@') && w.contains('.') && !w.starts_with('@'));
        assert!(!address_like, "something address-shaped is on the receipt");
    }

    #[test]
    fn an_answer_with_no_figures_says_so_rather_than_showing_an_empty_table() {
        let mut p = payload();
        p.provenance.clear();
        let html = render(&p);
        assert!(html.contains("used no published figure"));
    }

    #[test]
    fn markup_in_the_question_cannot_escape_into_the_page() {
        let mut p = payload();
        p.question = "<script>alert(1)</script>".into();
        let html = render(&p);
        assert!(!html.contains("<script>alert"));
        assert!(html.contains("&lt;script&gt;"));
    }
}
