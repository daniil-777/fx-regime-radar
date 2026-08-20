//! Alert engine (phase 24): push the computed state to where users live.
//!
//! A background task polls the newest row per pair (from `data/regimes.parquet`), evaluates three
//! triggers per (key, pair) — regime flip, anomaly siren p>98, consensus 3/3 — against the
//! persisted `last_alerted` state (idempotent: one flip = one alert, same regime two days in a row
//! = nothing), and enqueues signed deliveries on a tokio queue. Delivery is at-least-once with
//! exponential backoff, at most `max_tries`, then it gives up loudly (metric + log). Nothing here
//! ever runs inside an HTTP handler, and no text contains a direction word (see the lint test).

use crate::metrics as m;
use crate::store::{Store, Webhook};
use hmac::{Hmac, Mac};
use serde_json::{json, Value};
use sha2::Sha256;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::sync::mpsc;
use tracing::{error, info, warn};

pub const DISCLAIMER: &str = "Educational tool. Not investment advice.";
pub const TRIGGER_REGIME_FLIP: &str = "regime_flip";
pub const TRIGGER_ANOMALY: &str = "anomaly";
pub const TRIGGER_CONSENSUS: &str = "consensus";
pub const TRIGGERS: [&str; 3] = [TRIGGER_REGIME_FLIP, TRIGGER_ANOMALY, TRIGGER_CONSENSUS];
pub const ANOMALY_PCT_THRESHOLD: f64 = 98.0;
pub const CONSENSUS_FULL: i64 = 3;

/// Direction words banned from every user-facing generated text (golden rule 5). The alert lint
/// test scans templates against this list, and the avatar output gate (phase 35) reuses it.
pub(crate) const DIRECTION_WORDS: [&str; 14] = [
    "rise", "fall", "up", "down", "buy", "sell", "long", "short", "target", "bullish", "bearish",
    "rally", "drop", "crash",
];

/// Every phrase that can appear in an alert text. The lint test scans these AND rendered samples.
pub const TEMPLATE_FRAGMENTS: [&str; 12] = [
    "FX Regime Radar · {pair} · {date}",
    "Trigger: regime changed to {regime}",
    "Trigger: anomaly siren at p{anomaly_pct} (threshold p98)",
    "Trigger: consensus 3/3 — HMM, BOCPD and the volatility rule agree",
    "Regime: {regime}",
    "Change risk (5d): {risk}% (interval {lo}%–{hi}%)",
    "Change risk (5d): {risk}%",
    "Change risk (5d): n/a",
    "Consensus: {consensus_text}",
    "Consensus: n/a",
    "Next scheduled event: {type} on {date} ({source})",
    "Next scheduled event: n/a",
];

// ---------------------------------------------------------------------------------------------
// state snapshot + triggers (pure)
// ---------------------------------------------------------------------------------------------

/// The slice of one pair's newest regimes row that alerts care about (all optional but regime).
#[derive(Debug, Clone, PartialEq)]
pub struct Snapshot {
    pub pair: String,
    pub date: String,
    pub regime: String,
    pub change_risk_5d: Option<f64>,
    pub risk_lo: Option<f64>,
    pub risk_hi: Option<f64>,
    pub anomaly_pct: Option<f64>,
    pub agreement: Option<i64>,
    pub consensus_text: Option<String>,
}

fn num(v: &Value, k: &str) -> Option<f64> {
    v.get(k).and_then(|x| x.as_f64()).filter(|f| f.is_finite())
}

