//! The archive room: history and aggregates, answered from a closed set of shapes.
//!
//! Built in response to a measured failure rather than a plan. An audit asked the assistant
//! twenty-two ordinary financial questions and found that eighteen returned `gate pass` while only
//! about six actually answered what was asked. "How many crisis days has EUR/USD had this year?"
//! returned a picture of today. "What was the regime on 15 January 2015?" returned a malformed
//! caption. Nothing was fabricated — the grounding gate held throughout — but a confident
//! non-answer is worse than a refusal, because the user cannot tell the question was never
//! addressed, and no metric that counts gates will ever show it.
//!
//! The design principle is precedence, not cleverness. A question is matched against a small set of
//! SHAPES — count today, regime on a date, days in a regime over a period, typical duration,
//! compare two periods, event window. If it matches a shape, it is answered exactly from
//! `data/archive.json`. If it looks historical or aggregate but matches no shape, the caller must
//! REFUSE rather than fall through to a card about today. That refusal is the whole point: an
//! archive that admits its edges is worth more than one that improvises past them.

use serde::Deserialize;
use std::collections::HashMap;
use std::path::Path;

#[derive(Deserialize, Clone, Debug, Default)]
pub struct PairHistory {
    #[serde(default)]
    pub months: HashMap<String, HashMap<String, i64>>,
    #[serde(default)]
    pub years: HashMap<String, HashMap<String, i64>>,
    #[serde(default)]
    pub daily: HashMap<String, String>,
    #[serde(default)]
    pub daily_risk: HashMap<String, Option<f64>>,
    #[serde(default)]
    pub daily_siren: HashMap<String, Option<f64>>,
    #[serde(default)]
    pub first_date: String,
    #[serde(default)]
    pub last_date: String,
}

#[derive(Deserialize, Clone, Debug, Default)]
pub struct RunStats {
    pub episodes: i64,
    pub mean_days: f64,
    pub median_days: f64,
    pub longest_days: i64,
}

#[derive(Deserialize, Clone, Debug, Default)]
pub struct EventStats {
    #[serde(default)]
    pub pairs: HashMap<String, EventPairStats>,
    #[serde(default)]
    pub n_events: i64,
}

#[derive(Deserialize, Clone, Debug, Default)]
pub struct EventPairStats {
    #[serde(default)]
    pub mean_change_risk_before: Option<f64>,
    #[serde(default)]
    pub mean_change_risk_after: Option<f64>,
}

#[derive(Deserialize, Clone, Debug, Default)]
pub struct Episode {
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub pair: String,
    #[serde(default)]
    pub start: String,
    #[serde(default)]
    pub end: String,
}

#[derive(Deserialize, Clone, Debug, Default)]
pub struct TodayReading {
    #[serde(default)]
    pub regime: String,
    #[serde(default)]
    pub risk: Option<f64>,
    #[serde(default)]
    pub siren: Option<f64>,
}

#[derive(Deserialize, Clone, Debug, Default)]
pub struct LedgerTotals {
    #[serde(default)]
    pub days_live: Option<i64>,
    #[serde(default)]
    pub n_forecasts: Option<i64>,
    #[serde(default)]
    pub n_resolved: Option<i64>,
    #[serde(default)]
    pub chain_head_short: Option<String>,
    #[serde(default)]
    pub live_brier: Option<f64>,
    #[serde(default)]
    pub frozen_brier: Option<f64>,
}

#[derive(Deserialize, Clone, Debug, Default)]
pub struct Archive {
    #[serde(default)]
    pub ledger: LedgerTotals,
    #[serde(default)]
    pub today: HashMap<String, TodayReading>,
    #[serde(default)]
    pub data_through: String,
    #[serde(default)]
    pub daily_pairs: Vec<String>,
    #[serde(default)]
    pub markets_total: i64,
    #[serde(default)]
    pub counts_today: HashMap<String, i64>,
    #[serde(default)]
    pub by_regime_today: HashMap<String, Vec<String>>,
    #[serde(default)]
    pub pairs: HashMap<String, PairHistory>,
    #[serde(default)]
    pub runs: HashMap<String, HashMap<String, RunStats>>,
    #[serde(default)]
    pub events: HashMap<String, EventStats>,
    #[serde(default)]
    pub episodes: HashMap<String, Episode>,
}

pub fn load(path: &Path) -> Result<Archive, String> {
    let raw = std::fs::read_to_string(path).map_err(|e| format!("archive unreadable: {e}"))?;
    serde_json::from_str(&raw).map_err(|e| format!("archive is not valid JSON: {e}"))
}

