//! Phase-35 avatar tests — network-free (no Anthropic key, no vendor keys anywhere in these
//! configs; the LLM path is proven blocked/fallback-safe, never exercised live). A temp context
//! pack fixture stands in for data/avatar_context.json; `test_force_text` (honoured only via the
//! explicit test hook) lets the suite prove the gates block planted fabrications.

use fxradar_serve::app::{build_router, AppState, SelftestStatus};
use fxradar_serve::avatar::AvatarCfg;
use fxradar_serve::store::{now_unix, Store, Tier};
use serde_json::{json, Value};
use std::path::{Path, PathBuf};

const GREETING: &str =
    "As of the 2026-08-18 close, EURUSD is calm — change risk 0.01, band 0.00 to 0.51, siren 73 of 100.";
// "up to 2016" is deliberate: verbatim pack content is pre-linted by Python, so the word-list
// direction lint must NOT false-positive on it (the real pack's FAQ answers contain the phrase).
const SIREN_ANSWER: &str =
    "The siren ranks today against calm history from 0 to 100, trained on data up to 2016.";
const REF_DIRECTION: &str = "REFUSAL-DIRECTION: the radar never models direction.";
const REF_ADVICE: &str = "REFUSAL-ADVICE: educational tool, not investment advice.";
const REF_OFF_TOPIC: &str = "REFUSAL-OFFTOPIC: I only speak from the published numbers.";
const REF_NOT_IN_PACK: &str = "REFUSAL-NOTINPACK: I don't have that number and won't guess.";

