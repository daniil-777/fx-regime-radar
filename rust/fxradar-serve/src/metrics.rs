//! Prometheus metrics (phase 24): the golden signals for the service plus the alert engine.
//!
//! One global recorder is installed lazily (a process may only have one); `/metrics` renders it.
//! Metric names:
//!   http_requests_total{route,status}     http_request_duration_seconds{route}
//!   score_latency_seconds (engine only)   alerts_fired_total{trigger}
//!   alert_deliveries_total{outcome}       alert_poll_total{outcome}

use metrics_exporter_prometheus::{Matcher, PrometheusBuilder, PrometheusHandle};
use std::sync::OnceLock;

static HANDLE: OnceLock<PrometheusHandle> = OnceLock::new();

/// Install (once) and return the global Prometheus handle.
pub fn handle() -> &'static PrometheusHandle {
    HANDLE.get_or_init(|| {
        let builder = PrometheusBuilder::new()
            .set_buckets_for_metric(
                Matcher::Full("http_request_duration_seconds".into()),
                &[
                    0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5,
                ],
            )
            .and_then(|b| {
                b.set_buckets_for_metric(
                    Matcher::Full("score_latency_seconds".into()),
                    &[
                        0.0001, 0.00025, 0.0005, 0.001, 0.0025, 0.005, 0.01, 0.05, 0.1,
                    ],
                )
            })
            .and_then(|b| {
                b.set_buckets_for_metric(
                    Matcher::Full("avatar_brain_latency_seconds".into()),
                    &[
                        0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
                    ],
                )
            })
            .unwrap_or_else(|_| PrometheusBuilder::new());
        match builder.install_recorder() {
            Ok(h) => h,
            // a recorder already exists (tests): fall back to a fresh, unconnected handle
            Err(_) => PrometheusBuilder::new().build_recorder().handle(),
        }
    })
}

/// Render the current metrics in Prometheus text exposition format.
pub fn render() -> String {
    let h = handle();
    h.run_upkeep();
    h.render()
}

pub fn record_http(route: &str, status: u16, seconds: f64) {
    let route = route.to_string();
    metrics::counter!("http_requests_total", "route" => route.clone(), "status" => status.to_string())
        .increment(1);
    metrics::histogram!("http_request_duration_seconds", "route" => route).record(seconds);
}

pub fn record_score_latency(seconds: f64) {
    metrics::counter!("score_requests_total").increment(1);
    metrics::histogram!("score_latency_seconds").record(seconds);
}

pub fn alert_fired(trigger: &str) {
    metrics::counter!("alerts_fired_total", "trigger" => trigger.to_string()).increment(1);
}

/// outcome ∈ {"ok", "retry", "gave_up"}
pub fn alert_delivery(outcome: &str) {
    metrics::counter!("alert_deliveries_total", "outcome" => outcome.to_string()).increment(1);
}

pub fn alert_poll(outcome: &str) {
    metrics::counter!("alert_poll_total", "outcome" => outcome.to_string()).increment(1);
}

// ---- avatar (phase 35) ----------------------------------------------------------------------

/// source ∈ {"llm", "template", "refusal"}
pub fn avatar_request(source: &str) {
    metrics::counter!("avatar_requests_total", "source" => source.to_string()).increment(1);
}

/// kind ∈ {"direction", "advice", "off_topic", "not_in_pack"}
pub fn avatar_refusal(kind: &str) {
    metrics::counter!("avatar_refusals_total", "kind" => kind.to_string()).increment(1);
}

// ---- answer boards (phase 36/38) --------------------------------------------------------------

/// Which card was rendered as the primary of a board.
pub fn visual_render(component: &str) {
    metrics::counter!("visual_render_total", "component" => component.to_string()).increment(1);
}

/// A question was answered with no board at all — the null board is a first-class outcome, and
/// watching its rate is how you notice the registry going blind.
pub fn visual_null_board() {
    metrics::counter!("visual_null_board_total").increment(1);
}

// ---- precomputed answers (phase 40) ------------------------------------------------------------

/// path ∈ {"pack", "live"} — how the answer was produced.
pub fn answer_path(path: &str) {
    metrics::counter!("answer_path_total", "path" => path.to_string()).increment(1);
}

/// A pack was served although it was built under superseded rules; the stale badge went with it.
pub fn answer_pack_stale() {
    metrics::counter!("answer_pack_stale_total").increment(1);
}

/// outcome ∈ {"verbatim", "expanded", "ambiguous"} — what reference resolution did with a turn.
pub fn reference_resolution(outcome: &str) {
    metrics::counter!("reference_resolution_total", "outcome" => outcome.to_string()).increment(1);
}

/// Answer latency, labelled by path, so the pack and live tails can be read apart.
pub fn answer_latency(path: &str, seconds: f64) {
    metrics::histogram!("answer_latency_seconds", "path" => path.to_string()).record(seconds);
}

/// Which archive shape answered — so an unanswerable shape shows up as a gap, not as silence.
pub fn archive_answer(shape: &str) {
    metrics::counter!("archive_answer_total", "shape" => shape.to_string()).increment(1);
}

/// gate ∈ {"direction", "grounding"}
pub fn avatar_lint_rejection(gate: &str) {
    metrics::counter!("avatar_lint_rejections_total", "gate" => gate.to_string()).increment(1);
}

pub fn avatar_brain_latency(seconds: f64) {
    metrics::histogram!("avatar_brain_latency_seconds").record(seconds);
}

pub fn avatar_session() {
    metrics::counter!("avatar_sessions_total").increment(1);
}

/// Characters actually sent to the TTS vendor (browser-TTS fallback is free and uncounted).
pub fn avatar_tts_chars(n: u64) {
    metrics::counter!("avatar_tts_chars_total").increment(n);
}

/// Monotone-increasing total of avatar minutes. A gauge because the metrics crate's counters are
/// integer-only and minutes are fractional; it is only ever incremented.
pub fn avatar_minutes(minutes: f64) {
    metrics::gauge!("avatar_minutes_total").increment(minutes);
}