const REGIMES: [&str; 4] = ["calm", "trend", "chop", "crisis"];
const MONTHS: [(&str, u32); 12] = [
    ("january", 1),
    ("february", 2),
    ("march", 3),
    ("april", 4),
    ("may", 5),
    ("june", 6),
    ("july", 7),
    ("august", 8),
    ("september", 9),
    ("october", 10),
    ("november", 11),
    ("december", 12),
];

/// Does this question belong to the archive at all? Used by the caller to decide that a card about
/// today would be the wrong answer — the difference between "I cannot" and a confident irrelevance.
pub fn looks_historical(q_lower: &str) -> bool {
    // Two tiers, because a single list was too eager. "How many alerts do I get per flip?" is a
    // product question that happens to start with "how many" — routing it to the archive and then
    // refusing it REMOVED an answer the FAQ was already giving. A capability that takes away a
    // working answer is a net loss however good its own numbers look.
    const ALWAYS: [&str; 12] = [
        "last month",
        "last week",
        "last year",
        "a year ago",
        "a month ago",
        "back in",
        "in 20",
        "during",
        "history",
        "since",
        "this year",
        "was the",
    ];
    if ALWAYS.iter().any(|m| q_lower.contains(m)) {
        return true;
    }
    const NEEDS_SUBJECT: [&str; 8] = [
        "how many",
        "how often",
        "how long",
        "usually",
        "typically",
        "on average",
        "compared to",
        "versus",
    ];
    const SUBJECT: [&str; 13] = [
        "regime",
        "risk",
        "siren",
        "crisis",
        "calm",
        "chop",
        "trend",
        "volatility",
        "day",
        "days",
        "market",
        "forecast",
        "episode",
    ];
    NEEDS_SUBJECT.iter().any(|m| q_lower.contains(m)) && SUBJECT.iter().any(|w| q_lower.contains(w))
}

fn detect_pair(q: &str) -> Option<String> {
    const WORDS: [(&str, &str); 14] = [
        ("eurusd", "EURUSD"),
        ("eur/usd", "EURUSD"),
        ("euro", "EURUSD"),
        ("usdchf", "USDCHF"),
        ("usd/chf", "USDCHF"),
        ("franc", "USDCHF"),
        ("swissie", "USDCHF"),
        ("chf", "USDCHF"),
        ("gbpusd", "GBPUSD"),
        ("gbp/usd", "GBPUSD"),
        ("sterling", "GBPUSD"),
        ("cable", "GBPUSD"),
        ("pound", "GBPUSD"),
        ("livre", "GBPUSD"),
    ];
    let compact: String = q.chars().filter(|c| c.is_ascii_alphanumeric()).collect();
    for (word, code) in WORDS {
        let w: String = word.chars().filter(|c| c.is_ascii_alphanumeric()).collect();
        if compact.contains(&w) {
            return Some(code.to_string());
        }
    }
    None
}

/// Is the question about a NUMBER OF DAYS, rather than merely containing the word "today"?
fn mentions_days(q: &str) -> bool {
    q.split(|c: char| !c.is_alphanumeric())
        .any(|w| w == "day" || w == "days")
}

fn detect_regime(q: &str) -> Option<&'static str> {
    REGIMES.iter().find(|r| q.contains(**r)).copied()
}

fn pretty(pair: &str) -> String {
    if pair.len() == 6 {
        format!("{}/{}", &pair[..3], &pair[3..])
    } else {
        pair.replace('-', "/")
    }
}

/// "15 january 2015" | "january 2015" | "2015-01-15" | "march 2020" → (YYYY-MM-DD, YYYY-MM, YYYY)
fn detect_date(q: &str) -> (Option<String>, Option<String>, Option<String>) {
    // ISO first: unambiguous, and the form the ledger itself uses.
    let bytes: Vec<char> = q.chars().collect();
    for i in 0..bytes.len().saturating_sub(9) {
        let window: String = bytes[i..i + 10].iter().collect();
        if window.len() == 10
            && window.chars().enumerate().all(|(k, c)| {
                if k == 4 || k == 7 {
                    c == '-'
                } else {
                    c.is_ascii_digit()
                }
            })
        {
            return (
                Some(window.clone()),
                Some(window[..7].to_string()),
                Some(window[..4].to_string()),
            );
        }
    }
    let year = (1990..=2100)
        .map(|y| y.to_string())
        .find(|y| q.contains(y.as_str()));
    let month = MONTHS.iter().find(|(name, _)| q.contains(*name));
    match (&year, month) {
        (Some(y), Some((_, m))) => {
            // a day number sitting next to the month name, if there is one
            let day = q
                .split(|c: char| !c.is_ascii_digit())
                .filter(|t| !t.is_empty() && t.len() <= 2)
                .filter_map(|t| t.parse::<u32>().ok())
                .find(|d| (1..=31).contains(d));
            let ym = format!("{y}-{m:02}");
            (
                day.map(|d| format!("{ym}-{d:02}")),
                Some(ym),
                Some(y.clone()),
            )
        }
        (Some(y), None) => (None, None, Some(y.clone())),
        _ => (None, None, None),
    }
}

