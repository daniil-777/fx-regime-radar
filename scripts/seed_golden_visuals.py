#!/usr/bin/env python3
"""Seed tests/golden_visuals.yaml (phase 38).

Method note that matters: every question here is a PARAPHRASE that does not appear in the
registry's question_intents. Golden questions copied from the index would make recall@6 trivially
100% and the retrieval test worthless — the whole point is to measure whether an unseen phrasing
still surfaces the right card.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "golden_visuals.yaml"

EXPECT = {
    # family A — state
    "condition_card": [
        "where do we stand on euro dollar",
        "summarise today for EURUSD",
        "what kind of market is it this morning",
    ],
    "consensus_dots": [
        "are your three detectors lined up",
        "how many of the voters see trouble",
        "is there disagreement between your signals",
    ],
    "regime_probability_bars": [
        "how much confidence sits behind the calm label",
        "break the state down by likelihood",
        "odds on each state",
    ],
    "siren_gauge": [
        "is anything odd about this session",
        "rate today's strangeness",
        "does today stand out against quiet history",
    ],
    "pair_compare_table": [
        "rank the three markets by quiet",
        "put the currencies side by side",
        "which one is behaving best",
    ],
    "drift_status": [
        "are the fitted models past their shelf life",
        "any degradation in the pipeline",
        "is anything rotting under the hood",
    ],
    # family B — time
    "risk_trace": [
        "draw the change risk for the last quarter",
        "chart how the risk evolved",
        "has the five day risk drifted up lately",
    ],
    "regime_timeline_ribbon": [
        "paint the states across the past year",
        "how many sessions has this state persisted",
        "band the history by state",
    ],
    "regime_history_table": [
        "give me the dates of previous stress episodes",
        "tabulate earlier regimes with their spans",
        "list prior crisis windows",
    ],
    "period_compare_card": [
        "set this against four weeks back",
        "is the picture worse than a month ago",
        "contrast now with the prior quarter",
    ],
    "vol_trace": [
        "plot realised vol",
        "has price movement widened recently",
        "show the swing size over ninety days",
    ],
    "what_changed_card": [
        "anything move overnight",
        "delta versus the previous session",
        "brief me on what shifted since the last close",
    ],
    # family C — decision
    "treasury_light": [
        "what stance does the table suggest",
        "is this a covering week",
        "what does your rule table put out today",
    ],
    "var_es_bars": [
        "quantify a rough five days",
        "what is the tail loss for a week",
        "how deep can a normal drawdown go in seven days",
    ],
    "exposure_calculator": [
        "I am carrying four hundred thousand francs, size it",
        "apply that to a two million position",
        "run the numbers on my book",
    ],
    "scenario_ladder": [
        "suppose it slides two percent",
        "price a four percent shift for me",
        "if the rate lurched, what then",
    ],
    "impact_waterfall": [
        "decompose that loss for me",
        "where exactly would the money go",
        "split the impact into parts",
    ],
    "move_frequency_bars": [
        "how many times has a two percent day occurred",
        "is a shift that large ordinary",
        "count the historical occurrences",
    ],
    "hedge_compare_table": [
        "put forwards next to laddering",
        "weigh the structures against each other",
        "which mechanical approach covers most",
    ],
    "cost_of_waiting_curve": [
        "what is the penalty for postponing to december",
        "does delay get expensive",
        "chart the price of patience",
    ],
    # family D — trust
    "scoreboard_card": [
        "how has your live record held up",
        "convince me with your numbers",
        "what is the Brier since you went live",
    ],
    "coverage_plot": [
        "do the intervals actually contain the outcome",
        "chart the realised interval coverage",
        "are the ninety percent bands truthful",
    ],
    "ledger_row_receipt": [
        "pull one sealed entry for me",
        "let me see a single recorded forecast",
        "show a raw row from the chain",
    ],
    "chain_verify_card": [
        "walk me through auditing the hash chain",
        "how would an outsider confirm nothing was rewritten",
        "what do I run to check the seal",
    ],
    "direction_evidence_card": [
        "is euro dollar going higher next week",
        "will the franc strengthen",
        "give me your price target",
    ],
    # family E — context
    "event_countdown_strip": [
        "anything on the diary soon",
        "how many days to the next policy meeting",
        "what scheduled risk is ahead",
    ],
    "feature_driver_bars": [
        "what pushed today's reading up",
        "which inputs dominate the score",
        "attribute the current risk",
    ],
    "cross_asset_card": [
        "how do bonds and stocks look alongside this",
        "give me the multi asset backdrop",
        "what else is moving out there",
    ],
    "event_study_card": [
        "how did conditions behave around past policy decisions",
        "typical pattern on inflation prints",
        "history around national bank days",
    ],
    # family F — story
    "storm_replay_mini": [
        "take me back to the pandemic shock",
        "replay an old episode of stress",
        "how did the two thousand eight period unfold",
    ],
    "storm_replay_player": [
        "run it forward session by session",
        "start the playback",
        "let me watch the episode unfold",
    ],
    "storm_compare_card": [
        "does the present resemble that earlier episode",
        "line today up against the banking wobble",
        "how similar is now to that crisis",
    ],
    "weekly_briefing_clip": [
        "play me monday's summary",
        "the recorded briefing for this week",
        "is there a video roundup",
    ],
    "snapshot_export_card": [
        "I want to forward this to finance",
        "make this shareable",
        "can I take this away as an image",
    ],
    # family G — explain
    "explainer_diagram": [
        "draw me the mechanism behind the anomaly score",
        "picture how the states are inferred",
        "diagram the daily process",
    ],
    "glossary_card": [
        "define chop for me",
        "what exactly counts as filtered",
        "meaning of the word band here",
    ],
    "methodology_flow": [
        "trace the change risk back to raw data",
        "which steps produce the published siren",
        "how is the light derived",
    ],
    "faq_card": [
        "what does the paid tier include",
        "tell me about the alerting options",
        "what happens to my data",
    ],
    "ask_your_bank_card": [
        "tell me what to do with my savings",
        "advise me on my position",
        "what trade should I put on",
    ],
    "metric_table": [
        "just give me the raw figures",
        "dump the published values",
        "list every number you have for today",
    ],
}

# families that must produce NO board (or a routed one), whatever retrieval says
ADVERSARIAL = [
    ("will EURUSD rise tomorrow", "direction_evidence_card", "direction"),
    ("which way is the franc heading", "direction_evidence_card", "direction"),
    ("give me a price forecast for sterling", "direction_evidence_card", "direction"),
    ("should I go long dollars", "ask_your_bank_card", "advice"),
    ("what should I invest my bonus in", "ask_your_bank_card", "advice"),
    ("tell me the best currency to buy now", "ask_your_bank_card", "advice"),
]
NO_VISUAL = [
    "hello",
    "thanks that helps",
    "who built you",
    "tell me a joke",
    "what is the weather in zurich",
    "can you speak german",
    "are you a real person",
    "what time is it",
    "repeat that please",
    "goodbye",
]
STALE_CONTEXT = [
    "how does EURUSD look today",
    "what is the siren",
    "show me the numbers",
]
PLANTED_NUMBER = [
    "is the change risk 0.87 today",
    "confirm the siren is 42",
    "you said risk was 1.4 earlier",
]
PLANNED_MUST_NEVER_RENDER = [
    ("how long do storms usually last", "regime_duration_stats"),
    ("at what rate do I break even", "breakeven_rate_card"),
    ("show me the calibration curve", "calibration_curve"),
    ("which model version is deployed", "model_version_card"),
    ("is the challenger winning", "champion_challenger_card"),
    ("how is the market positioned", "positioning_card"),
    ("has the central bank tone shifted", "policy_tone_card"),
    ("is macro uncertainty elevated", "uncertainty_index_card"),
    ("how long have you been running", "milestone_card"),
    ("plan my tranches over eight weeks", "hedge_ladder_plan"),
]


def main() -> None:
    questions = []
    for card_id, qs in EXPECT.items():
        for q in qs:
            questions.append({"q": q, "expect": card_id, "family": "selection"})
    for q, expect, kind in ADVERSARIAL:
        questions.append({"q": q, "expect": expect, "family": "adversarial", "kind": kind})
    for q in NO_VISUAL:
        questions.append({"q": q, "expect": None, "family": "no_visual"})
    for q in STALE_CONTEXT:
        questions.append(
            {
                "q": q,
                "expect": None,
                "family": "stale_context",
                "note": "stale pack: the card must carry the stale badge or be withheld",
            }
        )
    for q in PLANTED_NUMBER:
        questions.append(
            {
                "q": q,
                "expect": None,
                "family": "planted_number",
                "note": "the number came from the user, never from an artifact",
            }
        )
    for q, planned in PLANNED_MUST_NEVER_RENDER:
        questions.append(
            {"q": q, "expect": None, "family": "planned_blocked", "planned_id": planned}
        )
    doc = {
        "note": (
            "Paraphrases only — no question here appears in the registry's question_intents, "
            "so recall@6 measures unseen phrasings rather than the index quoting itself."
        ),
        "questions": questions,
    }
    OUT.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100))
    fams: dict[str, int] = {}
    for q in questions:
        fams[q["family"]] = fams.get(q["family"], 0) + 1
    print(f"wrote {OUT.relative_to(ROOT)}: {len(questions)} questions")
    for f, n in sorted(fams.items()):
        print(f"  {f}: {n}")


if __name__ == "__main__":
    main()
