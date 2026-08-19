//! Phase-24 service-layer tests: keys (401/403/429), tier enforcement, webhooks + signed
//! deliveries, dead-receiver give-up, idempotent alerts, Stripe signature, docs/metrics/widget.
//! The engine is not needed for these (AppState.engine = None → /api/score answers 503 AFTER the
//! key checks, which is what we assert on); the gated engine path is covered by tests/engine.rs.

use axum::extract::State;
use axum::http::HeaderMap;
use axum::routing::post;
use axum::Router;
use fxradar_serve::alerts::{self, AlertEngine, DeliveryConfig, Source};
use fxradar_serve::app::{build_router, AppState, SelftestStatus};
use fxradar_serve::store::{Store, Tier};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::Duration;

fn scratch_dir(name: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("fxr_svc_{}_{}", name, std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

fn selftest_status() -> SelftestStatus {
    SelftestStatus {
        status: "skipped".into(),
        goldens: 0,
        at_unix: 0,
        worst: vec![],
    }
}

/// Spin up the full router on an ephemeral port; returns (base_url, store).
async fn spawn_app(
    data_dir: PathBuf,
    per_min: u32,
    stripe_secret: Option<&str>,
) -> (String, Store) {
    let store = Store::open_in_memory().unwrap();
    let state = AppState::new(
        None,
        store.clone(),
        data_dir,
        selftest_status(),
        per_min,
        stripe_secret.map(|s| s.to_string()),
    );
    let app = build_router(state);
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    (format!("http://{addr}"), store)
}

#[derive(Clone, Default)]
struct Received {
    hits: Arc<Mutex<Vec<(HeaderMap, String)>>>,
}

/// A tiny receiver that records every POST (headers + body) and answers 200.
async fn spawn_receiver() -> (String, Received) {
    let rec = Received::default();
    let app = Router::new()
        .route(
            "/hook",
            post(
                |State(r): State<Received>, headers: HeaderMap, body: String| async move {
                    r.hits.lock().unwrap().push((headers, body));
                    "ok"
                },
            ),
        )
        .with_state(rec.clone());
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr: SocketAddr = listener.local_addr().unwrap();
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    (format!("http://{addr}/hook"), rec)
}

fn static_source(rows: Arc<Mutex<BTreeMap<String, Value>>>) -> Source {
    Arc::new(move || Ok(rows.lock().unwrap().clone()))
}

fn row(regime: &str, anomaly_pct: f64, agreement: Option<i64>) -> Value {
    let mut v = json!({"date": "2026-08-17", "regime": regime, "change_risk_5d": 0.0134,
        "anomaly_pct": anomaly_pct, "risk_lo": 0.008, "risk_hi": 0.021});
    if let Some(a) = agreement {
        v["agreement"] = json!(a);
    }
    v
}

async fn wait_until(mut f: impl FnMut() -> bool, max: Duration) -> bool {
    let t0 = std::time::Instant::now();
    while t0.elapsed() < max {
        if f() {
            return true;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    f()
}

// ---------------------------------------------------------------------------------------------

#[tokio::test]
async fn keys_401_403_429_and_public_routes_stay_open() {
    let dir = scratch_dir("keys");
    let (base, store) = spawn_app(dir, 3, None).await;
    let c = reqwest::Client::new();
    // public routes: no key needed
    let h = c.get(format!("{base}/api/health")).send().await.unwrap();
    assert_eq!(h.status(), 200);
    let hj: Value = h.json().await.unwrap();
    assert_eq!(hj["selftest"]["status"], "skipped");
    // regimes.parquet absent in the scratch dir → 503 (not 401): still public
    let r = c
        .get(format!("{base}/api/regimes/EURUSD"))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 503);
    // keyed route without key / with bad key → 401
    let r = c
        .post(format!("{base}/api/score"))
        .json(&json!({}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
    let r = c
        .post(format!("{base}/api/score"))
        .header("X-API-Key", "fxr_not_a_key")
        .json(&json!({}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
    let body: Value = r.json().await.unwrap();
    assert!(body["error"]
        .as_str()
        .unwrap()
        .contains("unknown or revoked"));
    // free key → 403 on paid routes
    let (free_key, _) = store.issue_key("free", Tier::Free).unwrap();
    let r = c
        .get(format!("{base}/api/webhooks"))
        .header("X-API-Key", &free_key)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 403);
    // pro key → allowed (webhooks list = [])
    let (pro_key, pro_rec) = store.issue_key("pro", Tier::Pro).unwrap();
    let r = c
        .get(format!("{base}/api/webhooks"))
        .header("X-API-Key", &pro_key)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 200);
    assert_eq!(r.json::<Value>().await.unwrap(), json!([]));
    // rate limit: 3/min → 2 more ok, the 4th is 429 with Retry-After
    for _ in 0..2 {
        let r = c
            .get(format!("{base}/api/webhooks"))
            .header("X-API-Key", &pro_key)
            .send()
            .await
            .unwrap();
        assert_eq!(r.status(), 200);
    }
    let r = c
        .get(format!("{base}/api/webhooks"))
        .header("X-API-Key", &pro_key)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 429);
    assert!(r.headers().get("retry-after").is_some());
    // revoked → 401
    store.revoke(&pro_rec.key_hash[..10]).unwrap();
    let r = c
        .get(format!("{base}/api/webhooks"))
        .header("X-API-Key", &pro_key)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
    // partner key reaches /api/score; without an engine the handler answers 503 (auth passed)
    let (partner_key, _) = store.issue_key("partner", Tier::Partner).unwrap();
    let r = c
        .post(format!("{base}/api/score"))
        .header("X-API-Key", &partner_key)
        .json(&json!({"pair": "EURUSD", "windows": []}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 503);
    // stripe route without secret → 503; docs, openapi, metrics, widget all public
    let r = c
        .post(format!("{base}/api/stripe/webhook"))
        .body("{}")
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 503);
    let r = c.get(format!("{base}/docs/")).send().await.unwrap();
    assert_eq!(r.status(), 200);
    assert!(r.text().await.unwrap().to_lowercase().contains("swagger"));
    let r = c
        .get(format!("{base}/api-docs/openapi.json"))
        .send()
        .await
        .unwrap();
    let spec: Value = r.json().await.unwrap();
    for p in [
        "/api/health",
        "/api/regimes/{pair}",
        "/api/score",
        "/api/treasury",
        "/api/webhooks",
        "/api/webhooks/{id}",
        "/api/stripe/webhook",
        "/metrics",
        "/widget.js",
    ] {
        assert!(spec["paths"].get(p).is_some(), "missing {p} in openapi");
    }
    assert!(spec["components"]["securitySchemes"]["api_key"].is_object());
    let r = c.get(format!("{base}/metrics")).send().await.unwrap();
    let text = r.text().await.unwrap();
    assert!(text.contains("http_requests_total"), "{text}");
    assert!(text.contains("http_request_duration_seconds"), "{text}");
    let r = c.get(format!("{base}/widget.js")).send().await.unwrap();
    assert!(r.headers()["content-type"]
        .to_str()
        .unwrap()
        .contains("javascript"));
    let js = r.text().await.unwrap();
    assert!(js.contains("/api/regimes/") && js.contains("not investment advice"));
    let r = c.get(format!("{base}/widget")).send().await.unwrap();
    assert!(r.text().await.unwrap().contains("widget.js"));
}

#[tokio::test]
async fn treasury_route_reads_artifact_or_404() {
    let dir = scratch_dir("treasury");
    let (base, store) = spawn_app(dir.clone(), 60, None).await;
    let (key, _) = store.issue_key("t", Tier::Pro).unwrap();
    let c = reqwest::Client::new();
    let r = c
        .get(format!("{base}/api/treasury"))
        .header("X-API-Key", &key)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 404);
    std::fs::write(
        dir.join("treasury_risk.json"),
        json!({"generated_at_utc": "x", "levels": [0.95, 0.99], "horizon_days": 5,
            "pairs": {"EURUSD": {"current_regime": "calm",
                "table": {"calm": {"var_95": 0.01, "es_95": 0.0123, "var_99": 0.02, "es_99": 0.03}}}}})
        .to_string(),
    )
    .unwrap();
    let r = c
        .get(format!(
            "{base}/api/treasury?pair=EURUSD&amount=800000&weeks=2&level=0.99"
        ))
        .header("X-API-Key", &key)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 200);
    let v: Value = r.json().await.unwrap();
    assert_eq!(v["disclaimer"], "Educational tool. Not investment advice.");
    let es = v["calc"]["es_notional"].as_f64().unwrap();
    assert!((es - 800_000.0 * 0.03 * 2f64.sqrt()).abs() < 1e-6);
    let r = c
        .get(format!("{base}/api/treasury?pair=EURUSD&weeks=99"))
        .header("X-API-Key", &key)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 400);
}

#[tokio::test]
async fn webhooks_register_and_alerts_are_signed_and_idempotent() {
    let dir = scratch_dir("alerts");
    std::fs::write(
        dir.join("events.csv"),
        "date,type,source\n2026-09-17,FOMC,federalreserve.gov\n",
    )
    .unwrap();
    let (base, store) = spawn_app(dir.clone(), 600, None).await;
    let (key, _) = store.issue_key("alerts", Tier::Pro).unwrap();
    let (hook_url, received) = spawn_receiver().await;
    let c = reqwest::Client::new();
    // bad inputs
    let r = c
        .post(format!("{base}/api/webhooks"))
        .header("X-API-Key", &key)
        .json(&json!({"url": "ftp://x"}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 400);
    let r = c
        .post(format!("{base}/api/webhooks"))
        .header("X-API-Key", &key)
        .json(&json!({"url": hook_url, "kind": "telegram"}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 400);
    // register a generic hook for EURUSD only
    let r = c
        .post(format!("{base}/api/webhooks"))
        .header("X-API-Key", &key)
        .json(&json!({"url": hook_url, "pairs": ["eurusd"]}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 201);
    let created: Value = r.json().await.unwrap();
    let secret = created["secret"].as_str().unwrap().to_string();
    let id = created["id"].as_i64().unwrap();
    assert!(secret.starts_with("whsec_"));
    assert_eq!(created["pairs"], json!(["EURUSD"]));
    // list hides the secret
    let r = c
        .get(format!("{base}/api/webhooks"))
        .header("X-API-Key", &key)
        .send()
        .await
        .unwrap();
    let listed: Value = r.json().await.unwrap();
    assert_eq!(listed[0]["id"], id);
    assert!(listed[0].get("secret").is_none());

    // alert engine against a synthetic state: calm EURUSD + calm USDCHF (not subscribed)
    let rows = Arc::new(Mutex::new(BTreeMap::from([
        ("EURUSD".to_string(), row("calm", 30.0, Some(2))),
        ("USDCHF".to_string(), row("calm", 30.0, Some(2))),
    ])));
    let engine = AlertEngine::new(
        store.clone(),
        static_source(rows.clone()),
        &dir,
        DeliveryConfig {
            max_tries: 5,
            base_backoff: Duration::from_millis(10),
            timeout: Duration::from_secs(5),
        },
    );
    engine.spawn_worker();
    // first poll: one regime_flip alert (initial sighting) for EURUSD only
    assert_eq!(engine.poll_once().unwrap(), 1);
    assert!(
        wait_until(
            || received.hits.lock().unwrap().len() == 1,
            Duration::from_secs(5)
        )
        .await
    );
    // same regime again (day two): exactly zero new alerts
    assert_eq!(engine.poll_once().unwrap(), 0);
    assert_eq!(engine.poll_once().unwrap(), 0);
    tokio::time::sleep(Duration::from_millis(100)).await;
    assert_eq!(received.hits.lock().unwrap().len(), 1);
    // verify the signature of the delivery exactly like tools/verify_webhook_sig.py does
    let (headers, body) = received.hits.lock().unwrap()[0].clone();
    let ts: u64 = headers["x-fxradar-timestamp"]
        .to_str()
        .unwrap()
        .parse()
        .unwrap();
    let sig = headers["x-fxradar-signature"].to_str().unwrap().to_string();
    assert!(alerts::verify(&secret, ts, body.as_bytes(), &sig));
    assert!(!alerts::verify("whsec_wrong", ts, body.as_bytes(), &sig));
    assert_eq!(headers["x-fxradar-event"].to_str().unwrap(), "regime_flip");
    let payload: Value = serde_json::from_str(&body).unwrap();
    assert_eq!(payload["pair"], "EURUSD");
    assert_eq!(payload["regime"], "calm");
    assert_eq!(payload["next_event"]["type"], "FOMC");
    assert!(payload["text"]
        .as_str()
        .unwrap()
        .ends_with("Educational tool. Not investment advice."));
    assert_eq!(
        payload["disclaimer"],
        "Educational tool. Not investment advice."
    );
    // regime flips + anomaly spikes + consensus 3/3 → three alerts, all delivered
    rows.lock()
        .unwrap()
        .insert("EURUSD".into(), row("crisis", 99.5, Some(3)));
    assert_eq!(engine.poll_once().unwrap(), 3);
    assert!(
        wait_until(
            || received.hits.lock().unwrap().len() == 4,
            Duration::from_secs(5)
        )
        .await
    );
    // and again nothing
    assert_eq!(engine.poll_once().unwrap(), 0);
    // USDCHF flips but nobody subscribed → 0 deliveries, no state written either
    rows.lock()
        .unwrap()
        .insert("USDCHF".into(), row("chop", 30.0, Some(2)));
    assert_eq!(engine.poll_once().unwrap(), 0);
    // delete → gone, second delete 404
    let r = c
        .delete(format!("{base}/api/webhooks/{id}"))
        .header("X-API-Key", &key)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 204);
    let r = c
        .delete(format!("{base}/api/webhooks/{id}"))
        .header("X-API-Key", &key)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 404);
    // the metrics surface saw the alerts
    let text = fxradar_serve::metrics::render();
    assert!(text.contains("alerts_fired_total"), "{text}");
    assert!(
        text.contains("alert_deliveries_total{outcome=\"ok\"}"),
        "{text}"
    );
}

#[tokio::test]
async fn dead_receiver_retries_then_gives_up() {
    let dir = scratch_dir("dead");
    let store = Store::open_in_memory().unwrap();
    let (_, rec) = store.issue_key("dead", Tier::Pro).unwrap();
    // a port nobody listens on: bind, read the port, drop
    let dead_port = {
        let l = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        l.local_addr().unwrap().port()
    };
    store
        .add_webhook(
            &rec.key_hash,
            &format!("http://127.0.0.1:{dead_port}/hook"),
            "slack",
            &[],
            None,
        )
        .unwrap();
    let rows = Arc::new(Mutex::new(BTreeMap::from([(
        "GBPUSD".to_string(),
        row("trend", 10.0, None),
    )])));
    let engine = AlertEngine::new(
        store,
        static_source(rows),
        &dir,
        DeliveryConfig {
            max_tries: 5,
            base_backoff: Duration::from_millis(5),
            timeout: Duration::from_millis(500),
        },
    );
    engine.spawn_worker();
    let before = fxradar_serve::metrics::render();
    let gave_up_before = count_metric(&before, "alert_deliveries_total{outcome=\"gave_up\"}");
    assert_eq!(engine.poll_once().unwrap(), 1);
    let ok = wait_until(
        || {
            count_metric(
                &fxradar_serve::metrics::render(),
                "alert_deliveries_total{outcome=\"gave_up\"}",
            ) > gave_up_before
        },
        Duration::from_secs(10),
    )
    .await;
    assert!(ok, "gave_up counter never incremented");
    let after = fxradar_serve::metrics::render();
    // 5 tries = 4 retries then give up
    assert!(
        count_metric(&after, "alert_deliveries_total{outcome=\"retry\"}") >= 4,
        "{after}"
    );
}

fn count_metric(text: &str, prefix: &str) -> u64 {
    text.lines()
        .find(|l| l.starts_with(prefix))
        .and_then(|l| l.rsplit(' ').next())
        .and_then(|v| v.parse::<f64>().ok())
        .map(|v| v as u64)
        .unwrap_or(0)
}

#[tokio::test]
async fn stripe_webhook_updates_tier_when_signed() {
    let dir = scratch_dir("stripe");
    let secret = "whsec_test_synthetic";
    let (base, store) = spawn_app(dir, 60, Some(secret)).await;
    let (key, rec) = store.issue_key("buyer", Tier::Free).unwrap();
    let prefix = &rec.key_hash[..12];
    let c = reqwest::Client::new();
    let payload = json!({"id": "evt_1", "type": "checkout.session.completed",
        "data": {"object": {"client_reference_id": prefix, "metadata": {"tier": "pro"}}}})
    .to_string();
    let now = fxradar_serve::store::now_unix();
    // bad signature → 400, tier unchanged
    let r = c
        .post(format!("{base}/api/stripe/webhook"))
        .header("Stripe-Signature", format!("t={now},v1=deadbeef"))
        .body(payload.clone())
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 400);
    assert_eq!(
        store.lookup_plaintext(&key).unwrap().unwrap().tier,
        Tier::Free
    );
    // good signature → 200, tier pro
    let sig = fxradar_serve::stripe::sign(secret, now, payload.as_bytes());
    let r = c
        .post(format!("{base}/api/stripe/webhook"))
        .header("Stripe-Signature", format!("t={now},v1={sig}"))
        .body(payload.clone())
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 200);
    let ack: Value = r.json().await.unwrap();
    assert_eq!(ack["applied"]["tier"], "pro");
    assert_eq!(
        store.lookup_plaintext(&key).unwrap().unwrap().tier,
        Tier::Pro
    );
    // cancel → free
    let payload = json!({"id": "evt_2", "type": "customer.subscription.deleted",
        "data": {"object": {"metadata": {"key_prefix": prefix}}}})
    .to_string();
    let sig = fxradar_serve::stripe::sign(secret, now, payload.as_bytes());
    let r = c
        .post(format!("{base}/api/stripe/webhook"))
        .header("Stripe-Signature", format!("t={now},v1={sig}"))
        .body(payload)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 200);
    assert_eq!(
        store.lookup_plaintext(&key).unwrap().unwrap().tier,
        Tier::Free
    );
    // stale timestamp → 400
    let payload = "{}".to_string();
    let old = now - 1000;
    let sig = fxradar_serve::stripe::sign(secret, old, payload.as_bytes());
    let r = c
        .post(format!("{base}/api/stripe/webhook"))
        .header("Stripe-Signature", format!("t={old},v1={sig}"))
        .body(payload)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 400);
}