/// The answer, plus the shape that produced it, so the caller can record provenance.
#[derive(Debug, Clone, PartialEq)]
pub struct ArchiveAnswer {
    pub text: String,
    pub shape: &'static str,
}

/// Answer from the archive, or return None so the caller can refuse honestly.
pub fn answer(archive: &Archive, q_lower: &str) -> Option<ArchiveAnswer> {
    let q = q_lower;

    // --- shape 1: how many markets are in a regime right now -------------------------------------
    if (q.contains("how many") || q.contains("anything") || q.contains("any market"))
        && (q.contains("market")
            || q.contains("pair")
            || q.contains("board")
            || q.contains("of the"))
        && !mentions_days(q)
    // "today" contains "day": a substring test answers the wrong shape
    {
        if let Some(regime) = detect_regime(q) {
            let names = archive
                .by_regime_today
                .get(regime)
                .cloned()
                .unwrap_or_default();
            let n = names.len();
            if n == 0 {
                return Some(ArchiveAnswer {
                    text: format!(
                        "None of the {} markets is in {regime} today.",
                        archive.markets_total
                    ),
                    shape: "count_today",
                });
            }
            let listed: Vec<String> = names.iter().take(6).map(|p| pretty(p)).collect();
            return Some(ArchiveAnswer {
                text: format!(
                    "{n} of {} markets {} {regime} today: {}{}.",
                    archive.markets_total,
                    if n == 1 { "is" } else { "are" },
                    listed.join(", "),
                    if names.len() > listed.len() {
                        " and others"
                    } else {
                        ""
                    }
                ),
                shape: "count_today",
            });
        }
    }

    // --- shape 2: what was the regime on a given date ---------------------------------------------
    let (day, month, year) = detect_date(q);
    if let Some(date) = day.clone() {
        let pair = detect_pair(q).unwrap_or_else(|| "EURUSD".into());
        if let Some(hist) = archive.pairs.get(&pair) {
            if let Some(regime) = hist.daily.get(&date) {
                let risk = hist.daily_risk.get(&date).and_then(|v| *v);
                let siren = hist.daily_siren.get(&date).and_then(|v| *v);
                let mut text = format!("On {date}, {} was {regime}", pretty(&pair));
                if let Some(r) = risk {
                    text.push_str(&format!(", change risk {r:.2}"));
                }
                if let Some(s) = siren {
                    text.push_str(&format!(", siren {s:.0}"));
                }
                text.push('.');
                return Some(ArchiveAnswer {
                    text,
                    shape: "regime_on_date",
                });
            }
            // The date is outside what the archive holds — say which, rather than guessing.
            return Some(ArchiveAnswer {
                text: format!(
                    "I do not hold {} for {date}. My daily history runs from {} to {}.",
                    pretty(&pair),
                    hist.first_date,
                    hist.last_date
                ),
                shape: "regime_on_date_missing",
            });
        }
    }

    // --- shape 3: days in a regime over a month or a year -----------------------------------------
    if q.contains("how many") && mentions_days(q) {
        if let Some(regime) = detect_regime(q) {
            let pair = detect_pair(q).unwrap_or_else(|| "EURUSD".into());
            if let Some(hist) = archive.pairs.get(&pair) {
                if let Some(m) = month.clone() {
                    let n = hist
                        .months
                        .get(&m)
                        .and_then(|c| c.get(regime))
                        .copied()
                        .unwrap_or(0);
                    return Some(ArchiveAnswer {
                        text: format!(
                            "{} spent {n} trading days in {regime} during {m}.",
                            pretty(&pair)
                        ),
                        shape: "regime_days_month",
                    });
                }
                let y = year
                    .clone()
                    .unwrap_or_else(|| archive.data_through.get(..4).unwrap_or("").to_string());
                let n = hist
                    .years
                    .get(&y)
                    .and_then(|c| c.get(regime))
                    .copied()
                    .unwrap_or(0);
                let total: i64 = hist.years.get(&y).map(|c| c.values().sum()).unwrap_or(0);
                return Some(ArchiveAnswer {
                    text: format!(
                        "{} spent {n} of {total} trading days in {regime} during {y}.",
                        pretty(&pair)
                    ),
                    shape: "regime_days_year",
                });
            }
        }
    }

    // --- shape 4: how long a regime usually lasts -------------------------------------------------
    if (q.contains("how long")
        || q.contains("usually")
        || q.contains("typically")
        || q.contains("on average"))
        && (q.contains("last")
            || q.contains("regime")
            || q.contains("episode")
            || q.contains("storm")
            || detect_regime(q).is_some())
    {
        if let Some(regime) = detect_regime(q) {
            let pair = detect_pair(q).unwrap_or_else(|| "EURUSD".into());
            if let Some(stats) = archive.runs.get(&pair).and_then(|m| m.get(regime)) {
                return Some(ArchiveAnswer {
                    text: format!(
                        "Across {} episodes of {regime} in {}, the median lasted {:.0} trading days \
                         and the longest ran {}.",
                        stats.episodes,
                        pretty(&pair),
                        stats.median_days,
                        stats.longest_days
                    ),
                    shape: "regime_duration",
                });
            }
        }
    }

    // --- shape 5: what usually happens around an event --------------------------------------------
    for (name, stats) in &archive.events {
        let lower = name.to_lowercase();
        if q.contains(&lower) {
            let pair = detect_pair(q).unwrap_or_else(|| "EURUSD".into());
            // "how do markets behave on CPI days" names no market; averaging across the ones we
            // have beats falling through to a card about today.
            let fallback = stats.pairs.values().next();
            if let Some(p) = stats.pairs.get(&pair).or(fallback) {
                if let (Some(before), Some(after)) =
                    (p.mean_change_risk_before, p.mean_change_risk_after)
                {
                    return Some(ArchiveAnswer {
                        text: format!(
                            "Around {name} decisions, {} averaged change risk {before:.2} in the five \
                             days before and {after:.2} in the five after, over {} events. That is a \
                             description of conditions, not a forecast.",
                            pretty(&pair),
                            stats.n_events
                        ),
                        shape: "event_window",
                    });
                }
            }
        }
    }

    // --- shape 11: how much of a record there is ---------------------------------------------------
    // Added after this module caused a REGRESSION: "how many forecasts have you sealed" starts with
    // "how many", so it was routed here and refused, when the previous path answered it. A new
    // capability that removes an old answer is a net loss, whatever the metrics say.
    if (q.contains("how many") || q.contains("how long"))
        && (q.contains("forecast")
            || q.contains("sealed")
            || q.contains("record")
            || q.contains("ledger")
            || q.contains("live"))
    {
        let l = &archive.ledger;
        if let Some(n) = l.n_forecasts {
            let mut text = format!("{n} forecasts are sealed in the ledger");
            if let Some(days) = l.days_live {
                text.push_str(&format!(", over {days} days live"));
            }
            if let Some(resolved) = l.n_resolved {
                text.push_str(&format!("; {resolved} have matured"));
            }
            if let Some(head) = &l.chain_head_short {
                text.push_str(&format!(". Chain head {head}"));
            }
            text.push('.');
            return Some(ArchiveAnswer {
                text,
                shape: "ledger_totals",
            });
        }
    }

    // --- shape 9: which market is the most / least X today ----------------------------------------
    // The audit's multi-hop questions ("which has the highest siren, and is it also the riskiest?")
    // failed because answering them meant chaining two lookups. The archive holds today's reading
    // for every market, so the chain is one pass here rather than an agent loop.
    // A ranking question asks ACROSS markets. If the user named one, they are asking about it —
    // "which state is GBPUSD most likely in right now?" was being answered with "USD/CHF has the
    // highest risk", which is not so much a worse answer as a different question.
    let names_one_market = detect_pair(q).is_some();
    let asks_across = q.contains("which market")
        || q.contains("which pair")
        || q.contains("which of")
        || q.contains("markets")
        || q.contains("pairs")
        || q.contains("board");
    let ranking = (asks_across || !names_one_market) && !q.contains("most likely");
    let wants_max = ranking
        && (q.contains("highest")
            || q.contains("most")
            || q.contains("worst")
            || q.contains("riskiest")
            || q.contains("least calm"));
    let wants_min = ranking
        && (q.contains("lowest")
            || q.contains("calmest")
            || q.contains("least risky")
            || q.contains("quietest"));
    // ...but only about TODAY. "The worst week this year" is a time-series question, and answering
    // it with today's ranking is precisely the adjacent-answer failure this module exists to end —
    // caught here by its own test rather than by a user.
    let about_a_period = [
        "week", "month", "quarter", "year", "during", "history", "ever",
    ]
    .iter()
    .any(|w| q.contains(w))
        && !q.contains("today");
    // A condition we cannot apply ("of the markets WITH AN EVENT within 10 days…") must stop this
    // shape. Answering the unfiltered version answers an easier question than the one asked, which
    // is the same failure as answering about today when asked about the past.
    let has_unappliable_filter = q.contains("with an event")
        || q.contains("with events")
        || q.contains("that have an event")
        || q.contains("among the")
        || q.contains("excluding")
        || q.contains("apart from");
    if (wants_max || wants_min)
        && !about_a_period
        && !has_unappliable_filter
        && !archive.today.is_empty()
    {
        let metric = if q.contains("siren") || q.contains("unusual") {
            "siren"
        } else {
            "risk"
        };
        let mut scored: Vec<(&String, f64)> = archive
            .today
            .iter()
            .filter_map(|(pair, r)| {
                let v = if metric == "siren" { r.siren } else { r.risk };
                v.map(|v| (pair, v))
            })
            .collect();
        if !scored.is_empty() {
            scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
            let (pair, value) = if wants_max {
                scored[0]
            } else {
                scored[scored.len() - 1]
            };
            let reading = &archive.today[pair];
            let shown = if metric == "siren" {
                format!("{value:.0}")
            } else {
                format!("{value:.2}")
            };
            let mut text = format!(
                "{} has the {} {metric} today at {shown}, and reads {}.",
                pretty(pair),
                if wants_max { "highest" } else { "lowest" },
                reading.regime
            );
            // The "and is it also…" half of the question, answered rather than ignored.
            if q.contains("also") || q.contains(" and ") {
                let other = if metric == "siren" { "risk" } else { "siren" };
                let mut alt: Vec<(&String, f64)> = archive
                    .today
                    .iter()
                    .filter_map(|(p, r)| {
                        let v = if other == "siren" { r.siren } else { r.risk };
                        v.map(|v| (p, v))
                    })
                    .collect();
                alt.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
                if let Some((top_other, ov)) = alt.first() {
                    let ov_shown = if other == "siren" {
                        format!("{ov:.0}")
                    } else {
                        format!("{ov:.2}")
                    };
                    text.push_str(&format!(
                        " The highest {other} is {} at {ov_shown}, so {}.",
                        pretty(top_other),
                        if *top_other == pair {
                            "it is the same market"
                        } else {
                            "they are different markets"
                        }
                    ));
                }
            }
            return Some(ArchiveAnswer {
                text,
                shape: "extreme_today",
            });
        }
    }

    // --- shape 10: an average across today's markets ----------------------------------------------
    // If the user asserted their own figures, answering with ours quietly substitutes one question
    // for another — and looks like agreement with numbers we never checked.
    let user_supplied_numbers = q.chars().any(|c| c.is_ascii_digit())
        && (q.contains("you've got")
            || q.contains("you have")
            || q.contains("you said")
            || q.contains("at 0.")
            || q.contains("is 0."));
    if (q.contains("average") || q.contains("mean ")) && !user_supplied_numbers {
        let metric = if q.contains("siren") { "siren" } else { "risk" };
        let majors = ["EURUSD", "USDCHF", "GBPUSD"];
        let only_majors = q.contains("major");
        let values: Vec<f64> = archive
            .today
            .iter()
            .filter(|(p, _)| !only_majors || majors.contains(&p.as_str()))
            .filter_map(|(_, r)| if metric == "siren" { r.siren } else { r.risk })
            .collect();
        if !values.is_empty() {
            let mean = values.iter().sum::<f64>() / values.len() as f64;
            return Some(ArchiveAnswer {
                text: format!(
                    "Across {} {} today, the average {metric} is {mean:.2}.",
                    values.len(),
                    if only_majors { "majors" } else { "markets" }
                ),
                shape: "average_today",
            });
        }
    }

    // --- shape 7: what a value WAS at some point in the past --------------------------------------
    if (q.contains("what was") || q.contains("what were") || q.contains("was the"))
        && (q.contains("risk") || q.contains("siren") || q.contains("regime"))
    {
        let pair = detect_pair(q).unwrap_or_else(|| "EURUSD".into());
        if let Some(hist) = archive.pairs.get(&pair) {
            let mut dates: Vec<&String> = hist.daily.keys().collect();
            dates.sort();
            let back = if q.contains("year ago") || q.contains("last year") {
                252
            } else if q.contains("week ago") || q.contains("last week") {
                5
            } else if q.contains("month ago") || q.contains("last month") {
                23
            } else {
                0
            };
            if back > 0 && dates.len() > back {
                let when = dates[dates.len() - 1 - back];
                let regime = hist.daily.get(when).cloned().unwrap_or_default();
                let risk = hist.daily_risk.get(when).and_then(|v| *v);
                let siren = hist.daily_siren.get(when).and_then(|v| *v);
                let mut text = format!("On {when}, {} was {regime}", pretty(&pair));
                if let Some(r) = risk {
                    text.push_str(&format!(", change risk {r:.2}"));
                }
                if let Some(sv) = siren {
                    text.push_str(&format!(", siren {sv:.0}"));
                }
                text.push('.');
                return Some(ArchiveAnswer {
                    text,
                    shape: "value_in_past",
                });
            }
        }
    }

    // --- shape 8: how a market behaved during a named episode -------------------------------------
    for (name, ep) in &archive.episodes {
        let needle = name.to_lowercase();
        // Match the whole key, or the key's distinctive TITLE — never a single generic word from
        // it. "credit_suisse_2023" matching on "suisse" answered a French question about Swiss
        // corporate taxation with a summary of the 2023 banking episode.
        let title = ep.title.to_lowercase();
        let distinctive: Vec<&str> = needle
            .split('_')
            .filter(|w| w.len() > 4 && !matches!(*w, "suisse" | "swiss" | "banks" | "bank"))
            .collect();
        let hit = q.contains(&needle)
            || (!title.is_empty() && q.contains(title.split(" — ").next().unwrap_or(&title)))
            || distinctive.iter().any(|w| q.contains(w));
        if !hit || ep.start.is_empty() {
            continue;
        }
        let pair = detect_pair(q).unwrap_or_else(|| ep.pair.clone());
        if let Some(hist) = archive.pairs.get(&pair) {
            let mut counts: HashMap<&str, i64> = HashMap::new();
            let mut peak = 0.0_f64;
            for (date, regime) in &hist.daily {
                if date.as_str() >= ep.start.as_str() && date.as_str() <= ep.end.as_str() {
                    *counts.entry(regime.as_str()).or_insert(0) += 1;
                    if let Some(Some(sv)) = hist.daily_siren.get(date) {
                        peak = peak.max(*sv);
                    }
                }
            }
            if !counts.is_empty() {
                let total: i64 = counts.values().sum();
                let mut parts: Vec<(&str, i64)> = counts.into_iter().collect();
                parts.sort_by_key(|(_, n)| -n);
                let breakdown: Vec<String> =
                    parts.iter().map(|(r, n)| format!("{n} {r}")).collect();
                return Some(ArchiveAnswer {
                    text: format!(
                        "Through {} ({} to {}), {} recorded {total} trading days: {}. The siren                          peaked at {peak:.0}.",
                        ep.title,
                        ep.start,
                        ep.end,
                        pretty(&pair),
                        breakdown.join(", ")
                    ),
                    shape: "episode_summary",
                });
            }
        }
    }

    // --- shape 6: compare today against a past period ----------------------------------------------
    if (q.contains("compared to")
        || q.contains("versus")
        || q.contains("vs ")
        || q.contains("higher than")
        || q.contains("lower than")
        || q.contains("than a month ago")
        || q.contains("than last month"))
        && (q.contains("risk") || q.contains("siren") || q.contains("regime"))
    {
        let pair = detect_pair(q).unwrap_or_else(|| "EURUSD".into());
        if let Some(hist) = archive.pairs.get(&pair) {
            let mut dates: Vec<&String> = hist.daily_risk.keys().collect();
            dates.sort();
            if dates.len() > 25 {
                let today = dates[dates.len() - 1];
                let past_idx = dates.len().saturating_sub(23); // ~one trading month back
                let past = dates[past_idx];
                let now_v = hist.daily_risk.get(today).and_then(|v| *v);
                let then_v = hist.daily_risk.get(past).and_then(|v| *v);
                if let (Some(now_v), Some(then_v)) = (now_v, then_v) {
                    let word = if (now_v - then_v).abs() < 0.005 {
                        "about the same as"
                    } else if now_v > then_v {
                        "above"
                    } else {
                        "below"
                    };
                    return Some(ArchiveAnswer {
                        text: format!(
                            "{}: change risk is {now_v:.2} today ({today}) against {then_v:.2} on \
                             {past} — {word} where it was a month ago.",
                            pretty(&pair)
                        ),
                        shape: "compare_period",
                    });
                }
            }
        }
    }

    None
}

