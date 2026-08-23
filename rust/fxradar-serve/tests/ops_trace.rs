//! Phase 43: the operator trace surface — access control, recording, replay and promotion.
//!
//! The most valuable test in this file is `replay_agrees_with_the_live_chain`. The replay path and
//! the brain handler are two pieces of code making the same routing decisions, and the day they
//! disagree is the day replay starts giving confident wrong answers to someone debugging a real
//! complaint. That is a worse failure than having no replay at all, so the agreement is asserted
//! rather than assumed.

use fxradar_serve::app::{build_router, AppState, SelftestStatus};
use fxradar_serve::avatar::AvatarCfg;
use fxradar_serve::store::Store;
use fxradar_serve::trace::TraceCfg;
use serde_json::{json, Value};
use std::path::{Path, PathBuf};

const REF_DIRECTION: &str = "REFUSAL-DIRECTION: the radar never models direction.";
const REF_ADVICE: &str = "REFUSAL-ADVICE: educational tool, not investment advice.";
const REF_OFF_TOPIC: &str = "REFUSAL-OFFTOPIC: I only speak from the published numbers.";
const REF_NOT_IN_PACK: &str = "REFUSAL-NOTINPACK: I don't have that number and won't guess.";
const SIREN_ANSWER: &str = "The siren ranks today against calm history from 0 to 100.";
const OPS_KEY: &str = "ops_test_key_9f2";

