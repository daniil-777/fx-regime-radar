//! Request slips: a constrained address into the archive, never a query (phase 42).
//!
//! **This is deliberately not the open-ended search agent.** Phase 42 says to build one only if the
//! historical, multi-hop and aggregation families are still failing after phase 41. They are not —
//! 81%, 86%, 92% and 82% — and `reports/retrieval_ablation.md` records the decision and the
//! evidence. What is built here is the discipline the phase specifies around the archive that
//! already answers those questions: a slip whose every field is constrained, a point-in-time
//! guarantee, and defined semantics for the four ways a result can be empty.
//!
//! The reason a slip beats a query is not safety theatre. A model that can write SQL can write a
//! query that RUNS and is WRONG — right syntax, wrong window, plausible number, no error anywhere.
//! A slip cannot express a wrong query, only an unavailable one, and unavailable is a case the
//! server answers rather than a mistake it commits.
//!
//! Constraining string fields matters as much as banning numeric types, and the test says so with
//! `"14"`, `"1e3"` and `"0.68"`: a model that cannot emit the integer 14 can still try to emit the
//! string "14", and a field that accepts free text accepts everything.

use serde::{Deserialize, Serialize};

/// Which room a slip addresses. Five, and the callable surface stays under eight by design.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Room {
    /// Precomputed aggregates — always tried first, because it is a lookup.
    Cube,
    /// Daily history for the majors, monthly elsewhere. The fallback the SERVER chooses.
    Archive,
    /// Sealed forecast rows. Never recomputed, only read.
    Logbook,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Aggregation {
    Latest,
    Mean,
    Max,
    Min,
    Count,
    CountWhereRegime,
    RunLength,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Regime {
    Calm,
    Trend,
    Chop,
    Crisis,
    Any,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Metric {
    Regime,
    ChangeRisk,
    Siren,
    Consensus,
    Volatility,
    Forecasts,
}

/// The slip. Every field is an enum or a pattern-validated string; none accepts free text.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Slip {
    pub room: Room,
    pub metric: Metric,
    /// Pattern-validated: a market code from the published set, never arbitrary text.
    pub pair: String,
    pub aggregation: Aggregation,
    #[serde(default)]
    pub regime: Option<Regime>,
    /// ISO date or `YYYY-MM` or `YYYY`, regex-shaped and range-bounded.
    #[serde(default)]
    pub date_range: Option<String>,
    /// The point in time the answer must be true AS OF. A correctness property, not a filter:
    /// without it, a question about last March can silently be answered with data published after
    /// March, which is indistinguishable from a correct answer and wrong in the way that matters.
    #[serde(default)]
    pub as_of: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub enum SlipError {
    UnknownPair(String),
    BadDate(String),
    OutOfRange(String),
    NumericString(String),
}

impl std::fmt::Display for SlipError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            SlipError::UnknownPair(p) => write!(f, "pair {p:?} is not a published market"),
            SlipError::BadDate(d) => write!(f, "date {d:?} is not an ISO date, month or year"),
            SlipError::OutOfRange(d) => write!(f, "date {d:?} is outside the archive's range"),
            SlipError::NumericString(v) => {
                write!(
                    f,
                    "field received the numeric string {v:?}; values never come from the model"
                )
            }
        }
    }
}

const PUBLISHED_PAIRS: [&str; 6] = ["EURUSD", "USDCHF", "GBPUSD", "USDJPY", "USDRUB", "BTC-USD"];
const EARLIEST: &str = "2005-01-01";

/// Is this string a bare number wearing quotes? The case a "no numeric types" schema misses.
pub fn looks_numeric(value: &str) -> bool {
    let t = value.trim();
    if t.is_empty() {
        return false;
    }
    t.parse::<f64>().is_ok()
}

