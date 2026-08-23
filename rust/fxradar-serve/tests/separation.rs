//! Phase 43 requirement F: the customer surface and the operator surface stay apart, and the
//! separation is a test rather than an intention.
//!
//! The failure this guards against is gradual and reasonable-looking at every step: someone adds a
//! latency figure to a tooltip "just for debugging", someone links the trace from a support view,
//! someone returns the trace id in the answer payload so the widget can log it. Each is defensible
//! alone; together they turn the calm surface into the console this phase exists to prevent. A test
//! is the only thing that notices the accumulation.

use std::path::{Path, PathBuf};

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("repo root")
        .to_path_buf()
}

fn read(rel: &str) -> String {
    let p = repo_root().join(rel);
    std::fs::read_to_string(&p).unwrap_or_else(|e| panic!("read {}: {e}", p.display()))
}

/// The strings that mean "you are looking at the machine". None may reach the widget.
const OPERATOR_STRINGS: &[&str] = &[
    "/ops/",
    "trace_id",
    "deciding stage",
    "precedence conflict",
    "prompt economics",
    "prefix hash",
    "cached_tokens",
    "cost_chf",
    "X-Ops-Key",
    "promote to golden",
    "slip",
    "deadline_ms",
];

#[test]
fn the_widget_carries_no_operator_string() {
    let widget = read("rust/fxradar-serve/static/avatar.html").to_lowercase();
    for needle in OPERATOR_STRINGS {
        assert!(
            !widget.contains(&needle.to_lowercase()),
            "the customer widget contains the operator string {needle:?}; the trace view is not \
             part of the product surface"
        );
    }
}

#[test]
fn the_card_renderer_carries_no_operator_string() {
    let cards = read("rust/fxradar-serve/static/cards.js").to_lowercase();
    for needle in OPERATOR_STRINGS {
        assert!(
            !cards.contains(&needle.to_lowercase()),
            "cards.js contains the operator string {needle:?}"
        );
    }
}

#[test]
fn the_widget_never_imports_a_trace_component() {
    let widget = read("rust/fxradar-serve/static/avatar.html");
    for bad in ["ops.js", "trace.js", "/ops/traces", "opsKey"] {
        assert!(
            !widget.contains(bad),
            "the customer bundle references {bad:?}: separate bundles means separate bundles"
        );
    }
}

/// The customer response schema must not carry an operator identifier. A trace id in the payload is
/// how "strictly separate" quietly becomes "separate except for the bit we needed".
#[test]
fn the_brain_response_exposes_no_trace_id() {
    let src = read("rust/fxradar-serve/src/avatar.rs");
    let start = src.find("pub struct BrainResponse").expect("BrainResponse");
    let end = src[start..].find("\n}").expect("end of struct") + start;
    let body = &src[start..end];
    assert!(
        !body.contains("trace"),
        "BrainResponse exposes a trace field to the customer:\n{body}"
    );
}

/// Timings belong to the operator. The widget may know that an answer is slow — that is what the
/// wait line is for — but it must never render a number of milliseconds.
#[test]
fn the_widget_renders_no_timing_to_the_user() {
    let widget = read("rust/fxradar-serve/static/avatar.html");
    for line in widget.lines() {
        let l = line.trim();
        // The threshold constants themselves are code, not copy; the ban is on rendered text.
        if l.starts_with("//") || l.starts_with("*") || l.starts_with("const ") {
            continue;
        }
        let rendered = l.contains("textContent") || l.contains("innerHTML") || l.contains("addMsg");
        if rendered {
            assert!(
                !l.contains("latency") && !l.contains("elapsed") && !l.contains("_ms"),
                "a timing reaches a customer-visible string:\n  {l}"
            );
        }
    }
}

/// The OpenAPI document is what a customer integration reads. `/ops/*` is not part of the product.
#[test]
fn ops_routes_are_absent_from_the_openapi_document() {
    let app = read("rust/fxradar-serve/src/app.rs");
    let start = app.find("struct ApiDoc").expect("ApiDoc");
    let doc = &app[start.saturating_sub(2000)..start];
    assert!(
        !doc.contains("ops::"),
        "an /ops route is registered in the OpenAPI paths list"
    );
}

/// The operator page is server-rendered and its markup never enters the widget bundle.
#[test]
fn the_operator_page_lives_only_in_the_ops_module() {
    let ops = read("rust/fxradar-serve/src/ops.rs");
    assert!(
        ops.contains("Prompt economics"),
        "the panel exists in ops.rs"
    );
    for other in [
        "rust/fxradar-serve/static/avatar.html",
        "rust/fxradar-serve/static/cards.js",
    ] {
        assert!(
            !read(other).contains("Prompt economics"),
            "an operator panel leaked into {other}"
        );
    }
}
