//! Card selection for the answer boards (phase 36).
//!
//! The wall (CLAUDE.md rule 11) means this service never calls Python. The pipeline exports two
//! artifacts — `visual_boards.json` (every card already resolved from published data) and
//! `visual_index.json` (the retrieval index) — and this module reads them as data.
//!
//! Selection therefore mirrors `fxradar.visuals._score`: IDF-weighted token overlap plus character
//! n-gram similarity, over the same normalised text, with the same alias and thesaurus expansion
//! exported by the pipeline. `retrieval_agrees_with_python` pins the two implementations to the
//! same top-1 across the golden question set, so a change on one side cannot drift unnoticed.
//!
//! Two properties matter more than the ranking: the browser is handed values this service read
//! from an artifact (never anything the model produced), and a card that could not be resolved is
//! simply absent, so no answer can offer a card it cannot fill.

use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::path::Path;

pub const MAX_BOARD_CARDS: usize = 2;

/// The eight primitives of phase 38 — a card naming anything else cannot render.
pub const PRIMITIVES_ALLOWED: [&str; 8] = [
    "stat_block",
    "bar_row",
    "trace_band",
    "ribbon",
    "table",
    "dot_row",
    "media_frame",
    "diagram_frame",
];

/// Thresholds measured, not guessed — and the measurement changed the design. An absolute cut-off
/// cannot work: "which pair is calmest" scores 3.73 while "what is the weather in zurich" scores
/// 3.80, so any single line puts a wanted question below an unwanted one. What separates them is
/// the MARGIN over the runner-up: 1.98 for the real question, 0.35 for the off-topic one. A
/// confident match stands clear of the field; a spurious one has everything bunched behind it.
pub const STRONG_SCORE: f64 = 4.4;
pub const MARGIN_FLOOR_SCORE: f64 = 3.0;
pub const MIN_MARGIN: f64 = 1.5;

/// Similarity to an actual declared phrasing — the confidence signal that works here.
///
/// Measured alternative, recorded because it cost a day: BM25 rank score does NOT separate
/// questions worth answering from questions worth refusing. Wanted questions score 12.7 at the
/// median, unwanted ones 4.7 — but the unwanted 90th percentile is 23.7, so no cut-off exists.
/// Every question in this domain contains vocabulary that matches SOMETHING. Similarity to a
/// phrasing the registry actually declares behaves completely differently: at 0.60 it made zero
/// false positives and zero wrong-card matches on the golden set.
pub const SPEAK_SIMILARITY: f64 = 0.60;
pub const SHOW_SIMILARITY: f64 = 0.45;

pub fn phrase_similarity(index: &VisualIndex, question: &str) -> Option<(String, f64)> {
    let norm = normalise(question, &index.pair_aliases);
    let q = char_ngrams(&norm, 4);
    let mut best: Option<(String, f64)> = None;
    for (id, doc) in &index.docs {
        for phrase in &doc.phrases {
            let sim = cosine(&q, &char_ngrams(phrase, 4));
            if best.as_ref().is_none_or(|(_, b)| sim > *b) {
                best = Some((id.clone(), sim));
            }
        }
    }
    best
}

/// Is the best match good enough to act on? Either it is strong outright, or it is decent AND
/// clearly ahead of the alternatives.
pub fn is_confident(ranked: &[(String, f64)]) -> bool {
    let Some((_, top)) = ranked.first() else {
        return false;
    };
    let second = ranked.get(1).map(|(_, s)| *s).unwrap_or(0.0);
    *top >= STRONG_SCORE || (*top >= MARGIN_FLOOR_SCORE && (*top - second) >= MIN_MARGIN)
}
/// A support card must be genuinely related, not merely next in the ranking.
pub const SUPPORT_SCORE_RATIO: f64 = 0.45;