fn valid_date_shape(value: &str) -> bool {
    let parts: Vec<&str> = value.split('-').collect();
    match parts.len() {
        1 => parts[0].len() == 4 && parts[0].chars().all(|c| c.is_ascii_digit()),
        2 => {
            parts[0].len() == 4
                && parts[1].len() == 2
                && parts.iter().all(|p| p.chars().all(|c| c.is_ascii_digit()))
        }
        3 => {
            parts[0].len() == 4
                && parts[1].len() == 2
                && parts[2].len() == 2
                && parts.iter().all(|p| p.chars().all(|c| c.is_ascii_digit()))
        }
        _ => false,
    }
}

impl Slip {
    /// Validate every field. Rejection is the point: an invalid slip is a case the caller handles,
    /// not a query that runs against the wrong window.
    pub fn validate(&self, latest: &str) -> Result<(), SlipError> {
        if looks_numeric(&self.pair) {
            return Err(SlipError::NumericString(self.pair.clone()));
        }
        if !PUBLISHED_PAIRS.contains(&self.pair.as_str()) {
            return Err(SlipError::UnknownPair(self.pair.clone()));
        }
        for (field, value) in [("date_range", &self.date_range), ("as_of", &self.as_of)] {
            let Some(value) = value else { continue };
            if looks_numeric(value) && !valid_date_shape(value) {
                // "14", "1e3", "0.68" — a year is four digits, and nothing else numeric is a date.
                return Err(SlipError::NumericString(format!("{field}={value}")));
            }
            if !valid_date_shape(value) {
                return Err(SlipError::BadDate(value.clone()));
            }
            if value.as_str() < EARLIEST || value.as_str() > latest {
                return Err(SlipError::OutOfRange(value.clone()));
            }
        }
        Ok(())
    }
}

/// The four ways a result can be empty. Each is an ANSWER with its own wording — never an error,
/// and never silently the same as the others.
#[derive(Debug, Clone, PartialEq)]
pub enum Empty {
    /// The record does not reach back that far.
    NoDataYet { begins: String, asked: String },
    /// Markets were closed; we resolve to the prior trading day and SAY so.
    NotATradingDay { asked: String, used: String },
    /// The shape is real but this range is not covered by what we can read in a conversation.
    OutsideCoverage { what: String },
    /// Zero is a finding. "No crisis days this year" is an answer, and reporting it as an error
    /// would tell the user something false about the market.
    GenuinelyZero { what: String },
}

impl Empty {
    pub fn say(&self) -> String {
        match self {
            Empty::NoDataYet { begins, asked } => format!(
                "My record begins on {begins}; I have nothing for {asked}."
            ),
            Empty::NotATradingDay { asked, used } => format!(
                "{asked} was not a trading day, so I read {used}, the trading day before it."
            ),
            Empty::OutsideCoverage { what } => format!(
                "I hold {what} at a coarser grain than that question needs — the dashboard's Storms \
                 and Proof pages go deeper than I can inside a conversation."
            ),
            Empty::GenuinelyZero { what } => format!("None: {what}."),
        }
    }

    pub fn kind(&self) -> &'static str {
        match self {
            Empty::NoDataYet { .. } => "no_data_yet",
            Empty::NotATradingDay { .. } => "not_a_trading_day",
            Empty::OutsideCoverage { .. } => "outside_coverage",
            Empty::GenuinelyZero { .. } => "genuinely_zero",
        }
    }
}

/// Which lane a turn took, and what decided it. Logged so precedence conflicts are measurable
/// rather than anecdotal.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Lane {
    Guard,
    Archive,
    Pack,
    Template,
    Visual,
    Refusal,
}

impl Lane {
    pub fn as_str(&self) -> &'static str {
        match self {
            Lane::Guard => "guard",
            Lane::Archive => "archive",
            Lane::Pack => "pack",
            Lane::Template => "template",
            Lane::Visual => "visual",
            Lane::Refusal => "refusal",
        }
    }
}

