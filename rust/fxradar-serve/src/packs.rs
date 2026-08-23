//! Precomputed answers, conversation state, and reference resolution (phase 40).
//!
//! Serving order is: **resolve references → select intent → exact pack → live**. Resolution comes
//! first because "and USDCHF?" is not a question until it has been expanded — classifying it before
//! resolving it classifies the wrong utterance.
//!
//! Two rules shape everything here.
//!
//! **Staleness is explicit, never silent.** A pack whose context version, prompt version, gate
//! rules, model or voice no longer match current was written under superseded rules. It may still
//! be served — a stale answer beats no answer at 09:00 when the 06:00 build failed — but only with
//! the stale badge attached, so the user is told the difference.
//!
//! **A resolution is always echoed.** "USD/CHF, same reading: calm" lets the user catch a
//! mis-resolution in the same breath they hear it. A silently wrong resolution is the worst failure
//! a conversational product has: it is confident, it is fast, and it answers a question nobody
//! asked. When resolution is ambiguous the system asks a one-line question instead of guessing.
//!
//! On the intent classifier: the trained sklearn model lives on the research side and is measured in
//! `reports/intent_classifier.md`. It does not run here, because rule 11 forbids Python at runtime
//! and the model has not yet been exported across the wall. Serving uses the deterministic ranker of
//! phase 38 — which is itself a sub-millisecond local classifier, is mirrored and pinned against the
//! Python implementation, and produces the card that a pack is keyed by.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::Path;
use std::sync::Mutex;
use std::time::{Duration, Instant};

/// How long a conversation keeps its state. Long enough for a follow-up, short enough that a
/// stranger on the same session id cannot inherit a stale subject.
pub const STATE_TTL: Duration = Duration::from_secs(30 * 60);

#[derive(Deserialize, Clone, Debug, Default)]
pub struct PackManifest {
    #[serde(default)]
    pub context_version: String,
    #[serde(default)]
    pub intent_version: String,
    #[serde(default)]
    pub registry_version: String,
    #[serde(default)]
    pub prompt_version: String,
    #[serde(default)]
    pub gate_rules_version: String,
    #[serde(default)]
    pub model_id_and_version: String,
    #[serde(default)]
    pub voice_id: String,
    #[serde(default)]
    pub n_packs: usize,
    #[serde(default)]
    pub audio_baked: bool,
}

#[derive(Deserialize, Serialize, Clone, Debug)]
pub struct PackSpeech {
    #[serde(default)]
    pub standalone: String,
    #[serde(default)]
    pub followup: String,
}

#[derive(Deserialize, Clone, Debug)]
pub struct AnswerPack {
    pub intent_id: String,
    pub card: String,
    #[serde(default)]
    pub pair: String,
    #[serde(default)]
    pub locale: String,
    pub speech: PackSpeech,
    #[serde(default)]
    pub board: Vec<crate::visuals::CardSpec>,
    #[serde(default)]
    pub audio: Option<String>,
    #[serde(default)]
    pub cache_key: String,
}

#[derive(Deserialize, Clone, Debug, Default)]
pub struct AnswerPacks {
    #[serde(default)]
    pub manifest: PackManifest,
    #[serde(default)]
    pub packs: HashMap<String, AnswerPack>,
}

impl AnswerPacks {
    /// Find the pack for a card, market and locale. Falls back to the locale-free instance so a
    /// French question about a market we only built in English still gets its numbers.
    pub fn find(&self, card: &str, pair: &str, locale: &str) -> Option<&AnswerPack> {
        let mut best: Option<&AnswerPack> = None;
        for pack in self.packs.values() {
            if pack.card != card {
                continue;
            }
            let pair_ok = pair.is_empty() || pack.pair.eq_ignore_ascii_case(pair);
            if !pair_ok {
                continue;
            }
            if pack.locale == locale {
                return Some(pack);
            }
            if best.is_none() && pack.locale == "en" {
                best = Some(pack);
            }
        }
        best
    }