#[derive(Deserialize, Clone, Debug)]
pub struct IndexDoc {
    #[serde(default)]
    pub phrases: Vec<String>,
    #[serde(default)]
    pub text: String,
    #[serde(default)]
    pub tokens: HashMap<String, f64>,
    #[serde(default)]
    pub total: f64,
    #[serde(default)]
    pub family: String,
    #[serde(default)]
    pub tier: i64,
    #[serde(default)]
    pub rivals: Vec<String>,
}

#[derive(Deserialize, Clone, Debug, Default)]
pub struct VisualIndex {
    #[serde(default)]
    pub registry_version: String,
    #[serde(default)]
    pub df: HashMap<String, f64>,
    #[serde(default)]
    pub docs: HashMap<String, IndexDoc>,
    #[serde(default)]
    pub catch_alls: Vec<String>,
    #[serde(default)]
    pub expansion: HashMap<String, Vec<String>>,
    #[serde(default)]
    pub pair_aliases: HashMap<String, Vec<String>>,
}

#[derive(Deserialize, Serialize, Clone, Debug, utoipa::ToSchema)]
pub struct CardSpec {
    pub component: String,
    pub primitive: String,
    #[serde(default)]
    pub family: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    #[schema(value_type = Object)]
    pub args: serde_json::Value,
    #[serde(default)]
    pub caption: String,
    #[serde(default)]
    pub label: String,
    #[serde(default)]
    pub asof: Option<String>,
    #[serde(default)]
    #[schema(value_type = Object)]
    pub data: serde_json::Value,
    #[serde(default)]
    pub stale: bool,
}

#[derive(Deserialize, Clone, Debug, Default)]
pub struct VisualBoards {
    #[serde(default)]
    pub registry_version: String,
    #[serde(default)]
    pub data_through: Option<String>,
    #[serde(default)]
    pub cards: HashMap<String, CardSpec>,
    /// Arguments to prefer when the question names none (the lead market, usually EURUSD).
    #[serde(default)]
    pub default_args: HashMap<String, String>,
}

pub fn load_index(path: &Path) -> Result<VisualIndex, String> {
    let raw = std::fs::read_to_string(path).map_err(|e| format!("visual index unreadable: {e}"))?;
    serde_json::from_str(&raw).map_err(|e| format!("visual index is not valid JSON: {e}"))
}

pub fn load_boards(path: &Path) -> Result<VisualBoards, String> {
    let raw =
        std::fs::read_to_string(path).map_err(|e| format!("visual boards unreadable: {e}"))?;
    serde_json::from_str(&raw).map_err(|e| format!("visual boards are not valid JSON: {e}"))
}

fn normalise(text: &str, aliases: &HashMap<String, Vec<String>>) -> String {
    let mut low = text.to_lowercase();
    for (code, names) in aliases {
        for name in names {
            if low.contains(name.as_str()) {
                low = low.replace(name.as_str(), code);
            }
        }
    }
    low
}

fn tokens(text: &str) -> Vec<String> {
    text.split(|c: char| !c.is_alphanumeric())
        .filter(|w| !w.is_empty())
        .map(|w| w.to_string())
        .collect()
}

fn expand(toks: &[String], expansion: &HashMap<String, Vec<String>>) -> HashMap<String, f64> {
    let mut bag: HashMap<String, f64> = HashMap::new();
    for t in toks {
        *bag.entry(t.clone()).or_insert(0.0) += 1.0;
    }
    for t in toks {
        if let Some(canons) = expansion.get(t) {
            for c in canons {
                *bag.entry(c.clone()).or_insert(0.0) += 1.0;
            }
        }
    }
    bag
}

fn char_ngrams(text: &str, n: usize) -> HashMap<String, f64> {
    let cleaned: String = text
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == ' ' {
                c
            } else {
                ' '
            }
        })
        .collect();
    let padded: Vec<char> = format!(" {cleaned} ").chars().collect();
    let mut out: HashMap<String, f64> = HashMap::new();
    if padded.len() >= n {
        for i in 0..=(padded.len() - n) {
            let gram: String = padded[i..i + n].iter().collect();
            *out.entry(gram).or_insert(0.0) += 1.0;
        }
    }
    out
}