/// Does this utterance carry data the packs cannot contain?
///
/// The pre-router OUTRANKS a confident classifier on these patterns, and that precedence is the
/// point: a pack is a snapshot of today, so a question naming a date, a count or a comparison is
/// asking for something no pack can hold, however confidently an intent was recognised.
pub fn pre_router_wants_archive(q_lower: &str) -> bool {
    const PATTERNS: [&str; 14] = [
        "how many",
        "compare",
        "since",
        "last year",
        "last month",
        "what did you say",
        "during",
        "in 20",
        "a year ago",
        "a month ago",
        "usually",
        "typically",
        "was the",
        "history",
    ];
    PATTERNS.iter().any(|p| q_lower.contains(p))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn slip(pair: &str) -> Slip {
        Slip {
            room: Room::Archive,
            metric: Metric::Regime,
            pair: pair.into(),
            aggregation: Aggregation::Latest,
            regime: None,
            date_range: None,
            as_of: None,
        }
    }

    #[test]
    fn a_numeric_string_is_rejected_rather_than_coerced() {
        // The case a "no numeric types" schema misses entirely: a model that cannot emit 14 can
        // still emit "14", and a field that quietly parses it has re-opened the hole.
        for value in ["14", "1e3", "0.68"] {
            let mut s = slip("EURUSD");
            s.date_range = Some(value.to_string());
            let err = s.validate("2026-08-20").unwrap_err();
            assert!(
                matches!(err, SlipError::NumericString(_)),
                "{value} should be rejected as a numeric string, got {err}"
            );
            let numeric_pair = slip(value);
            assert!(matches!(
                numeric_pair.validate("2026-08-20").unwrap_err(),
                SlipError::NumericString(_)
            ));
        }
    }

    #[test]
    fn a_four_digit_year_is_a_date_not_a_number() {
        let mut s = slip("EURUSD");
        s.date_range = Some("2015".into());
        assert!(
            s.validate("2026-08-20").is_ok(),
            "a year must remain addressable"
        );
    }

    #[test]
    fn unknown_markets_and_out_of_range_dates_are_refused() {
        assert!(matches!(
            slip("XAUUSD").validate("2026-08-20").unwrap_err(),
            SlipError::UnknownPair(_)
        ));
        let mut s = slip("EURUSD");
        s.as_of = Some("2099-01-01".into());
        assert!(matches!(
            s.validate("2026-08-20").unwrap_err(),
            SlipError::OutOfRange(_)
        ));
        s.as_of = Some("1998-01-01".into());
        assert!(matches!(
            s.validate("2026-08-20").unwrap_err(),
            SlipError::OutOfRange(_)
        ));
    }

    #[test]
    fn every_empty_kind_says_something_different_and_true() {
        let cases = [
            Empty::NoDataYet {
                begins: "2011-01-03".into(),
                asked: "March 2008".into(),
            },
            Empty::NotATradingDay {
                asked: "2026-08-16".into(),
                used: "2026-08-14".into(),
            },
            Empty::OutsideCoverage {
                what: "the zloty".into(),
            },
            Empty::GenuinelyZero {
                what: "EUR/USD had no crisis days in 2026".into(),
            },
        ];
        let said: Vec<String> = cases.iter().map(|c| c.say()).collect();
        for text in &said {
            assert!(!text.is_empty());
            assert!(
                !text.to_lowercase().contains("error"),
                "empty is an answer, not an error"
            );
        }
        // and each is distinguishable from the others
        for i in 0..said.len() {
            for j in (i + 1)..said.len() {
                assert_ne!(said[i], said[j]);
            }
        }
        assert!(
            said[1].contains("trading day before"),
            "a date shift must be stated: {}",
            said[1]
        );
        assert!(
            said[3].starts_with("None:"),
            "zero is a finding: {}",
            said[3]
        );
    }

    #[test]
    fn the_pre_router_outranks_a_confident_intent_on_date_bearing_questions() {
        assert!(pre_router_wants_archive("how many crisis days last year"));
        assert!(pre_router_wants_archive("compare today against march"));
        assert!(pre_router_wants_archive("what did you say in 2015"));
        // ...and leaves today's questions alone, or the slow lane becomes the design.
        assert!(!pre_router_wants_archive("how does eurusd look today"));
        assert!(!pre_router_wants_archive("siren?"));
    }
}