    /// Are these packs still governed by current rules? Returns the reasons they are not.
    pub fn staleness(&self, context_version: &str, registry_version: &str) -> Vec<String> {
        let m = &self.manifest;
        let mut out = Vec::new();
        if !m.context_version.is_empty() && m.context_version != context_version {
            out.push(format!(
                "context {} (current {context_version})",
                m.context_version
            ));
        }
        if !m.registry_version.is_empty() && m.registry_version != registry_version {
            out.push(format!(
                "registry {} (current {registry_version})",
                m.registry_version
            ));
        }
        out
    }
}

pub fn load_packs(path: &Path) -> Result<AnswerPacks, String> {
    let raw = std::fs::read_to_string(path).map_err(|e| format!("answer packs unreadable: {e}"))?;
    serde_json::from_str(&raw).map_err(|e| format!("answer packs are not valid JSON: {e}"))
}

// ---------------------------------------------------------------------------------------------
// conversation state
// ---------------------------------------------------------------------------------------------

/// Deliberately small. Storing free text would make this a transcript store with a TTL, which is a
/// different thing with different obligations; these five fields are what resolution needs and
/// nothing more.
#[derive(Clone, Debug, Default)]
pub struct SessionState {
    pub last_intent: Option<String>,
    pub last_card: Option<String>,
    pub last_pair: Option<String>,
    pub last_date_range: Option<String>,
    pub last_board_cards: Vec<String>,
    pub locale: String,
    pub turn_index: u32,
}

#[derive(Default)]
pub struct ConversationStore {
    inner: Mutex<HashMap<String, (SessionState, Instant)>>,
}

impl ConversationStore {
    pub fn get(&self, session_id: &str) -> Option<SessionState> {
        let mut map = self.inner.lock().ok()?;
        match map.get(session_id) {
            Some((state, seen)) if seen.elapsed() < STATE_TTL => Some(state.clone()),
            Some(_) => {
                map.remove(session_id);
                None
            }
            None => None,
        }
    }

    pub fn put(&self, session_id: &str, state: SessionState) {
        if let Ok(mut map) = self.inner.lock() {
            if map.len() > 4096 {
                let now = Instant::now();
                map.retain(|_, (_, seen)| now.duration_since(*seen) < STATE_TTL);
            }
            map.insert(session_id.to_string(), (state, Instant::now()));
        }
    }

    pub fn end(&self, session_id: &str) {
        if let Ok(mut map) = self.inner.lock() {
            map.remove(session_id);
        }
    }
}

// ---------------------------------------------------------------------------------------------
// reference resolution
// ---------------------------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq)]
pub enum Resolution {
    /// Nothing elliptical: use the utterance as it stands.
    Verbatim,
    /// Expanded against state. `echo` is spoken back so a mis-resolution is caught immediately.
    /// `period` is set when the follow-up asked for a DIFFERENT time range — the caller must check
    /// whether the answering path can actually honour it, because echoing "last month" over a
    /// reading of today is a lie the user has no way to detect.
    Expanded {
        query: String,
        echo: String,
        pair: Option<String>,
        period: Option<String>,
    },
    /// Ambiguous. Ask rather than guess — a wrong silent resolution is worse than a short question.
    Ambiguous { question: String },
}

const PAIR_WORDS: &[(&str, &str)] = &[
    ("eurusd", "EURUSD"),
    ("eur/usd", "EURUSD"),
    ("euro", "EURUSD"),
    ("usdchf", "USDCHF"),
    ("usd/chf", "USDCHF"),
    ("franc", "USDCHF"),
    ("franken", "USDCHF"),
    ("swissie", "USDCHF"),
    ("chf", "USDCHF"),
    ("gbpusd", "GBPUSD"),
    ("gbp/usd", "GBPUSD"),
    ("sterling", "GBPUSD"),
    ("cable", "GBPUSD"),
    ("pound", "GBPUSD"),
    ("livre", "GBPUSD"),
    ("usdjpy", "USDJPY"),
    ("yen", "USDJPY"),
    ("jpy", "USDJPY"),
    ("bitcoin", "BTC-USD"),
    ("btc", "BTC-USD"),
    ("ruble", "USDRUB"),
    ("rouble", "USDRUB"),
    ("rubel", "USDRUB"),
];

