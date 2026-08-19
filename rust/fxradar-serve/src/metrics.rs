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