#[cfg(test)]
mod tests {
    use super::*;

    fn archive() -> Archive {
        let mut pairs = HashMap::new();
        let mut daily = HashMap::new();
        let mut daily_risk = HashMap::new();
        let mut daily_siren = HashMap::new();
        for (i, d) in ["2015-01-14", "2015-01-15", "2015-01-16"]
            .iter()
            .enumerate()
        {
            daily.insert(
                d.to_string(),
                if i == 1 { "crisis" } else { "calm" }.to_string(),
            );
            daily_risk.insert(d.to_string(), Some(0.10 + i as f64 * 0.1));
            daily_siren.insert(d.to_string(), Some(50.0 + i as f64));
        }
        let mut months = HashMap::new();
        months.insert(
            "2015-01".to_string(),
            HashMap::from([("crisis".to_string(), 4_i64)]),
        );
        let mut years = HashMap::new();
        years.insert(
            "2015".to_string(),
            HashMap::from([("crisis".to_string(), 9_i64), ("calm".to_string(), 240_i64)]),
        );
        pairs.insert(
            "USDCHF".to_string(),
            PairHistory {
                months,
                years,
                daily,
                daily_risk,
                daily_siren,
                first_date: "2011-01-03".into(),
                last_date: "2026-08-20".into(),
            },
        );
        Archive {
            ledger: LedgerTotals {
                days_live: Some(4),
                n_forecasts: Some(12),
                n_resolved: Some(3),
                chain_head_short: Some("2fb2db21".into()),
                live_brier: None,
                frozen_brier: Some(0.102),
            },
            today: HashMap::from([
                (
                    "EURUSD".to_string(),
                    TodayReading {
                        regime: "calm".into(),
                        risk: Some(0.03),
                        siren: Some(79.0),
                    },
                ),
                (
                    "USDCHF".to_string(),
                    TodayReading {
                        regime: "chop".into(),
                        risk: Some(0.31),
                        siren: Some(44.0),
                    },
                ),
                (
                    "USDRUB".to_string(),
                    TodayReading {
                        regime: "crisis".into(),
                        risk: Some(0.21),
                        siren: Some(100.0),
                    },
                ),
            ]),
            data_through: "2026-08-20".into(),
            daily_pairs: vec!["USDCHF".into()],
            markets_total: 20,
            counts_today: HashMap::from([("calm".to_string(), 16_i64), ("crisis".to_string(), 1)]),
            by_regime_today: HashMap::from([
                (
                    "calm".to_string(),
                    vec!["EURUSD".to_string(), "GBPUSD".to_string()],
                ),
                ("crisis".to_string(), vec!["USDRUB".to_string()]),
            ]),
            pairs,
            runs: HashMap::from([(
                "USDCHF".to_string(),
                HashMap::from([(
                    "chop".to_string(),
                    RunStats {
                        episodes: 12,
                        mean_days: 9.4,
                        median_days: 7.0,
                        longest_days: 41,
                    },
                )]),
            )]),
            events: HashMap::from([(
                "SNB".to_string(),
                EventStats {
                    pairs: HashMap::from([(
                        "USDCHF".to_string(),
                        EventPairStats {
                            mean_change_risk_before: Some(0.21),
                            mean_change_risk_after: Some(0.34),
                        },
                    )]),
                    n_events: 18,
                },
            )]),
            episodes: HashMap::new(),
        }
    }