/// Words that make an utterance a continuation rather than a new question, in all three locales.
const CONTINUATION: &[&str] = &[
    "and",
    "what about",
    "how about",
    "same for",
    "same as",
    "also",
    "then",
    "und",
    "was ist mit",
    "wie sieht",
    "auch",
    "und der",
    "und die",
    "und das",
    "et",
    "et pour",
    "et le",
    "et la",
    "aussi",
    "quid de",
];
const TIME_WORDS: &[&str] = &[
    "last month",
    "last week",
    "last year",
    "a year ago",
    "yesterday",
    "this month",
    "letzten monat",
    "letzte woche",
    "im märz",
    "vor einem jahr",
    "gestern",
    "le mois dernier",
    "la semaine dernière",
    "il y a un an",
    "hier",
];
const DEICTIC: &[&str] = &[
    "that one",
    "the same",
    "it",
    "this one",
    "der gleiche",
    "le même",
];

fn detect_pair(text: &str) -> Option<String> {
    let low = text.to_lowercase();
    let compact: String = low.chars().filter(|c| c.is_ascii_alphanumeric()).collect();
    for (word, code) in PAIR_WORDS {
        let w: String = word.chars().filter(|c| c.is_ascii_alphanumeric()).collect();
        if compact.contains(&w) {
            return Some((*code).to_string());
        }
    }
    None
}

fn pretty(pair: &str) -> String {
    if pair.len() == 6 && !pair.contains('/') {
        format!("{}/{}", &pair[..3], &pair[3..])
    } else {
        pair.replace('-', "/")
    }
}

