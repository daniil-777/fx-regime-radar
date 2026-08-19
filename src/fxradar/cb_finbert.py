"""Live leg of the central-bank communication index (phase 29, part C): one pinned FinBERT.

FinBERT has memory: its weights were fitted on financial text written after most of our history,
so it has — in effect — read how markets reacted to old statements. Scoring a 2015 letter with it
would be parametric look-ahead (see docs/why-we-refuse-the-backtest.md). Therefore:

* `score_live` REFUSES any document published before the phase-20 deploy date
  (`cb_text.DEPLOY_DATE`) by raising `LiveOnlyError`; the guard runs BEFORE transformers is
  imported, so the test needs neither torch nor the network.
* The checkpoint is pinned by model id + HF revision hash in data/cb/finbert_pin.json.
* transformers/torch live in requirements-nlp.txt only (VM / laptop). CI never installs them;
  the scorer imports them lazily inside `load_scorer`.
* Scores are appended to data/cb/finbert_scores.jsonl; the orchestrator mirrors them into the
  hash-chained ledger. They never enter training data or historical features.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

from fxradar.cb_text import CB_DIR, DEPLOY_DATE, doc_date, load_docs

log = logging.getLogger(__name__)

MODEL_ID = "ProsusAI/finbert"
# HF API sha for ProsusAI/finbert, read 2026-08-19 (lastModified 2023-05-23). `load_scorer`
# passes it as `revision=` so a silent upstream change cannot alter our numbers.
REVISION = "4556d13015211d73dccd3fdd39d39232506f3e43"
PIN_PATH = CB_DIR / "finbert_pin.json"
SCORES_PATH = CB_DIR / "finbert_scores.jsonl"
MAX_WORDS_PER_CHUNK = 300  # FinBERT takes 512 word-pieces; ~300 words keeps every chunk inside
LABELS = ("positive", "negative", "neutral")


class LiveOnlyError(RuntimeError):
    """Raised when a model with memory is asked to score a pre-deploy (historical) document."""


def assert_live_only(docs: list[dict], deploy_date: date = DEPLOY_DATE) -> None:
    """Raise LiveOnlyError if ANY document was published before `deploy_date`."""
    stale = [(d["bank"], doc_date(d).isoformat()) for d in docs if doc_date(d) < deploy_date]
    if stale:
        raise LiveOnlyError(
            f"refusing to score {len(stale)} pre-deploy document(s) (deploy date {deploy_date}): "
            f"{stale[:5]}{' ...' if len(stale) > 5 else ''}"
        )


def write_pin(path: Path = PIN_PATH) -> dict:
    pin = {
        "model_id": MODEL_ID,
        "revision": REVISION,
        "source": "https://huggingface.co/api/models/ProsusAI/finbert (field 'sha')",
        "pinned_at": "2026-08-19",
        "labels": list(LABELS),
        "tone_definition": "p_positive - p_negative, averaged over <=300-word chunks",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pin, indent=1) + "\n")
    return pin


def chunks(text: str, max_words: int = MAX_WORDS_PER_CHUNK) -> list[str]:
    """Split on paragraph boundaries, then cap each chunk at `max_words` words."""
    out: list[str] = []
    for para in text.split("\n\n"):
        words = para.split()
        for i in range(0, len(words), max_words):
            piece = " ".join(words[i : i + max_words]).strip()
            if piece:
                out.append(piece)
    return out


def load_scorer() -> Callable[[str], dict]:
    """Lazy: import transformers here, load the PINNED checkpoint, return text -> probabilities."""
    from transformers import pipeline  # noqa: PLC0415 — deliberate lazy import

    pipe = pipeline(
        "text-classification",
        model=MODEL_ID,
        revision=REVISION,
        top_k=None,
        truncation=True,
        max_length=512,
    )

    def _score(text: str) -> dict:
        probs = {k: 0.0 for k in LABELS}
        for result in pipe(text):
            for item in result if isinstance(result, list) else [result]:
                probs[item["label"].lower()] = float(item["score"])
        return probs

    return _score


def score(doc: dict, scorer: Callable[[str], dict] | None = None) -> dict:
    """Document-level FinBERT probabilities (chunk average) and tone = p_pos - p_neg.

    `scorer` is injectable for tests; the default loads the pinned transformers pipeline.
    No live-only check here — callers go through `score_live`.
    """
    run = scorer or load_scorer()
    parts = chunks(doc["text"]) or [doc["text"]]
    acc = {k: 0.0 for k in LABELS}
    for part in parts:
        p = run(part)
        for k in LABELS:
            acc[k] += p.get(k, 0.0) / len(parts)
    return {
        "bank": doc["bank"],
        "date": doc_date(doc).isoformat(),
        "published_at": doc["published_at"],
        "sha256": doc.get("sha256"),
        "model_id": MODEL_ID,
        "revision": REVISION,
        "n_chunks": len(parts),
        "p_positive": acc["positive"],
        "p_negative": acc["negative"],
        "p_neutral": acc["neutral"],
        "finbert_tone": acc["positive"] - acc["negative"],
        "scored_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def already_scored(path: Path = SCORES_PATH) -> set[str]:
    if not path.exists():
        return set()
    return {json.loads(line)["sha256"] for line in path.read_text().splitlines() if line.strip()}


def score_live(
    docs: list[dict],
    deploy_date: date = DEPLOY_DATE,
    scorer: Callable[[str], dict] | None = None,
    out_path: Path = SCORES_PATH,
) -> list[dict]:
    """Score post-deploy documents only and append to the jsonl. The guard runs FIRST."""
    assert_live_only(docs, deploy_date)  # before any model import
    done = already_scored(out_path)
    todo = [d for d in docs if d.get("sha256") not in done]
    if not todo:
        return []
    run = scorer or load_scorer()
    results = [score(d, run) for d in todo]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r) + "\n")
    return results


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="FinBERT-score post-deploy statements (VM/local only)")
    ap.add_argument("--write-pin", action="store_true", help="(re)write data/cb/finbert_pin.json")
    args = ap.parse_args()
    if args.write_pin:
        print(json.dumps(write_pin(), indent=1))
    docs = [d for d in load_docs() if doc_date(d) >= DEPLOY_DATE]
    print(f"{len(docs)} post-deploy document(s) eligible (deploy date {DEPLOY_DATE})")
    if not docs:
        return
    try:
        results = score_live(docs)
    except ImportError as exc:
        print(f"transformers/torch not installed ({exc}); pip install -r requirements-nlp.txt")
        return
    for r in results:
        print(f"{r['bank']} {r['date']} finbert_tone={r['finbert_tone']:+.3f}")
    print(f"{len(results)} new score(s) appended to {SCORES_PATH}")


if __name__ == "__main__":
    main()