    #[test]
    fn counts_markets_in_a_regime_today() {
        let a = answer(&archive(), "how many of the markets are calm today").unwrap();
        assert_eq!(a.shape, "count_today");
        assert!(a.text.contains("2 of 20"), "{}", a.text);
    }

    #[test]
    fn reads_a_specific_historical_date() {
        let a = answer(&archive(), "what was the regime for usdchf on 2015-01-15").unwrap();
        assert_eq!(a.shape, "regime_on_date");
        assert!(
            a.text.contains("crisis") && a.text.contains("2015-01-15"),
            "{}",
            a.text
        );
    }

    #[test]
    fn parses_a_spoken_date() {
        let a = answer(&archive(), "what was the franc doing on 15 january 2015").unwrap();
        assert!(a.text.contains("crisis"), "{}", a.text);
    }

    #[test]
    fn a_date_outside_the_archive_says_so_instead_of_guessing() {
        let a = answer(&archive(), "what was usdchf on 1999-05-05").unwrap();
        assert_eq!(a.shape, "regime_on_date_missing");
        assert!(a.text.contains("do not hold"), "{}", a.text);
    }

    #[test]
    fn counts_days_in_a_regime_over_a_year() {
        let a = answer(&archive(), "how many crisis days did usdchf have in 2015").unwrap();
        assert_eq!(a.shape, "regime_days_year");
        assert!(a.text.contains("9 of 249"), "{}", a.text);
    }