fn scratch_dir(name: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("fxr_avatar_{}_{}", name, std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

fn write_pack(root: &Path, greeting: &str) {
    let pack = json!({
        "generated_at_utc": "2026-08-19T06:00:00Z",
        "universe": "fx",
        "data_through": "2026-08-18",
        "system_prompt_version": "v1",
        "disclosure": "I am the radar's AI presenter — a computer-generated voice, not a person.",
        "greeting": greeting,
        "pairs": {"EURUSD": {"regime": "calm", "change_risk_5d": 0.01}},
        "events": [],
        "treasury": {},
        "ledger": {},
        "drift": {"model_stale": false},
        "refusals": {
            "direction": REF_DIRECTION,
            "advice": REF_ADVICE,
            "off_topic": REF_OFF_TOPIC,
            "not_in_pack": REF_NOT_IN_PACK,
        },
        "faq": [
            {"q": "What is the siren?", "keywords": ["siren"], "answer": SIREN_ANSWER},
            {"q": "What is the change risk?", "keywords": ["change", "risk", "probability"],
             "answer": "The chance the regime label differs within 5 trading days."},
        ],
        "allowed_numbers": ["0", "0.01", "0.51", "5", "73", "100", "2016", "2026", "8", "18"],
        "knowledge_pack": "docs/avatar_knowledge.md",
    });
    std::fs::create_dir_all(root.join("data")).unwrap();
    std::fs::create_dir_all(root.join("docs")).unwrap();
    std::fs::write(
        root.join("data/avatar_context.json"),
        serde_json::to_vec_pretty(&pack).unwrap(),
    )
    .unwrap();
    std::fs::write(
        root.join("docs/avatar_knowledge.md"),
        "# Avatar knowledge pack (test fixture)\nThe siren ranks strangeness from 0 to 100.\n",
    )
    .unwrap();
}

fn selftest_status() -> SelftestStatus {
    SelftestStatus {
        status: "skipped".into(),
        goldens: 0,
        at_unix: 0,
        worst: vec![],
    }
}

fn base_cfg() -> AvatarCfg {
    AvatarCfg {
        enabled: true,
        brain_token: Some("brt_test".into()),
        test_hook: true, // explicit: the suite must behave the same under --release
        ..AvatarCfg::default()
    }
}

/// Spin up the full router with an avatar config; data_dir = <root>/data.
async fn spawn_app(root: &Path, cfg: AvatarCfg) -> (String, Store) {
    let store = Store::open_in_memory().unwrap();
    let state = AppState::new(
        None,
        store.clone(),
        root.join("data"),
        selftest_status(),
        60,
        None,
    )
    .with_avatar(cfg);
    let app = build_router(state);
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    (format!("http://{addr}"), store)
}

async fn ask(base: &str, token: &str, question: &str, force: Option<&str>) -> Value {
    let mut body = json!({
        "session_id": "s-test",
        "messages": [{"role": "user", "content": question}],
    });
    if let Some(f) = force {
        body["test_force_text"] = json!(f);
    }
    let r = reqwest::Client::new()
        .post(format!("{base}/avatar/brain"))
        .header("X-Avatar-Token", token)
        .json(&body)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 200, "brain call failed");
    r.json().await.unwrap()
}

// ---------------------------------------------------------------------------------------------

#[tokio::test]
async fn flag_off_all_avatar_routes_answer_503() {
    let root = scratch_dir("off");
    write_pack(&root, GREETING);
    let cfg = AvatarCfg {
        enabled: false,
        ..base_cfg()
    };
    let (base, _) = spawn_app(&root, cfg).await;
    let c = reqwest::Client::new();
    for (method, path) in [
        ("GET", "/avatar/greeting"),
        ("POST", "/avatar/brain"),
        ("POST", "/avatar/session-token"),
        ("POST", "/avatar/heartbeat"),
        ("POST", "/avatar/tts"),
    ] {
        let req = match method {
            "GET" => c.get(format!("{base}{path}")),
            _ => c.post(format!("{base}{path}")).json(&json!({})),
        };
        let r = req.send().await.unwrap();
        assert_eq!(r.status(), 503, "{path} must be 503 while the flag is off");
        let v: Value = r.json().await.unwrap();
        assert_eq!(v["error"], "avatar disabled", "{path}");
    }
    // non-avatar public routes stay open
    let r = c.get(format!("{base}/api/health")).send().await.unwrap();
    assert_eq!(r.status(), 200);
}

#[tokio::test]
async fn brain_requires_a_token() {
    let root = scratch_dir("auth");
    write_pack(&root, GREETING);
    let (base, _) = spawn_app(&root, base_cfg()).await;
    let c = reqwest::Client::new();
    let body = json!({"session_id": "s", "messages": [{"role": "user", "content": "hi"}]});
    let r = c
        .post(format!("{base}/avatar/brain"))
        .json(&body)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
    let r = c
        .post(format!("{base}/avatar/brain"))
        .header("X-Avatar-Token", "wrong")
        .json(&body)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
}

#[tokio::test]
async fn topic_guard_refuses_direction_and_advice_with_pack_texts() {
    let root = scratch_dir("guard");
    write_pack(&root, GREETING);
    let (base, _) = spawn_app(&root, base_cfg()).await;
    let v = ask(&base, "brt_test", "will EURUSD rise?", None).await;
    assert_eq!(v["source"], "refusal");
    assert_eq!(v["gate"], "refused:direction");
    assert_eq!(v["text"], REF_DIRECTION);
    let v = ask(&base, "brt_test", "should I buy dollars?", None).await;
    assert_eq!(v["gate"], "refused:advice");
    assert_eq!(v["text"], REF_ADVICE);
    let v = ask(&base, "brt_test", "what's a good stop loss?", None).await;
    assert_eq!(v["gate"], "refused:advice");
}

#[tokio::test]
async fn keyless_faq_answer_passes_the_gates() {
    let root = scratch_dir("faq");
    write_pack(&root, GREETING);
    let (base, _) = spawn_app(&root, base_cfg()).await;
    let t0 = std::time::Instant::now();
    let v = ask(&base, "brt_test", "what is the siren?", None).await;
    let wall_ms = t0.elapsed().as_millis();
    assert_eq!(v["source"], "template");
    assert_eq!(v["gate"], "pass");
    assert_eq!(v["text"], SIREN_ANSWER);
    let numbers: Vec<String> = v["numbers"]
        .as_array()
        .unwrap()
        .iter()
        .map(|n| n.as_str().unwrap().to_string())
        .collect();
    assert_eq!(numbers, vec!["0", "100", "2016"]);
    println!(
        "keyless brain latency: server={} ms, wall={} ms",
        v["latency_ms"], wall_ms
    );
    // off-topic keyless → branded off-topic refusal
    let v = ask(&base, "brt_test", "tell me a joke about cats", None).await;
    assert_eq!(v["source"], "refusal");
    assert_eq!(v["gate"], "refused:off_topic");
    assert_eq!(v["text"], REF_OFF_TOPIC);
}

#[tokio::test]
async fn planted_fabrication_is_blocked_by_the_grounding_gate() {
    let root = scratch_dir("fab");
    write_pack(&root, GREETING);
    let (base, _) = spawn_app(&root, base_cfg()).await;
    let v = ask(
        &base,
        "brt_test",
        "what is the change risk?",
        Some("EURUSD change risk is 0.42 today"),
    )
    .await;
    assert_eq!(v["gate"], "blocked", "0.42 is not in allowed_numbers");
    assert_eq!(v["source"], "refusal");
    assert_eq!(v["text"], REF_NOT_IN_PACK);
}

#[tokio::test]
async fn planted_direction_word_is_blocked_by_the_lint() {
    let root = scratch_dir("dirword");
    write_pack(&root, GREETING);
    let (base, _) = spawn_app(&root, base_cfg()).await;
    let v = ask(
        &base,
        "brt_test",
        "what is the regime?",
        Some("The euro should rally after the meeting"),
    )
    .await;
    assert_eq!(v["gate"], "blocked");
    assert_eq!(v["text"], REF_NOT_IN_PACK);
}

#[tokio::test]
async fn numbers_echoed_from_the_question_are_not_fabrication() {
    let root = scratch_dir("echo");
    write_pack(&root, GREETING);
    let (base, _) = spawn_app(&root, base_cfg()).await;
    let v = ask(
        &base,
        "brt_test",
        "why did you mention 0.42 earlier?",
        Some("You mentioned 0.42; the published change risk is 0.01."),
    )
    .await;
    assert_eq!(v["gate"], "pass");
    assert_eq!(v["source"], "llm");
    let numbers: Vec<&str> = v["numbers"]
        .as_array()
        .unwrap()
        .iter()
        .map(|n| n.as_str().unwrap())
        .collect();
    assert_eq!(numbers, vec!["0.42", "0.01"]);
}

#[tokio::test]
async fn test_hook_is_ignored_without_the_test_flag() {
    let root = scratch_dir("hookoff");
    write_pack(&root, GREETING);
    let cfg = AvatarCfg {
        test_hook: false,
        ..base_cfg()
    };
    let (base, _) = spawn_app(&root, cfg).await;
    // In a release binary without FXRADAR_AVATAR_TEST the forced text must be ignored and the
    // keyless FAQ path used instead. (In debug builds AvatarCfg::default() re-enables the hook,
    // so guard on the env var too.)
    if cfg!(debug_assertions) || std::env::var("FXRADAR_AVATAR_TEST").as_deref() == Ok("1") {
        return;
    }
    let v = ask(
        &base,
        "brt_test",
        "what is the siren?",
        Some("Fabricated 0.42 rally"),
    )
    .await;
    assert_eq!(v["source"], "template");
    assert_eq!(v["text"], SIREN_ANSWER);
}

#[tokio::test]
async fn greeting_is_served_verbatim_and_corrupt_packs_500() {
    let root = scratch_dir("greet");
    write_pack(&root, GREETING);
    let (base, _) = spawn_app(&root, base_cfg()).await;
    let r = reqwest::Client::new()
        .get(format!("{base}/avatar/greeting"))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 200);
    let v: Value = r.json().await.unwrap();
    assert_eq!(v["text"], GREETING);
    assert_eq!(v["source"], "template");
    assert_eq!(v["data_through"], "2026-08-18");
    assert!(v["disclosure"].as_str().unwrap().contains("AI presenter"));
    // a pack whose greeting cites a number outside its own allowed list is corrupt → 500 loudly
    let root2 = scratch_dir("greet_bad");
    write_pack(&root2, "Change risk is 0.42 today.");
    let (base2, _) = spawn_app(&root2, base_cfg()).await;
    let r = reqwest::Client::new()
        .get(format!("{base2}/avatar/greeting"))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 500);
}