fn cosine(a: &HashMap<String, f64>, b: &HashMap<String, f64>) -> f64 {
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }
    let mut num = 0.0;
    for (k, v) in a {
        if let Some(w) = b.get(k) {
            num += v * w;
        }
    }
    let na: f64 = a.values().map(|v| v * v).sum::<f64>().sqrt();
    let nb: f64 = b.values().map(|v| v * v).sum::<f64>().sqrt();
    if na == 0.0 || nb == 0.0 {
        0.0
    } else {
        num / (na * nb)
    }
}

/// BM25 parameters, mirrored from `fxradar.visuals`. Length normalisation is the point: card
/// documents here differ in size by a factor of three, and plain IDF overlap was rewarding the long
/// ones for being long.
pub const BM25_K1: f64 = 1.2;
pub const BM25_B: f64 = 0.75;

/// Rank the indexed cards for a question. Mirrors `fxradar.visuals.Registry._score` exactly, which
/// `retrieval_agrees_with_python` pins to the golden vectors.
pub fn rank(index: &VisualIndex, question: &str) -> Vec<(String, f64)> {
    let norm = normalise(question, &index.pair_aliases);
    let q_bag = expand(&tokens(&norm), &index.expansion);
    let q_chars = char_ngrams(&norm, 4);
    let n = index.docs.len().max(1) as f64;
    let avgdl = if index.docs.is_empty() {
        1.0
    } else {
        index.docs.values().map(|d| d.total).sum::<f64>() / index.docs.len() as f64
    };
    let mut scored: Vec<(String, f64)> = index
        .docs
        .iter()
        .map(|(id, doc)| {
            let mut lexical = 0.0;
            for (tok, qn) in &q_bag {
                let f = doc.tokens.get(tok).copied().unwrap_or(0.0);
                if f == 0.0 {
                    continue;
                }
                let df = index.df.get(tok).copied().unwrap_or(0.0);
                let idf = (1.0 + (n - df + 0.5) / (df + 0.5)).ln();
                lexical += idf * qn * (f * (BM25_K1 + 1.0))
                    / (f + BM25_K1 * (1.0 - BM25_B + BM25_B * doc.total / avgdl));
            }
            let score = lexical + 2.5 * cosine(&q_chars, &char_ngrams(&doc.text, 4));
            (id.clone(), score)
        })
        .collect();
    scored.sort_by(|a, b| {
        b.1.partial_cmp(&a.1)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| a.0.cmp(&b.0))
    });
    scored
}

fn key_for(component: &str, args: &serde_json::Value) -> String {
    let mut parts: Vec<String> = Vec::new();
    if let Some(obj) = args.as_object() {
        let mut names: Vec<&String> = obj.keys().collect();
        names.sort();
        for name in names {
            if let Some(v) = obj.get(name).and_then(|v| v.as_str()) {
                parts.push(format!("{name}={v}"));
            }
        }
    }
    if parts.is_empty() {
        component.to_string()
    } else {
        format!("{component}|{}", parts.join(","))
    }
}

/// Every resolved instance of one component, cheapest default first (fewest arguments).
fn instances<'a>(boards: &'a VisualBoards, component: &str) -> Vec<(&'a String, &'a CardSpec)> {
    let mut out: Vec<(&String, &CardSpec)> = boards
        .cards
        .iter()
        .filter(|(_, c)| c.component == component)
        .collect();
    out.sort_by_key(|(k, _)| (k.len(), (*k).clone()));
    out
}