    #[test]
    fn quotes_a_typical_duration() {
        let a = answer(
            &archive(),
            "how long does a chop regime usually last on usdchf",
        )
        .unwrap();
        assert_eq!(a.shape, "regime_duration");
        assert!(
            a.text.contains("median") && a.text.contains("41"),
            "{}",
            a.text
        );
    }

    #[test]
    fn reads_an_event_window_without_forecasting() {
        let a = answer(
            &archive(),
            "what usually happens around snb meetings for usdchf",
        )
        .unwrap();
        assert_eq!(a.shape, "event_window");
        assert!(
            a.text.contains("not a forecast"),
            "the event answer must disclaim: {}",
            a.text
        );
    }

    #[test]
    fn answers_a_multi_hop_extreme_question_in_one_pass() {
        // The audit's hardest shape: "which is the most X, and is it also the most Y" needs two
        // lookups chained. Returning a comparison table instead was the old behaviour.
        let a = answer(
            &archive(),
            "which market has the highest siren and is it also the riskiest",
        )
        .unwrap();
        assert_eq!(a.shape, "extreme_today");
        assert!(a.text.contains("USD/RUB"), "{}", a.text);
        assert!(
            a.text.contains("different markets") || a.text.contains("same market"),
            "the 'and is it also' half must be answered: {}",
            a.text
        );
    }