impl Snapshot {
    pub fn from_row(pair: &str, row: &Value) -> Snapshot {
        Snapshot {
            pair: pair.to_string(),
            date: row
                .get("date")
                .and_then(|d| d.as_str())
                .unwrap_or("n/a")
                .to_string(),
            regime: row
                .get("regime")
                .and_then(|r| r.as_str())
                .unwrap_or("unknown")
                .to_string(),
            change_risk_5d: num(row, "change_risk_5d"),
            risk_lo: num(row, "risk_lo"),
            risk_hi: num(row, "risk_hi"),
            anomaly_pct: num(row, "anomaly_pct"),
            agreement: row
                .get("agreement")
                .and_then(|a| a.as_i64().or_else(|| a.as_f64().map(|f| f.round() as i64))),
            consensus_text: row
                .get("consensus_text")
                .and_then(|c| c.as_str())
                .map(|s| s.to_string()),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TriggerState {
    pub trigger: &'static str,
    /// Value to persist as the new last-alerted state for this trigger.
    pub value: String,
    /// True when an alert must be sent now.
    pub fired: bool,
}

/// Evaluate all triggers for one (key, pair). `last(trigger)` returns the persisted value.
pub fn evaluate(snap: &Snapshot, last: impl Fn(&str) -> Option<String>) -> Vec<TriggerState> {
    let mut out = Vec::with_capacity(3);
    // 1) regime flip: first sighting counts as the initial notification; same regime again = silent
    let prev = last(TRIGGER_REGIME_FLIP);
    out.push(TriggerState {
        trigger: TRIGGER_REGIME_FLIP,
        fired: prev.as_deref() != Some(snap.regime.as_str()),
        value: snap.regime.clone(),
    });
    // 2) anomaly siren: fire on the edge into p>98, silent while it stays there
    let high = snap
        .anomaly_pct
        .map(|p| p > ANOMALY_PCT_THRESHOLD)
        .unwrap_or(false);
    let value = if high { "high" } else { "normal" };
    out.push(TriggerState {
        trigger: TRIGGER_ANOMALY,
        fired: high && last(TRIGGER_ANOMALY).as_deref() != Some("high"),
        value: value.to_string(),
    });
    // 3) consensus 3/3 (column may be absent → never fires)
    let full = snap.agreement == Some(CONSENSUS_FULL);
    let value = if full { "3" } else { "lt3" };
    out.push(TriggerState {
        trigger: TRIGGER_CONSENSUS,
        fired: full && last(TRIGGER_CONSENSUS).as_deref() != Some("3"),
        value: value.to_string(),
    });
    out
}

// ---------------------------------------------------------------------------------------------
// next scheduled event (data/events.csv: date,type,source)
// ---------------------------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct NextEvent {
    pub date: String,
    #[serde(rename = "type")]
    pub kind: String,
    pub source: String,
}

/// First row of events.csv whose date is on/after `today` (ISO strings compare lexically).
pub fn next_event(path: &Path, today: &str) -> Option<NextEvent> {
    let raw = std::fs::read_to_string(path).ok()?;
    let mut lines = raw.lines();
    let header: Vec<&str> = lines.next()?.split(',').map(|s| s.trim()).collect();
    let idx = |name: &str| header.iter().position(|h| *h == name);
    let (di, ti, si) = (idx("date")?, idx("type")?, idx("source"));
    let mut best: Option<NextEvent> = None;
    for line in lines {
        let cols: Vec<&str> = line.split(',').map(|s| s.trim()).collect();
        let Some(date) = cols.get(di) else { continue };
        let date = &date[..date.len().min(10)];
        if date < today {
            continue;
        }
        let ev = NextEvent {
            date: date.to_string(),
            kind: cols.get(ti).unwrap_or(&"").to_string(),
            source: si.and_then(|i| cols.get(i)).unwrap_or(&"").to_string(),
        };
        if best.as_ref().map(|b| ev.date < b.date).unwrap_or(true) {
            best = Some(ev);
        }
    }
    best
}

// ---------------------------------------------------------------------------------------------
// text template + payload
// ---------------------------------------------------------------------------------------------

fn pct(x: f64) -> String {
    format!("{:.1}", x * 100.0)
}

/// Human text for one alert. Ends with the disclaimer, always.
pub fn render_text(trigger: &str, snap: &Snapshot, next: Option<&NextEvent>) -> String {
    let trigger_line = match trigger {
        TRIGGER_REGIME_FLIP => format!("Trigger: regime changed to {}", snap.regime),
        TRIGGER_ANOMALY => format!(
            "Trigger: anomaly siren at p{} (threshold p98)",
            snap.anomaly_pct
                .map(|p| format!("{p:.0}"))
                .unwrap_or("n/a".into())
        ),
        _ => "Trigger: consensus 3/3 — HMM, BOCPD and the volatility rule agree".to_string(),
    };
    let risk_line = match (snap.change_risk_5d, snap.risk_lo, snap.risk_hi) {
        (Some(r), Some(lo), Some(hi)) => format!(
            "Change risk (5d): {}% (interval {}%–{}%)",
            pct(r),
            pct(lo),
            pct(hi)
        ),
        (Some(r), _, _) => format!("Change risk (5d): {}%", pct(r)),
        _ => "Change risk (5d): n/a".to_string(),
    };
    let consensus_line = match &snap.consensus_text {
        Some(t) if !t.is_empty() => format!("Consensus: {t}"),
        _ => "Consensus: n/a".to_string(),
    };
    let event_line = match next {
        Some(e) => format!(
            "Next scheduled event: {} on {} ({})",
            e.kind, e.date, e.source
        ),
        None => "Next scheduled event: n/a".to_string(),
    };
    format!(
        "FX Regime Radar · {} · {}\n{}\nRegime: {}\n{}\n{}\n{}\n{}",
        snap.pair,
        snap.date,
        trigger_line,
        snap.regime,
        risk_line,
        consensus_line,
        event_line,
        DISCLAIMER
    )
}

/// The generic JSON payload (what a `kind=generic` receiver gets; Slack/Telegram get `text` only).
pub fn build_payload(trigger: &str, snap: &Snapshot, next: Option<&NextEvent>) -> Value {
    json!({
        "event": trigger,
        "pair": snap.pair,
        "date": snap.date,
        "regime": snap.regime,
        "change_risk_5d": snap.change_risk_5d,
        "risk_lo": snap.risk_lo,
        "risk_hi": snap.risk_hi,
        "anomaly_pct": snap.anomaly_pct,
        "agreement": snap.agreement,
        "consensus_text": snap.consensus_text,
        "next_event": next,
        "text": render_text(trigger, snap, next),
        "disclaimer": DISCLAIMER,
        "sent_at_utc": crate::store::now_iso(),
        "source": "fxradar-serve",
    })
}

/// Body actually POSTed for a webhook kind.
pub fn body_for(kind: &str, chat_id: Option<&str>, payload: &Value) -> String {
    let text = payload
        .get("text")
        .and_then(|t| t.as_str())
        .unwrap_or(DISCLAIMER);
    match kind {
        "slack" => json!({ "text": text }).to_string(),
        "telegram" => json!({
            "chat_id": chat_id.unwrap_or(""),
            "text": text,
            "disable_web_page_preview": true,
        })
        .to_string(),
        _ => payload.to_string(),
    }
}

/// HMAC-SHA256 over `"{timestamp}.{body}"`, hex. Header: `X-FXRadar-Signature: sha256=<hex>`.
pub fn sign(secret: &str, timestamp: u64, body: &[u8]) -> String {
    let mut mac =
        Hmac::<Sha256>::new_from_slice(secret.as_bytes()).expect("hmac accepts any key length");
    mac.update(timestamp.to_string().as_bytes());
    mac.update(b".");
    mac.update(body);
    hex::encode(mac.finalize().into_bytes())
}

/// Verify a received signature (used by tests; `tools/verify_webhook_sig.py` is the Python twin).
pub fn verify(secret: &str, timestamp: u64, body: &[u8], header_value: &str) -> bool {
    let Some(hexsig) = header_value.strip_prefix("sha256=") else {
        return false;
    };
    let expected = sign(secret, timestamp, body);
    hexsig.len() == expected.len()
        && hexsig
            .bytes()
            .zip(expected.bytes())
            .fold(0u8, |acc, (a, b)| acc | (a ^ b))
            == 0
}

// ---------------------------------------------------------------------------------------------
// delivery queue
// ---------------------------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct DeliveryConfig {
    pub max_tries: u32,
    pub base_backoff: Duration,
    pub timeout: Duration,
}

impl Default for DeliveryConfig {
    fn default() -> Self {
        DeliveryConfig {
            max_tries: 5,
            base_backoff: Duration::from_secs(2),
            timeout: Duration::from_secs(10),
        }
    }
}

#[derive(Debug, Clone)]
pub struct Delivery {
    pub webhook: Webhook,
    pub event: String,
    pub body: String,
}

/// POST one delivery with retries; returns true on success. Never called from a handler.
pub async fn deliver_with_retry(
    client: &reqwest::Client,
    d: Delivery,
    cfg: &DeliveryConfig,
) -> bool {
    for attempt in 1..=cfg.max_tries.max(1) {
        let ts = crate::store::now_unix();
        let sig = sign(&d.webhook.secret, ts, d.body.as_bytes());
        let res = client
            .post(&d.webhook.url)
            .header("Content-Type", "application/json")
            .header(
                "User-Agent",
                concat!("fxradar-serve/", env!("CARGO_PKG_VERSION")),
            )
            .header("X-FXRadar-Signature", format!("sha256={sig}"))
            .header("X-FXRadar-Timestamp", ts.to_string())
            .header("X-FXRadar-Event", &d.event)
            .header("X-FXRadar-Webhook-Id", d.webhook.id.to_string())
            .timeout(cfg.timeout)
            .body(d.body.clone())
            .send()
            .await;
        match res {
            Ok(r) if r.status().is_success() => {
                m::alert_delivery("ok");
                info!(webhook = d.webhook.id, attempt, event = %d.event, "alert delivered");
                return true;
            }
            Ok(r) => {
                warn!(webhook = d.webhook.id, attempt, status = %r.status(), "alert delivery rejected");
            }
            Err(e) => {
                warn!(webhook = d.webhook.id, attempt, error = %e, "alert delivery failed");
            }
        }
        if attempt < cfg.max_tries {
            m::alert_delivery("retry");
            let backoff = cfg.base_backoff * 2u32.saturating_pow(attempt - 1);
            tokio::time::sleep(backoff).await;
        }
    }
    m::alert_delivery("gave_up");
    error!(webhook = d.webhook.id, event = %d.event, tries = cfg.max_tries, "alert delivery GAVE UP");
    false
}

/// Where the newest-row-per-pair state comes from (parquet in prod, a closure in tests).
pub type Source = Arc<dyn Fn() -> Result<BTreeMap<String, Value>, String> + Send + Sync>;

pub fn parquet_source(path: PathBuf) -> Source {
    Arc::new(move || crate::state_store::latest_regimes(&path).map_err(|e| e.to_string()))
}

pub struct AlertEngine {
    store: Store,
    source: Source,
    events_csv: PathBuf,
    client: reqwest::Client,
    cfg: DeliveryConfig,
    tx: mpsc::UnboundedSender<Delivery>,
    rx: Mutex<Option<mpsc::UnboundedReceiver<Delivery>>>,
}

impl AlertEngine {
    pub fn new(store: Store, source: Source, data_dir: &Path, cfg: DeliveryConfig) -> Arc<Self> {
        let _ = m::handle();
        let (tx, rx) = mpsc::unbounded_channel();
        Arc::new(AlertEngine {
            store,
            source,
            events_csv: data_dir.join("events.csv"),
            client: reqwest::Client::new(),
            cfg,
            tx,
            rx: Mutex::new(Some(rx)),
        })
    }