#[tokio::test]
async fn session_token_flow_local_vendor_and_expiry() {
    let root = scratch_dir("session");
    write_pack(&root, GREETING);
    let (base, store) = spawn_app(&root, base_cfg()).await;
    let c = reqwest::Client::new();
    // no key → 401
    let r = c
        .post(format!("{base}/avatar/session-token"))
        .json(&json!({"vendor": "local"}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
    // free tier → 403
    let (free_key, _) = store.issue_key("free", Tier::Free).unwrap();
    let r = c
        .post(format!("{base}/avatar/session-token"))
        .header("X-API-Key", free_key)
        .json(&json!({"vendor": "local"}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 403);
    // pro key → 200 with a short-lived session token the widget can use on /avatar/brain
    let (pro_key, _) = store.issue_key("pro", Tier::Pro).unwrap();
    let r = c
        .post(format!("{base}/avatar/session-token"))
        .header("X-API-Key", &pro_key)
        .json(&json!({"vendor": "local"}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 200);
    let v: Value = r.json().await.unwrap();
    assert_eq!(v["vendor"], "local");
    assert_eq!(v["brain"], "/avatar/brain");
    let token = v["token"].as_str().unwrap().to_string();
    assert_eq!(token.len(), 32, "32-hex session token");
    assert!(v["session_id"].as_str().unwrap().len() >= 8);
    // the session token authenticates the brain
    let ans = ask(&base, &token, "what is the siren?", None).await;
    assert_eq!(ans["gate"], "pass");
    // an expired session token does not
    let now = now_unix();
    store
        .insert_avatar_session("e".repeat(32).as_str(), "old", now - 100, now - 1)
        .unwrap();
    let body = json!({"session_id": "old", "messages": [{"role": "user", "content": "hi"}]});
    let r = c
        .post(format!("{base}/avatar/brain"))
        .header("X-Avatar-Token", "e".repeat(32))
        .json(&body)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
    // vendor keys unset → 503, never an invented success (and never a network call)
    for vendor in ["anam", "heygen"] {
        let r = c
            .post(format!("{base}/avatar/session-token"))
            .header("X-API-Key", &pro_key)
            .json(&json!({"vendor": vendor}))
            .send()
            .await
            .unwrap();
        assert_eq!(r.status(), 503, "{vendor} without a key must 503");
        let v: Value = r.json().await.unwrap();
        assert_eq!(v["error"], format!("{vendor} not configured"));
    }
}

#[tokio::test]
async fn dev_flag_waives_the_key_in_dev_mode_only() {
    let root = scratch_dir("dev");
    write_pack(&root, GREETING);
    let cfg = AvatarCfg {
        dev: true,
        ..base_cfg()
    };
    let (base, store) = spawn_app(&root, cfg).await;
    let c = reqwest::Client::new();
    // DEV ONLY behaviour: local vendor without a key → 200
    let r = c
        .post(format!("{base}/avatar/session-token"))
        .json(&json!({"vendor": "local"}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 200);
    // still counted against the monthly budget
    let month = &fxradar_serve::store::iso_from_unix(now_unix())[..7];
    assert_eq!(store.avatar_usage(month).unwrap().0, 1);
    // dev waives the key for non-local vendors too (the widget never holds one); the anam key
    // itself is absent in this test config, so the proxy correctly answers 503 — NOT 401.
    let r = c
        .post(format!("{base}/avatar/session-token"))
        .json(&json!({"vendor": "anam"}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 503);
}

#[tokio::test]
async fn monthly_cost_caps_answer_429() {
    // session cap
    let root = scratch_dir("cap_sessions");
    write_pack(&root, GREETING);
    let cfg = AvatarCfg {
        max_sessions_month: 1,
        ..base_cfg()
    };
    let (base, store) = spawn_app(&root, cfg).await;
    let (pro_key, _) = store.issue_key("pro", Tier::Pro).unwrap();
    let c = reqwest::Client::new();
    let post = |b: &str| {
        c.post(format!("{b}/avatar/session-token"))
            .header("X-API-Key", &pro_key)
            .json(&json!({"vendor": "local"}))
    };
    assert_eq!(post(&base).send().await.unwrap().status(), 200);
    let r = post(&base).send().await.unwrap();
    assert_eq!(r.status(), 429);
    let v: Value = r.json().await.unwrap();
    assert_eq!(v["error"], "monthly avatar budget reached");
    // minutes cap via heartbeat accounting
    let root2 = scratch_dir("cap_minutes");
    write_pack(&root2, GREETING);
    let cfg2 = AvatarCfg {
        max_minutes_month: 0.5,
        ..base_cfg()
    };
    let (base2, store2) = spawn_app(&root2, cfg2).await;
    let (pro2, _) = store2.issue_key("pro", Tier::Pro).unwrap();
    let r = c
        .post(format!("{base2}/avatar/heartbeat"))
        .header("X-Avatar-Token", "brt_test")
        .json(&json!({"session_id": "s", "seconds": 60.0}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 200);
    let v: Value = r.json().await.unwrap();
    assert!((v["minutes_month"].as_f64().unwrap() - 1.0).abs() < 1e-9);
    let r = c
        .post(format!("{base2}/avatar/session-token"))
        .header("X-API-Key", &pro2)
        .json(&json!({"vendor": "local"}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 429, "1.0 min used > 0.5 min cap");
}

#[tokio::test]
async fn every_brain_answer_writes_a_transcript_row() {
    let root = scratch_dir("transcript");
    write_pack(&root, GREETING);
    let (base, store) = spawn_app(&root, base_cfg()).await;
    let _ = ask(&base, "brt_test", "what is the siren?", None).await;
    let _ = ask(&base, "brt_test", "will EURUSD rise?", None).await;
    let rows = store.recent_transcripts(10).unwrap();
    assert_eq!(rows.len(), 2);
    // newest first
    assert_eq!(rows[0].question, "will EURUSD rise?");
    assert_eq!(rows[0].gate, "refused:direction");
    assert_eq!(rows[0].source, "refusal");
    assert_eq!(rows[1].question, "what is the siren?");
    assert_eq!(rows[1].answer, SIREN_ANSWER);
    assert_eq!(rows[1].gate, "pass");
    assert_eq!(rows[1].session_id, "s-test");
}

// ---------------------------------------------------------------------------------------------
// delta: open mode + realistic TTS
// ---------------------------------------------------------------------------------------------

#[test]
fn v2_prompt_exists_and_is_the_open_mode_default() {
    let p = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../prompts/avatar_system_v2.txt");
    let text = std::fs::read_to_string(&p).unwrap();
    assert!(text.contains("avatar_system_v2"));
    assert!(text.contains("price direction"), "the hard bans stay in v2");
    assert!(fxradar_serve::avatar::default_system_prompt(true).ends_with("avatar_system_v2.txt"));
    assert!(fxradar_serve::avatar::default_system_prompt(false).ends_with("avatar_system_v1.txt"));
}

#[tokio::test]
async fn open_mode_annotates_ungrounded_numbers_but_direction_stays_blocking() {
    let root = scratch_dir("open");
    write_pack(&root, GREETING);
    let cfg = AvatarCfg {
        open: true,
        ..base_cfg()
    };
    let (base, store) = spawn_app(&root, cfg).await;
    // a general-knowledge number flows, annotated — never blocked
    let v = ask(
        &base,
        "brt_test",
        "what happened in the financial crisis?",
        Some("The 2008 crisis pushed volatility to historic extremes near 80 percent."),
    )
    .await;
    assert_eq!(v["gate"], "open:ungrounded");
    assert_eq!(v["source"], "llm");
    assert!(v["text"].as_str().unwrap().contains("2008"), "text intact");
    // the direction lint is constitutional and still blocks
    let v = ask(
        &base,
        "brt_test",
        "tell me about markets",
        Some("Stocks look bullish this quarter"),
    )
    .await;
    assert_eq!(v["gate"], "blocked");
    assert_eq!(v["text"], REF_NOT_IN_PACK);
    // and so does the topic guard
    let v = ask(&base, "brt_test", "will EURUSD rise?", None).await;
    assert_eq!(v["gate"], "refused:direction");
    // greeting + session-token badge the mode (and the TTS transport)
    let g: Value = reqwest::get(format!("{base}/avatar/greeting"))
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(g["open"], true);
    let (pro, _) = store.issue_key("pro", Tier::Pro).unwrap();
    let t: Value = reqwest::Client::new()
        .post(format!("{base}/avatar/session-token"))
        .header("X-API-Key", pro)
        .json(&json!({"vendor": "local"}))
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(t["open"], true);
    assert_eq!(t["tts"], "browser", "no ElevenLabs key in tests");
}

#[tokio::test]
async fn closed_mode_still_blocks_ungrounded_numbers() {
    let root = scratch_dir("closed");
    write_pack(&root, GREETING);
    let (base, _) = spawn_app(&root, base_cfg()).await; // open: false
    let v = ask(
        &base,
        "brt_test",
        "what happened in the financial crisis?",
        Some("The 2008 crisis pushed volatility near 80 percent."),
    )
    .await;
    assert_eq!(v["gate"], "blocked");
}

#[tokio::test]
async fn tts_only_speaks_gated_answers() {
    let root = scratch_dir("tts");
    write_pack(&root, GREETING);
    let (base, _) = spawn_app(&root, base_cfg()).await;
    let c = reqwest::Client::new();
    // 401 without a token
    let r = c
        .post(format!("{base}/avatar/tts"))
        .json(&json!({"session_id": "s-test", "text": "x"}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
    // un-hashed text → 403 (the hash check runs BEFORE the vendor-key check, so this is keyless)
    let r = c
        .post(format!("{base}/avatar/tts"))
        .header("X-Avatar-Token", "brt_test")
        .json(&json!({"session_id": "s-test", "text": "a text the brain never produced"}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 403);
    let v: Value = r.json().await.unwrap();
    assert_eq!(v["error"], "tts only speaks gated answers");
    // a real brain answer passes the hash check; keyless → 404 browser fallback (proves the
    // request reached the vendor-key step)
    let ans = ask(&base, "brt_test", "what is the siren?", None).await;
    let text = ans["text"].as_str().unwrap();
    let r = c
        .post(format!("{base}/avatar/tts"))
        .header("X-Avatar-Token", "brt_test")
        .json(&json!({"session_id": "s-test", "text": text}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 404);
    let v: Value = r.json().await.unwrap();
    assert_eq!(v["tts"], "browser");
    // hashes are per-session: the same text under another session id is refused
    let r = c
        .post(format!("{base}/avatar/tts"))
        .header("X-Avatar-Token", "brt_test")
        .json(&json!({"session_id": "other-session", "text": text}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 403);
    // the exact current pack greeting is always speakable (spoken before any session exists)
    let r = c
        .post(format!("{base}/avatar/tts"))
        .header("X-Avatar-Token", "brt_test")
        .json(&json!({"session_id": "nosession", "text": GREETING}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 404);
}

#[tokio::test]
async fn tts_chars_cap_answers_429() {
    let root = scratch_dir("ttscap");
    write_pack(&root, GREETING);
    let cfg = AvatarCfg {
        max_tts_chars_month: 3,
        ..base_cfg()
    };
    let (base, _) = spawn_app(&root, cfg).await;
    let ans = ask(&base, "brt_test", "what is the siren?", None).await;
    let text = ans["text"].as_str().unwrap();
    let r = reqwest::Client::new()
        .post(format!("{base}/avatar/tts"))
        .header("X-Avatar-Token", "brt_test")
        .json(&json!({"session_id": "s-test", "text": text}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 429, "answer length exceeds the 3-char cap");
    let v: Value = r.json().await.unwrap();
    assert_eq!(v["error"], "monthly avatar budget reached");
}

#[tokio::test]
async fn heygen_and_anam_vendor_responses_carry_a_brain_token() {
    // Without vendor keys the branches 503 — but the local branch plus the response contract are
    // covered here: every session-token response must let the widget call /avatar/brain, i.e.
    // "local" carries `token` valid for the brain, and the vendor branches (verified live with a
    // real Anam key on 2026-08-20) mint the same store-backed token as `brain_token`.
    let root = scratch_dir("brain_token_contract");
    write_pack(&root, GREETING);
    let cfg = AvatarCfg {
        dev: true,
        ..base_cfg()
    };
    let (base, store) = spawn_app(&root, cfg).await;
    let c = reqwest::Client::new();
    let r: serde_json::Value = c
        .post(format!("{base}/avatar/session-token"))
        .json(&json!({"vendor": "local"}))
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    let tok = r["token"].as_str().unwrap();
    // the minted token must authenticate a brain call
    let b = c
        .post(format!("{base}/avatar/brain"))
        .header("X-Avatar-Token", tok)
        .json(&json!({"session_id": r["session_id"], "messages": [{"role":"user","content":"what is the siren?"}]}))
        .send()
        .await
        .unwrap();
    assert_eq!(b.status(), 200);
    assert!(store.avatar_session_valid(tok, now_unix()).unwrap());
}

// ---------------------------------------------------------------------------------------------
// delta: deterministic hedging decision support (advice mode)
// ---------------------------------------------------------------------------------------------

const DEC_DISCLOSURE: &str = "DECISION-DISCLOSURE: software-generated decision support from the \
radar's published numbers, not advice from a licensed adviser.";

fn write_decision_table(root: &Path) {
    let row = |ratio: f64, sched4: Value| {
        json!({
            "light": "wait", "regime": "calm", "hedge_ratio": ratio,
            "schedule_by_horizon": {
                "1": [{"week": 0, "fraction": ratio}],
                "2": [{"week": 0, "fraction": ratio}],
                "4": sched4,
                "8": [{"week": 0, "fraction": ratio}],
                "12": [{"week": 0, "fraction": ratio}],
            },
            "es_99_1w": 0.02, "es_95_1w": 0.016, "var_99_1w": 0.018,
            "review_trigger": "revisit if the regime flips or the consensus reaches 2 of 3; otherwise review weekly",
        })
    };
    let pair = |cons4: Value| {
        json!({
            "conservative": row(0.6, cons4),
            "balanced": row(0.5, json!([{"week": 0, "fraction": 0.5}])),
            "aggressive": row(0.3, json!([{"week": 0, "fraction": 0.3}])),
        })
    };
    let cons4 = json!([
        {"week": 0, "fraction": 0.3}, {"week": 1, "fraction": 0.1},
        {"week": 2, "fraction": 0.1}, {"week": 3, "fraction": 0.1}]);
    let table = json!({
        "generated_at_utc": "2026-08-19T06:00:00Z",
        "data_through": "2026-08-18",
        "disclosure": DEC_DISCLOSURE,
        "method": "deterministic",
        "fx": {"EURUSD": 1.16, "USDCHF": 0.81, "GBPUSD": 1.35, "EURCHF": 0.94, "GBPCHF": 1.10},
        "pairs": {
            "EURUSD": pair(cons4),
            "GBPUSD": pair(json!([{"week": 0, "fraction": 0.6}])),
            "USDCHF": pair(json!([{"week": 0, "fraction": 0.6}])),
        },
        "compliance": "software-generated decision support; Swiss FinSA review required",
    });
    std::fs::write(
        root.join("data/decision_table.json"),
        serde_json::to_vec_pretty(&table).unwrap(),
    )
    .unwrap();
}

#[tokio::test]
async fn advice_mode_gives_deterministic_decision_support() {
    let root = scratch_dir("advice_on");
    write_pack(&root, GREETING);
    write_decision_table(&root);
    let cfg = AvatarCfg {
        advice: true,
        ..base_cfg()
    };
    let (base, _) = spawn_app(&root, cfg).await;
    // full question: pair + amount + horizon + tolerance
    let v = ask(
        &base,
        "brt_test",
        "Should I hedge my 800000 euro exposure for 4 weeks? I am conservative",
        None,
    )
    .await;
    assert_eq!(v["source"], "decision");
    assert_eq!(v["gate"], "pass");
    let text = v["text"].as_str().unwrap();
    assert!(
        text.starts_with(DEC_DISCLOSURE),
        "first advice answer of a session carries the disclosure: {text}"
    );
    assert!(text.contains("cover 60% of the exposure"), "{text}");
    assert!(
        text.contains("30% now, then 10% in each of the next 3 weeks"),
        "{text}"
    );
    // 800000 × (1 − 0.6) × 0.02 × sqrt(4) = 12800, in the user's own currency
    assert!(text.contains("12800 EUR"), "{text}");
    assert!(text.contains("Today's light: wait (calm regime)"), "{text}");
    // second advice answer in the SAME session: no disclosure repeat
    let v = ask(
        &base,
        "brt_test",
        "should i hedge my 800000 euro exposure?",
        None,
    )
    .await;
    assert_eq!(v["source"], "decision");
    assert!(!v["text"].as_str().unwrap().contains("DECISION-DISCLOSURE"));
    // defaults path: no pair, no amount, no horizon → balanced, first table pair, 4 weeks,
    // amount-free phrasing
    let body = json!({"session_id": "fresh", "messages": [{"role": "user", "content": "should I hedge?"}]});
    let v: Value = reqwest::Client::new()
        .post(format!("{base}/avatar/brain"))
        .header("X-Avatar-Token", "brt_test")
        .json(&body)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(v["source"], "decision");
    assert_eq!(v["gate"], "pass");
    let text = v["text"].as_str().unwrap();
    assert!(
        text.contains("balanced profile on EUR/USD over 4 weeks"),
        "{text}"
    );
    assert!(text.contains("cover 50% of the exposure"), "{text}");
    // 0.02 × sqrt(4) = 4.0% of the amount
    assert!(text.contains("about 4.0% of the amount"), "{text}");
    assert!(
        text.starts_with(DEC_DISCLOSURE),
        "fresh session hears the disclosure"
    );
    // direction questions are STILL refused with advice on
    let v = ask(&base, "brt_test", "will EURUSD rise?", None).await;
    assert_eq!(v["gate"], "refused:direction");
    // badges
    let g: Value = reqwest::get(format!("{base}/avatar/greeting"))
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(g["advice"], true);
}

#[tokio::test]
async fn advice_off_keeps_the_refusal_even_with_a_table_present() {
    let root = scratch_dir("advice_off");
    write_pack(&root, GREETING);
    write_decision_table(&root);
    let (base, _) = spawn_app(&root, base_cfg()).await; // advice: false (default)
    let v = ask(&base, "brt_test", "should I hedge my exposure?", None).await;
    assert_eq!(v["source"], "refusal");
    assert_eq!(v["gate"], "refused:advice");
    assert_eq!(v["text"], REF_ADVICE);
    let g: Value = reqwest::get(format!("{base}/avatar/greeting"))
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(g["advice"], false);
}