    #[test]
    fn averages_across_todays_markets() {
        let a = answer(
            &archive(),
            "what is the average change risk across the markets",
        )
        .unwrap();
        assert_eq!(a.shape, "average_today");
        assert!(a.text.contains("average risk"), "{}", a.text);
    }

    #[test]
    fn a_filter_we_cannot_apply_stops_the_shape() {
        // We hold no per-market event calendar in the archive, so the honest outcome for "of the
        // markets with an event within 10 days, which is least calm" is None and a refusal — not
        // the unfiltered ranking, which answers an easier question than the one asked.
        assert!(answer(
            &archive(),
            "of the markets with an event within 10 days which is least calm"
        )
        .is_none());
    }

    #[test]
    fn a_named_market_is_not_a_ranking_question() {
        // "which state is GBPUSD most likely in" asks about GBPUSD, not for a league table.
        assert!(answer(&archive(), "which state is gbpusd most likely in right now").is_none());
        // ...while an explicitly cross-market question still ranks.
        assert!(answer(&archive(), "which market has the highest risk today").is_some());
    }

    #[test]
    fn answers_ledger_totals_rather_than_refusing_them() {
        // Regression guard: adding the archive briefly BROKE this question, because "how many"
        // routed it to a room that had no shape for it. A new capability that removes an old
        // answer is a net loss, whatever the aggregate metrics say.
        let a = answer(&archive(), "how many forecasts have you sealed so far").unwrap();
        assert_eq!(a.shape, "ledger_totals");
        assert!(a.text.contains("12 forecasts"), "{}", a.text);
    }

    #[test]
    fn an_unsupported_shape_returns_none_so_the_caller_can_refuse() {
        // Deliberately outside every shape: the archive must not improvise an adjacent number.
        assert!(answer(
            &archive(),
            "what is the correlation between usdchf and gold"
        )
        .is_none());
        assert!(answer(&archive(), "show me the worst week for usdchf this year").is_none());
    }

    #[test]
    fn historical_questions_are_recognisable_as_such() {
        assert!(looks_historical("how many crisis days this year"));
        assert!(looks_historical("what was the regime during covid"));
        assert!(!looks_historical("how does eurusd look today"));
        // Regression guard: a product question that merely begins with "how many" must not be
        // routed to the archive, because the archive would then refuse an answerable question.
        assert!(!looks_historical(
            "alerts - slack? and how many do i get per flip"
        ));
        assert!(!looks_historical("how many tiers are there"));
    }
}