    /// Start the delivery worker (once). Each queued delivery runs its own retry task so one dead
    /// receiver never delays the others.
    pub fn spawn_worker(self: &Arc<Self>) {
        let Some(mut rx) = self.rx.lock().ok().and_then(|mut g| g.take()) else {
            return;
        };
        let me = Arc::clone(self);
        tokio::spawn(async move {
            while let Some(d) = rx.recv().await {
                let client = me.client.clone();
                let cfg = me.cfg.clone();
                tokio::spawn(async move {
                    deliver_with_retry(&client, d, &cfg).await;
                });
            }
        });
    }

    /// Poll loop: evaluate at start-up, then every `interval`.
    pub async fn run(self: Arc<Self>, interval: Duration) {
        loop {
            match self.poll_once() {
                Ok(n) => {
                    m::alert_poll("ok");
                    if n > 0 {
                        info!(alerts = n, "alert poll fired alerts");
                    }
                }
                Err(e) => {
                    m::alert_poll("error");
                    warn!(error = %e, "alert poll failed");
                }
            }
            tokio::time::sleep(interval).await;
        }
    }

    /// One evaluation pass; returns how many alerts were fired (each may fan out to several hooks).
    pub fn poll_once(&self) -> Result<usize, String> {
        let latest = (self.source)()?;
        let hooks = self.store.list_webhooks(None).map_err(|e| e.to_string())?;
        if hooks.is_empty() {
            return Ok(0);
        }
        let mut by_key: BTreeMap<String, Vec<Webhook>> = BTreeMap::new();
        for h in hooks {
            by_key.entry(h.key_hash.clone()).or_default().push(h);
        }
        let today = latest
            .values()
            .filter_map(|r| r.get("date").and_then(|d| d.as_str()))
            .max()
            .unwrap_or("")
            .to_string();
        let next = next_event(&self.events_csv, &today);
        let mut fired_total = 0usize;
        for (key_hash, hooks) in by_key {
            let rec = self
                .store
                .lookup_hash(&key_hash)
                .map_err(|e| e.to_string())?;
            let Some(rec) = rec else { continue };
            if rec.revoked || !rec.tier.is_paid() {
                continue;
            }
            for (pair, row) in &latest {
                let subs: Vec<&Webhook> = hooks
                    .iter()
                    .filter(|h| h.pairs.is_empty() || h.pairs.iter().any(|p| p == pair))
                    .collect();
                if subs.is_empty() {
                    continue;
                }
                let snap = Snapshot::from_row(pair, row);
                let states = evaluate(&snap, |t| {
                    self.store.last_alerted(&key_hash, pair, t).ok().flatten()
                });
                for st in states {
                    if st.fired {
                        m::alert_fired(st.trigger);
                        fired_total += 1;
                        let payload = build_payload(st.trigger, &snap, next.as_ref());
                        for h in &subs {
                            let d = Delivery {
                                webhook: (*h).clone(),
                                event: st.trigger.to_string(),
                                body: body_for(&h.kind, h.chat_id.as_deref(), &payload),
                            };
                            if self.tx.send(d).is_err() {
                                warn!("alert queue closed; delivery dropped");
                            }
                        }
                    }
                    self.store
                        .set_last_alerted(&key_hash, pair, st.trigger, &st.value)
                        .map_err(|e| e.to_string())?;
                }
            }
        }
        Ok(fired_total)
    }
}

// ---------------------------------------------------------------------------------------------
// tests
// ---------------------------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn words(s: &str) -> Vec<String> {
        s.split(|c: char| !c.is_alphanumeric())
            .filter(|w| !w.is_empty())
            .map(|w| w.to_ascii_lowercase())
            .collect()
    }

    fn assert_no_direction(text: &str) {
        for w in words(text) {
            assert!(
                !DIRECTION_WORDS.contains(&w.as_str()),
                "direction word {w:?} in alert text: {text:?}"
            );
        }
    }

    fn sample() -> Snapshot {
        Snapshot {
            pair: "EURUSD".into(),
            date: "2026-08-17".into(),
            regime: "chop".into(),
            change_risk_5d: Some(0.21),
            risk_lo: Some(0.12),
            risk_hi: Some(0.33),
            anomaly_pct: Some(99.2),
            agreement: Some(3),
            consensus_text: Some("3/3 models agree on chop".into()),
        }
    }

    #[test]
    fn templates_have_no_direction_words_and_end_with_disclaimer() {
        for frag in TEMPLATE_FRAGMENTS {
            assert_no_direction(frag);
        }
        let ev = NextEvent {
            date: "2026-09-17".into(),
            kind: "FOMC".into(),
            source: "federalreserve.gov".into(),
        };
        for regime in ["calm", "trend", "chop", "crisis"] {
            let mut s = sample();
            s.regime = regime.into();
            for t in TRIGGERS {
                for next in [Some(&ev), None] {
                    let text = render_text(t, &s, next);
                    assert_no_direction(&text);
                    assert!(text.ends_with(DISCLAIMER), "{text}");
                    let p = build_payload(t, &s, next);
                    assert_eq!(p["disclaimer"], DISCLAIMER);
                    for kind in ["generic", "slack", "telegram"] {
                        let body = body_for(kind, Some("42"), &p);
                        assert!(body.contains("Educational tool"));
                        assert_no_direction(&body);
                    }
                }
            }
        }
        // a sparse row (no interval, no consensus) also renders cleanly
        let sparse = Snapshot {
            risk_lo: None,
            risk_hi: None,
            consensus_text: None,
            anomaly_pct: None,
            agreement: None,
            ..sample()
        };
        let text = render_text(TRIGGER_REGIME_FLIP, &sparse, None);
        assert!(text.contains("Change risk (5d): 21.0%"));
        assert!(text.contains("Consensus: n/a"));
        assert!(text.contains("Next scheduled event: n/a"));
    }

    #[test]
    fn triggers_are_edge_detectors() {
        let s = sample();
        let none = |_: &str| None::<String>;
        let first = evaluate(&s, none);
        assert!(first.iter().all(|t| t.fired), "{first:?}");
        // same state again → nothing fires, values unchanged
        let mut mem: HashMap<&str, String> =
            first.iter().map(|t| (t.trigger, t.value.clone())).collect();
        let again = evaluate(&s, |t| mem.get(t).cloned());
        assert!(again.iter().all(|t| !t.fired), "{again:?}");
        // regime changes → only the flip fires
        let mut s2 = s.clone();
        s2.regime = "crisis".into();
        let third = evaluate(&s2, |t| mem.get(t).cloned());
        let fired: Vec<&str> = third
            .iter()
            .filter(|t| t.fired)
            .map(|t| t.trigger)
            .collect();
        assert_eq!(fired, vec![TRIGGER_REGIME_FLIP]);
        for t in &third {
            mem.insert(t.trigger, t.value.clone());
        }
        // anomaly drops below then comes back → anomaly fires once more
        let mut s3 = s2.clone();
        s3.anomaly_pct = Some(50.0);
        for t in evaluate(&s3, |t| mem.get(t).cloned()) {
            assert!(!t.fired);
            mem.insert(t.trigger, t.value);
        }
        let s4 = s2.clone();
        let fired: Vec<&str> = evaluate(&s4, |t| mem.get(t).cloned())
            .iter()
            .filter(|t| t.fired)
            .map(|t| t.trigger)
            .collect();
        assert_eq!(fired, vec![TRIGGER_ANOMALY]);
        // absent agreement column never fires consensus
        let mut s5 = sample();
        s5.agreement = None;
        let c = evaluate(&s5, none)
            .into_iter()
            .find(|t| t.trigger == TRIGGER_CONSENSUS)
            .unwrap();
        assert!(!c.fired);
    }

    #[test]
    fn snapshot_from_sparse_row() {
        let row = json!({"date": "2026-08-17", "regime": "calm", "change_risk_5d": 0.0134,
            "anomaly_pct": 24.9, "agreement": 2.0});
        let s = Snapshot::from_row("USDCHF", &row);
        assert_eq!(s.regime, "calm");
        assert_eq!(s.agreement, Some(2));
        assert!(s.risk_lo.is_none());
    }

    #[test]
    fn signature_roundtrip() {
        let body = br#"{"event":"regime_flip"}"#;
        let sig = sign("whsec_x", 1_700_000_000, body);
        assert!(verify(
            "whsec_x",
            1_700_000_000,
            body,
            &format!("sha256={sig}")
        ));
        assert!(!verify(
            "whsec_y",
            1_700_000_000,
            body,
            &format!("sha256={sig}")
        ));
        assert!(!verify(
            "whsec_x",
            1_700_000_001,
            body,
            &format!("sha256={sig}")
        ));
        assert!(!verify("whsec_x", 1_700_000_000, body, &sig));
    }

    #[test]
    fn next_event_reads_first_future_row() {
        let dir = std::env::temp_dir().join(format!("fxr_events_{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let p = dir.join("events.csv");
        std::fs::write(
            &p,
            "date,type,source\n2026-08-01,NFP,bls.gov\n2026-09-17,FOMC,fed\n2026-09-10,ECB,ecb\n",
        )
        .unwrap();
        let ev = next_event(&p, "2026-08-17").unwrap();
        assert_eq!(ev.kind, "ECB");
        assert_eq!(ev.date, "2026-09-10");
        assert!(next_event(&p, "2027-01-01").is_none());
        assert!(next_event(&dir.join("missing.csv"), "2026-01-01").is_none());
        let _ = std::fs::remove_dir_all(&dir);
    }
}