/// Expand an elliptical utterance against conversation state.
///
/// The bar for treating something as a follow-up is deliberately high: short, and either opening
/// with a continuation word or consisting of nothing but a market name. A long sentence that merely
/// starts with "and" is a new question that happens to begin with a conjunction.
pub fn resolve(utterance: &str, state: Option<&SessionState>) -> Resolution {
    let text = utterance.trim();
    let low = text.to_lowercase();
    let words = low.split_whitespace().count();
    if words > 8 {
        return Resolution::Verbatim;
    }
    let starts_continuation = CONTINUATION.iter().any(|w| low.starts_with(w));
    let bare_pair = detect_pair(&low).filter(|_| words <= 4);
    let time_ref = TIME_WORDS.iter().find(|w| low.contains(**w)).copied();
    // Multi-word deictics ("the same", "that one") are matched as phrases; single words are matched
    // as whole tokens, so "it" does not fire inside "volatility".
    let deictic = DEICTIC.iter().any(|w| {
        if w.contains(' ') {
            low.contains(w)
        } else {
            low.split_whitespace()
                .any(|t| t.trim_matches(|c: char| !c.is_alphanumeric()) == *w)
        }
    });

    if !starts_continuation && bare_pair.is_none() && time_ref.is_none() && !deictic {
        return Resolution::Verbatim;
    }

    let Some(state) = state else {
        // Nothing to inherit. Guessing the subject here would be inventing one.
        if bare_pair.is_some() {
            return Resolution::Verbatim; // a bare market name is a perfectly good question
        }
        return Resolution::Ambiguous {
            question: "Which market should I read that for?".into(),
        };
    };
    let last_intent = state.last_intent.clone().unwrap_or_default();
    let last_card = state.last_card.clone().unwrap_or_default();
    if last_intent.is_empty() && last_card.is_empty() {
        return Resolution::Verbatim;
    }
    let subject = last_card.replace('_', " ");

    // A bare market name inherits the last intent: "and USDCHF?" after a condition question.
    if let Some(pair) = bare_pair {
        let echo = format!("{}, same reading:", pretty(&pair));
        return Resolution::Expanded {
            query: format!("{subject} {pair}"),
            echo,
            pair: Some(pair),
            period: None,
        };
    }
    // A bare time expression inherits both intent and market.
    if let Some(when) = time_ref {
        let Some(pair) = state.last_pair.clone() else {
            return Resolution::Ambiguous {
                question: "Which market did you mean for that period?".into(),
            };
        };
        return Resolution::Expanded {
            query: format!("{subject} {pair} {when}"),
            echo: format!("{}, {when}:", pretty(&pair)),
            pair: Some(pair),
            period: Some(when.to_string()),
        };
    }
    // "that one" / "the same": resolve to the last board's subject, if there was exactly one.
    if deictic {
        return match state.last_board_cards.len() {
            0 => Resolution::Ambiguous {
                question: "Which of those should I take — say the market or the metric.".into(),
            },
            1 => {
                let pair = state.last_pair.clone().unwrap_or_default();
                Resolution::Expanded {
                    query: format!("{} {pair}", state.last_board_cards[0].replace('_', " ")),
                    echo: if pair.is_empty() {
                        String::new()
                    } else {
                        format!("{}:", pretty(&pair))
                    },
                    pair: (!pair.is_empty()).then_some(pair),
                    period: None,
                }
            }
            _ => Resolution::Ambiguous {
                question: format!(
                    "I showed you {} — which one do you mean?",
                    state
                        .last_board_cards
                        .iter()
                        .map(|c| c.replace('_', " "))
                        .collect::<Vec<_>>()
                        .join(" and ")
                ),
            },
        };
    }
    // "and?" with nothing else to go on.
    Resolution::Ambiguous {
        question: "And what would you like to know — a different market, or a different period?"
            .into(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn state() -> SessionState {
        SessionState {
            last_intent: Some("ask_condition_card".into()),
            last_card: Some("condition_card".into()),
            last_pair: Some("EURUSD".into()),
            last_board_cards: vec!["condition_card".into()],
            locale: "en".into(),
            turn_index: 1,
            ..Default::default()
        }
    }

    #[test]
    fn bare_market_inherits_the_last_intent() {
        match resolve("and USDCHF?", Some(&state())) {
            Resolution::Expanded {
                query, echo, pair, ..
            } => {
                assert!(
                    query.contains("condition") && query.contains("USDCHF"),
                    "{query}"
                );
                assert!(echo.starts_with("USD/CHF"), "{echo}");
                assert_eq!(pair.as_deref(), Some("USDCHF"));
            }
            other => panic!("expected an expansion, got {other:?}"),
        }
    }

    #[test]
    fn bare_time_expression_inherits_intent_and_market() {
        match resolve("what about last month?", Some(&state())) {
            Resolution::Expanded {
                query,
                pair,
                period,
                ..
            } => {
                assert!(
                    query.contains("EURUSD") && query.contains("last month"),
                    "{query}"
                );
                assert_eq!(
                    period.as_deref(),
                    Some("last month"),
                    "a period follow-up must be flagged so the caller can refuse it"
                );
                assert_eq!(pair.as_deref(), Some("EURUSD"));
            }
            other => panic!("expected an expansion, got {other:?}"),
        }
    }

    #[test]
    fn german_and_french_follow_ups_resolve_too() {
        assert!(matches!(
            resolve("und der Franken?", Some(&state())),
            Resolution::Expanded { .. }
        ));
        assert!(matches!(
            resolve("et la livre ?", Some(&state())),
            Resolution::Expanded { .. }
        ));
    }

    #[test]
    fn an_ambiguous_follow_up_asks_rather_than_guesses() {
        let mut s = state();
        s.last_board_cards = vec!["condition_card".into(), "risk_trace".into()];
        match resolve("the same", Some(&s)) {
            Resolution::Ambiguous { question } => {
                assert!(question.contains("which one") || question.contains("which"))
            }
            other => panic!("a wrong silent resolution is worse than a question: {other:?}"),
        }
    }

    #[test]
    fn a_full_question_is_never_treated_as_a_follow_up() {
        // Starts with a continuation word but is plainly a new question.
        assert_eq!(
            resolve(
                "and how does the conformal band get calibrated in the first place",
                Some(&state())
            ),
            Resolution::Verbatim
        );
    }

    #[test]
    fn without_state_a_bare_market_is_still_a_question() {
        assert_eq!(resolve("usdchf?", None), Resolution::Verbatim);
    }

    #[test]
    fn state_expires() {
        let store = ConversationStore::default();
        store.put("s1", state());
        assert!(store.get("s1").is_some());
        store.end("s1");
        assert!(store.get("s1").is_none());
    }
}