fn scratch_dir(name: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("fxr_ops_{}_{}", name, std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

fn write_pack(root: &Path) {
    let pack = json!({
        "generated_at_utc": "2026-08-19T06:00:00Z",
        "universe": "fx",
        "data_through": "2026-08-18",
        "system_prompt_version": "v1",
        "disclosure": "I am the radar's AI presenter — a computer-generated voice, not a person.",
        "greeting": "As of the 2026-08-18 close, EURUSD is calm.",
        "pairs": {"EURUSD": {"regime": "calm", "change_risk_5d": 0.01}},
        "events": [], "treasury": {}, "ledger": {}, "drift": {"model_stale": false},
        "refusals": {
            "direction": REF_DIRECTION, "advice": REF_ADVICE,
            "off_topic": REF_OFF_TOPIC, "not_in_pack": REF_NOT_IN_PACK,
        },
        "faq": [{"q": "What is the siren?", "keywords": ["siren"], "answer": SIREN_ANSWER}],
        "markets": {"fx": {"label": "FX majors", "data_through": "2026-08-18", "pairs": {
            "EURUSD": {"label": "EUR/USD", "regime": "calm", "regime_prob": 0.99,
                       "days_in_regime": 12, "change_risk_5d": 0.01, "risk_lo": 0.0,
                       "risk_hi": 0.51, "anomaly_pct": 73.0, "agreement": 0}}}},
        "allowed_numbers": ["0", "0.01", "0.51", "0.99", "12", "73", "100", "2026", "8", "18"],
        "knowledge_pack": "docs/avatar_knowledge.md",
    });
    std::fs::create_dir_all(root.join("data")).unwrap();
    std::fs::create_dir_all(root.join("docs")).unwrap();
    std::fs::write(
        root.join("data/avatar_context.json"),
        serde_json::to_vec_pretty(&pack).unwrap(),
    )
    .unwrap();
    std::fs::write(root.join("docs/avatar_knowledge.md"), "# test fixture\n").unwrap();
}

fn state_for(root: &Path, ops_key: Option<&str>) -> AppState {
    AppState::new(
        None,
        Store::open_in_memory().unwrap(),
        root.join("data"),
        SelftestStatus {
            status: "skipped".into(),
            goldens: 0,
            at_unix: 0,
            worst: vec![],
        },
        60,
        None,
    )
    .with_avatar(AvatarCfg {
        enabled: true,
        brain_token: Some("brt_test".into()),
        test_hook: true,
        ..AvatarCfg::default()
    })
    .with_traces(TraceCfg {
        retention_secs: 3600,
        capacity: 50,
        operator_key: ops_key.map(str::to_string),
    })
}

async fn spawn(root: &Path, ops_key: Option<&str>) -> String {
    let app = build_router(state_for(root, ops_key));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    format!("http://{addr}")
}

async fn ask(base: &str, question: &str) -> Value {
    reqwest::Client::new()
        .post(format!("{base}/avatar/brain"))
        .header("X-Avatar-Token", "brt_test")
        .json(&json!({
            "session_id": "s-ops",
            "messages": [{"role": "user", "content": question}],
        }))
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap()
}

// ---------------------------------------------------------------------------------------------

#[tokio::test]
async fn ops_routes_401_without_an_operator_key() {
    let root = scratch_dir("401");
    write_pack(&root);
    let base = spawn(&root, Some(OPS_KEY)).await;
    let client = reqwest::Client::new();
    for path in [
        "/ops/traces",
        "/ops/audit",
        "/ops/trace/anything",
        "/ops/trace/anything/json",
    ] {
        let r = client.get(format!("{base}{path}")).send().await.unwrap();
        assert_eq!(
            r.status(),
            401,
            "{path} must refuse an unauthenticated read"
        );
    }
    for path in ["/ops/trace/x/replay", "/ops/trace/x/promote"] {
        let r = client.post(format!("{base}{path}")).send().await.unwrap();
        assert_eq!(
            r.status(),
            401,
            "{path} must refuse an unauthenticated write"
        );
    }
    // A wrong key is not better than no key.
    let r = client
        .get(format!("{base}/ops/traces"))
        .header("X-Ops-Key", "not-the-key")
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
}

#[tokio::test]
async fn with_no_key_configured_the_surface_is_closed_to_everyone() {
    let root = scratch_dir("closed");
    write_pack(&root);
    let base = spawn(&root, None).await;
    let r = reqwest::Client::new()
        .get(format!("{base}/ops/traces"))
        .header("X-Ops-Key", OPS_KEY)
        .send()
        .await
        .unwrap();
    assert_eq!(
        r.status(),
        401,
        "an unconfigured operator surface must fail shut, not open"
    );
}

#[tokio::test]
async fn a_turn_is_recorded_and_the_trace_shows_its_panels() {
    let root = scratch_dir("record");
    write_pack(&root);
    let base = spawn(&root, Some(OPS_KEY)).await;
    let answer = ask(&base, "will EURUSD rise tomorrow?").await;
    assert_eq!(answer["gate"], "refused:direction");
    // the customer response carries no operator identifier
    assert!(answer.get("trace_id").is_none());

    let client = reqwest::Client::new();
    let index: String = client
        .get(format!("{base}/ops/traces"))
        .header("X-Ops-Key", OPS_KEY)
        .send()
        .await
        .unwrap()
        .text()
        .await
        .unwrap();
    assert!(index.contains("will EURUSD rise tomorrow?"));
    let id = index
        .split("/ops/trace/")
        .nth(1)
        .and_then(|s| s.split('"').next())
        .expect("a trace link")
        .to_string();

    let page: String = client
        .get(format!("{base}/ops/trace/{id}"))
        .header("X-Ops-Key", OPS_KEY)
        .send()
        .await
        .unwrap()
        .text()
        .await
        .unwrap();
    for panel in [
        "Timeline",
        "Router",
        "Resolution",
        "Slips",
        "Gates",
        "Provenance map",
        "Prompt economics",
    ] {
        assert!(page.contains(panel), "the trace view is missing {panel:?}");
    }
    assert!(
        page.contains("topic guard: direction"),
        "deciding stage shown"
    );

    // JSON export carries the same record, with the session hashed rather than named.
    let j: Value = client
        .get(format!("{base}/ops/trace/{id}/json"))
        .header("X-Ops-Key", OPS_KEY)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(j["router"]["path"], "refusal");
    assert_ne!(
        j["session_hash"], "s-ops",
        "raw session id must not be stored"
    );
    assert!(j["session_hash"].as_str().unwrap().len() == 12);

    // every access left an audit row
    let audit: Value = client
        .get(format!("{base}/ops/audit"))
        .header("X-Ops-Key", OPS_KEY)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    let actions: Vec<&str> = audit["rows"]
        .as_array()
        .unwrap()
        .iter()
        .map(|r| r["action"].as_str().unwrap())
        .collect();
    assert!(actions.contains(&"view"), "the page view is audited");
    assert!(actions.contains(&"export"), "the JSON export is audited");
    let key_shown = audit["rows"][0]["key"].as_str().unwrap();
    assert_ne!(key_shown, OPS_KEY, "the audit trail stores the key hashed");
}

/// The anti-drift guarantee: replay and the live handler must route identically.
#[tokio::test]
async fn replay_agrees_with_the_live_chain() {
    let root = scratch_dir("replay");
    write_pack(&root);
    let base = spawn(&root, Some(OPS_KEY)).await;
    let client = reqwest::Client::new();

    let questions = [
        "will EURUSD rise tomorrow?",
        "should I buy dollars?",
        "what is the siren?",
        "how is EURUSD doing?",
        "what is the capital of France?",
    ];
    for q in questions {
        let live = ask(&base, q).await;
        let index: String = client
            .get(format!("{base}/ops/traces"))
            .header("X-Ops-Key", OPS_KEY)
            .send()
            .await
            .unwrap()
            .text()
            .await
            .unwrap();
        let id = index
            .split("/ops/trace/")
            .nth(1)
            .and_then(|s| s.split('"').next())
            .expect("a trace link")
            .to_string();
        let report: Value = client
            .post(format!("{base}/ops/trace/{id}/replay"))
            .header("X-Ops-Key", OPS_KEY)
            .send()
            .await
            .unwrap()
            .json()
            .await
            .unwrap();
        assert!(
            report["reproduced"].as_bool().unwrap_or(false),
            "replay diverged from the live chain for {q:?}: {} (live answer was {:?})",
            report["diffs"],
            live["text"]
        );
    }
}

#[tokio::test]
async fn promote_produces_a_reviewable_golden_item() {
    let root = scratch_dir("promote");
    write_pack(&root);
    let base = spawn(&root, Some(OPS_KEY)).await;
    let client = reqwest::Client::new();
    ask(&base, "what is the siren?").await;
    let index: String = client
        .get(format!("{base}/ops/traces"))
        .header("X-Ops-Key", OPS_KEY)
        .send()
        .await
        .unwrap()
        .text()
        .await
        .unwrap();
    let id = index
        .split("/ops/trace/")
        .nth(1)
        .and_then(|s| s.split('"').next())
        .unwrap()
        .to_string();
    let out: Value = client
        .post(format!("{base}/ops/trace/{id}/promote"))
        .header("X-Ops-Key", OPS_KEY)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    let yaml = out["yaml"].as_str().unwrap();
    assert!(yaml.contains("question: \"what is the siren?\""));
    assert!(yaml.contains("expected_route:"));
    assert!(yaml.contains("gold_values:"));
    assert!(
        yaml.contains("REVIEW before merging"),
        "a promoted item must not read as already-approved: it records what DID happen"
    );
    // and it must parse as YAML
    let parsed: serde_yaml::Value = serde_yaml::from_str(yaml).expect("promoted item parses");
    assert!(parsed.as_sequence().is_some_and(|s| s.len() == 1));
}

/// Requirement D: "regeneration from the trace is byte-identical".
///
/// Both paths call one renderer, so this test is really asking whether they build the same payload
/// — which is where the two could quietly drift, and the only place a divergence would show up as
/// two different official documents for the same answer.
#[tokio::test]
async fn the_operator_reissues_a_byte_identical_receipt() {
    let root = scratch_dir("receipt");
    write_pack(&root);
    let base = spawn(&root, Some(OPS_KEY)).await;
    let client = reqwest::Client::new();

    let answer = ask(&base, "what is the siren?").await;
    let customer: String = client
        .post(format!("{base}/avatar/receipt"))
        .header("X-Avatar-Token", "brt_test")
        .json(&json!({
            "session_id": "s-ops",
            "question": "what is the siren?",
            "answer": answer["text"],
            "provenance": answer.get("board")
                .and_then(|b| b.as_array())
                .map(|cards| cards.iter()
                    .filter_map(|c| c.get("provenance").and_then(|p| p.as_array()))
                    .flatten().cloned().collect::<Vec<_>>())
                .unwrap_or_default(),
        }))
        .send()
        .await
        .unwrap()
        .text()
        .await
        .unwrap();
    assert!(customer.contains("Educational tool. Not investment advice."));
    assert!(customer.contains("AI PRESENTER"));

    let index: String = client
        .get(format!("{base}/ops/traces"))
        .header("X-Ops-Key", OPS_KEY)
        .send()
        .await
        .unwrap()
        .text()
        .await
        .unwrap();
    let id = index
        .split("/ops/trace/")
        .nth(1)
        .and_then(|s| s.split('"').next())
        .unwrap()
        .to_string();
    let reissued: String = client
        .get(format!("{base}/ops/trace/{id}/receipt"))
        .header("X-Ops-Key", OPS_KEY)
        .send()
        .await
        .unwrap()
        .text()
        .await
        .unwrap();
    assert_eq!(
        customer, reissued,
        "the operator's reissued receipt differs from the one the customer received"
    );
}

/// A receipt is a document that carries this system's name. It may only be issued for something
/// this system actually said.
#[tokio::test]
async fn a_receipt_cannot_be_issued_for_text_we_never_produced() {
    let root = scratch_dir("forge");
    write_pack(&root);
    let base = spawn(&root, Some(OPS_KEY)).await;
    let r = reqwest::Client::new()
        .post(format!("{base}/avatar/receipt"))
        .header("X-Avatar-Token", "brt_test")
        .json(&json!({
            "session_id": "s-ops",
            "question": "is EURUSD going up?",
            "answer": "Yes, EURUSD will rise 3% next week.",
            "provenance": [],
        }))
        .send()
        .await
        .unwrap();
    assert_eq!(
        r.status(),
        403,
        "arbitrary text must not become an official receipt"
    );
}

/// Phase 45: the kill switch must work mid-session, under load, without dropping anything.
///
/// Testing it at rest proves the flag parses. What matters operationally is the moment you flip it
/// with sessions in flight: every one of them must keep answering, and every answer must stay
/// grounded. A kill switch that requires quiescence is a deploy with extra steps.
#[tokio::test]
async fn the_kill_switch_takes_effect_mid_session_under_load() {
    let root = scratch_dir("killswitch");
    write_pack(&root);
    let flags_path = root.join("flags.json");
    std::fs::write(&flags_path, "{}").unwrap();

    let mut state = state_for(&root, Some(OPS_KEY));
    state.flags = fxradar_serve::flags::FlagStore::new(flags_path.clone());
    let app = build_router(state);
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    let base = format!("http://{addr}");

    // Twelve concurrent sessions, each asking repeatedly, while the switch is flipped underneath.
    let stop = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let errors = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let answered = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let mut workers = Vec::new();
    for i in 0..12 {
        let (base, stop, errors, answered) =
            (base.clone(), stop.clone(), errors.clone(), answered.clone());
        workers.push(tokio::spawn(async move {
            let client = reqwest::Client::new();
            while !stop.load(std::sync::atomic::Ordering::Relaxed) {
                let r = client
                    .post(format!("{base}/avatar/brain"))
                    .header("X-Avatar-Token", "brt_test")
                    .json(&json!({
                        "session_id": format!("load-{i}"),
                        "messages": [{"role": "user", "content": "what is the siren?"}],
                    }))
                    .send()
                    .await;
                match r {
                    Ok(res) if res.status() == 200 => {
                        let body: Value = res.json().await.unwrap_or(json!({}));
                        // The invariant that must hold across the flip: every answer is gated.
                        // Degrading the feature set may not degrade the guarantee.
                        let gate = body["gate"].as_str().unwrap_or("");
                        if gate.is_empty() {
                            errors.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                        } else {
                            answered.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                        }
                    }
                    _ => {
                        errors.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                    }
                }
                tokio::task::yield_now().await;
            }
        }));
    }

    // Wait for the load to actually establish rather than sleeping a fixed interval and hoping.
    // A fixed sleep passes on an idle machine and flakes on a busy one, which is the worst
    // combination: it fails in CI and passes for whoever is asked to look at it.
    let mut before = 0;
    for _ in 0..100 {
        tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        before = answered.load(std::sync::atomic::Ordering::Relaxed);
        if before > 0 {
            break;
        }
    }
    assert!(before > 0, "load did not establish within 2s");

    let client = reqwest::Client::new();
    let flip = client
        .post(format!("{base}/ops/flags"))
        .header("X-Ops-Key", OPS_KEY)
        .json(&json!({"flag": "agent_enabled", "value": false}))
        .send()
        .await
        .unwrap();
    assert_eq!(
        flip.status(),
        200,
        "the switch must flip without a redeploy"
    );

    // And wait for turns to complete AFTER the flip, again by condition rather than by clock.
    for _ in 0..100 {
        tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        if answered.load(std::sync::atomic::Ordering::Relaxed) > before {
            break;
        }
    }
    stop.store(true, std::sync::atomic::Ordering::Relaxed);
    for w in workers {
        let _ = w.await;
    }

    let after = answered.load(std::sync::atomic::Ordering::Relaxed);
    let failed = errors.load(std::sync::atomic::Ordering::Relaxed);
    assert!(
        after > before,
        "sessions must keep answering across the flip ({before} before, {after} after)"
    );
    assert_eq!(
        failed, 0,
        "{failed} requests failed while the switch was pulled"
    );

    // And the flag really is off afterwards, read back through the file that is the source of truth.
    let now: Value = client
        .get(format!("{base}/ops/flags"))
        .header("X-Ops-Key", OPS_KEY)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(now["flags"]["agent_enabled"], false);
}