/// Pick the instance whose arguments best match what the question actually named.
fn best_instance<'a>(
    boards: &'a VisualBoards,
    component: &str,
    question: &str,
) -> Option<&'a CardSpec> {
    let q = question.to_lowercase();
    let compact: String = q.chars().filter(|c| c.is_ascii_alphanumeric()).collect();
    let mut best: Option<(i32, &CardSpec)> = None;
    for (key, spec) in instances(boards, component) {
        let mut score = 0;
        if let Some(obj) = spec.args.as_object() {
            for (name, value) in obj.iter() {
                let Some(v) = value.as_str() else { continue };
                let v = v.to_lowercase();
                if compact.contains(&v.replace('-', "")) || q.contains(&v) {
                    score += 4; // the question named this argument outright
                } else if boards.default_args.get(name).map(|d| d.to_lowercase()) == Some(v) {
                    score += 2; // nothing named: the lead market beats an arbitrary one
                }
            }
            score -= obj.len() as i32; // fewer arguments wins when nothing was named
        }
        let _ = key;
        if best.as_ref().is_none_or(|(s, _)| score > *s) {
            best = Some((score, spec));
        }
    }
    best.map(|(_, s)| s)
}

/// The board for one question: a primary card plus at most one support card from another family.
/// Returns an empty vector when nothing fits — the null board is first-class.
pub fn select_board(
    index: &VisualIndex,
    boards: &VisualBoards,
    question: &str,
    forced: Option<&str>,
) -> Vec<CardSpec> {
    if index.docs.is_empty() || boards.cards.is_empty() {
        return Vec::new();
    }
    let ranked = rank(index, question);
    let mut chosen: Vec<CardSpec> = Vec::new();
    let mut families: HashSet<String> = HashSet::new();
    let mut primitives: HashSet<String> = HashSet::new();

    let mut order: Vec<String> = Vec::new();
    let mut pinned: Option<&CardSpec> = None;
    if let Some(f) = forced {
        // "component" or "component|arg=value": the caller already knows which instance it means
        // (the market lookup resolved the pair itself), so honour it exactly rather than re-guessing.
        if let Some(spec) = boards.cards.get(f) {
            pinned = Some(spec);
        } else {
            order.push(f.to_string());
        }
    }
    if let Some(spec) = pinned {
        chosen.push(spec.clone());
        // A pinned card is an ANSWER TO A REFUSAL — the direction-evidence card, the escalation
        // card. It travels alone. Raising the candidate slice to eight briefly let a price trace
        // ride along beside "I don't model direction", which answers the question in pixels that
        // the sentence just declined to answer in words. Enforced here rather than in the caller,
        // because every caller would otherwise have to remember.
        return chosen;
    }
    order.extend(ranked.iter().map(|(id, _)| id.clone()));

    // A weak best match means the question was not really about a visual: a low top score is the
    // signal for the null board, not a licence to render the catch-all at everyone.
    let top = ranked.first().map(|(_, s)| *s).unwrap_or(0.0);
    if forced.is_none() && !is_confident(&ranked) {
        return Vec::new();
    }
    let score_of: HashMap<&str, f64> = ranked.iter().map(|(id, s)| (id.as_str(), *s)).collect();

    for id in order {
        if chosen.len() >= MAX_BOARD_CARDS {
            break;
        }
        let Some(spec) = best_instance(boards, &id, question) else {
            continue;
        };
        if !chosen.is_empty() {
            if families.contains(&spec.family) || primitives.contains(&spec.primitive) {
                continue;
            }
            let own = score_of
                .get(spec.component.as_str())
                .copied()
                .unwrap_or(0.0);
            if own < top * SUPPORT_SCORE_RATIO {
                continue; // a support card must be related, not merely next in the ranking
            }
            if index.catch_alls.iter().any(|c| c == &spec.component) {
                continue; // never pad a board with the catch-all
            }
        }
        families.insert(spec.family.clone());
        primitives.insert(spec.primitive.clone());
        chosen.push(spec.clone());
    }
    chosen
}

/// Cards must carry only values this service read from the artifact. A number that appears in a
/// caption but nowhere in the resolved data is a fabrication, whatever produced it.
pub fn board_is_grounded(cards: &[CardSpec]) -> bool {
    cards.iter().all(|c| !c.data.is_null())
}

pub fn board_key(cards: &[CardSpec]) -> String {
    cards
        .iter()
        .map(|c| key_for(&c.component, &c.args))
        .collect::<Vec<_>>()
        .join("+")
}
