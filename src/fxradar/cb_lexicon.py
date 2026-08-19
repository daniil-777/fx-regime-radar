"""Historical leg of the central-bank communication index (phase 29, part B): frozen word lists.

Why a word list for history? It has no memory. A list of 121 hawkish and 129 dovish terms plus
the 297 Loughran-McDonald uncertainty words knows nothing about what EUR/USD did after any
statement, so scoring a 2015 letter with it is as honest as scoring tomorrow's. FinBERT and
LLMs were trained on text written AFTER those letters (including commentary about their market
impact) — their memory is in the weights — so they are confined to post-deploy documents
(`cb_finbert`, `cb_llm`).

Scores per document (all normalised by token count, so long and short statements compare):
    hawk        = hawkish term hits / n_tokens
    dove        = dovish term hits / n_tokens
    tone        = (hawk - dove) / (hawk + dove + EPS)         in [-1, 1]
    uncertainty = LM uncertainty hits / n_tokens
Matching is lower-case, hyphens -> spaces, greedy longest phrase first (a hit on "rate hike"
consumes both tokens so "hike" is not counted twice). The lists are frozen by sha256
(data/lexicon/hashes.json); `load_lexicon` refuses to run on a tampered file.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path

import pandas as pd

from fxradar import config
from fxradar.cb_text import BANKS, DEPLOY_DATE, doc_date, load_docs

LEXICON_VERSION = "v1"
LEXICON_DIR = config.ROOT / "data" / "lexicon"
HASHES_PATH = LEXICON_DIR / "hashes.json"
FILES = {
    "hawkish": "hawkish.txt",
    "dovish": "dovish.txt",
    "uncertainty": "lm_uncertainty.txt",
}
EPS = 1e-9
MAX_NGRAM = 3
SCORE_COLUMNS = [
    "bank",
    "date",
    "published_at",
    "n_tokens",
    "n_hawk",
    "n_dove",
    "n_uncert",
    "hawk",
    "dove",
    "tone",
    "uncertainty",
    "sha256",
    "lexicon_version",
]

_TOKEN = re.compile(r"[a-z0-9]+")


# --------------------------------------------------------------------------------------
# lexicon loading (frozen)
# --------------------------------------------------------------------------------------
def file_hashes(lexicon_dir: Path = LEXICON_DIR) -> dict[str, str]:
    """sha256 of every lexicon file currently on disk."""
    return {
        name: hashlib.sha256((lexicon_dir / name).read_bytes()).hexdigest()
        for name in FILES.values()
    }


def verify_hashes(lexicon_dir: Path = LEXICON_DIR) -> None:
    """Raise if any lexicon file differs from the pinned hash — the lists are frozen."""
    pinned = json.loads((lexicon_dir / "hashes.json").read_text())["files"]
    actual = file_hashes(lexicon_dir)
    bad = {k: (pinned.get(k), actual[k]) for k in actual if pinned.get(k) != actual[k]}
    if bad:
        raise RuntimeError(f"lexicon hash mismatch (frozen lists were edited): {bad}")


def _read_terms(path: Path) -> frozenset[tuple[str, ...]]:
    terms = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip().lower()
        if not line or line.startswith("#"):
            continue
        toks = tuple(tokenize(line))
        if toks and len(toks) <= MAX_NGRAM:
            terms.add(toks)
    return frozenset(terms)


def load_lexicon(lexicon_dir: Path = LEXICON_DIR, verify: bool = True) -> dict:
    """{"hawkish": set of token-tuples, "dovish": ..., "uncertainty": ...}; verifies the hashes."""
    if verify:
        verify_hashes(lexicon_dir)
    return {key: _read_terms(lexicon_dir / name) for key, name in FILES.items()}


# --------------------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------------------
def tokenize(text: str) -> list[str]:
    """Lower-case word tokens; hyphens become spaces so "two-sided" -> ["two", "sided"]."""
    return _TOKEN.findall(text.lower().replace("-", " ").replace("‑", " "))


def count_hits(tokens: list[str], terms: frozenset[tuple[str, ...]]) -> int:
    """Number of lexicon hits, greedy longest-phrase-first; matched tokens are consumed."""
    n = len(tokens)
    i = 0
    hits = 0
    while i < n:
        matched = 0
        for k in range(min(MAX_NGRAM, n - i), 0, -1):
            if tuple(tokens[i : i + k]) in terms:
                matched = k
                break
        if matched:
            hits += 1
            i += matched
        else:
            i += 1
    return hits


def score_text(text: str, lexicon: dict | None = None) -> dict:
    """Per-document normalised counts and the tone balance (see module docstring)."""
    lex = lexicon or load_lexicon()
    tokens = tokenize(text)
    n = len(tokens)
    n_hawk = count_hits(tokens, lex["hawkish"])
    n_dove = count_hits(tokens, lex["dovish"])
    n_unc = count_hits(tokens, lex["uncertainty"])
    hawk = n_hawk / n if n else 0.0
    dove = n_dove / n if n else 0.0
    return {
        "n_tokens": n,
        "n_hawk": n_hawk,
        "n_dove": n_dove,
        "n_uncert": n_unc,
        "hawk": hawk,
        "dove": dove,
        "tone": (hawk - dove) / (hawk + dove + EPS),
        "uncertainty": n_unc / n if n else 0.0,
    }


def score_docs(docs: list[dict], lexicon: dict | None = None) -> pd.DataFrame:
    """One row per document (contract: SCORE_COLUMNS), sorted by published_at then bank."""
    lex = lexicon or load_lexicon()
    rows = []
    for doc in docs:
        s = score_text(doc["text"], lex)
        rows.append(
            {
                "bank": doc["bank"],
                "date": pd.Timestamp(doc_date(doc)),
                "published_at": doc["published_at"],
                **s,
                "sha256": doc.get("sha256"),
                "lexicon_version": LEXICON_VERSION,
            }
        )
    out = pd.DataFrame(rows, columns=SCORE_COLUMNS)
    return out.sort_values(["published_at", "bank"]).reset_index(drop=True)


# --------------------------------------------------------------------------------------
# live tracking (proof page)
# --------------------------------------------------------------------------------------
def live_tracking_summary(docs: list[dict] | None = None, deploy_date: date = DEPLOY_DATE) -> dict:
    """Small dict for the proof page: per bank, statements since deploy + last lexicon tone."""
    docs = load_docs() if docs is None else docs
    scores = score_docs(docs) if docs else pd.DataFrame(columns=SCORE_COLUMNS)
    out: dict = {
        "deploy_date": deploy_date.isoformat(),
        "lexicon_version": LEXICON_VERSION,
        "banks": {},
    }
    for bank in BANKS:
        s = scores[scores["bank"] == bank]
        live = s[s["date"] >= pd.Timestamp(deploy_date)]
        last = s.iloc[-1] if len(s) else None
        out["banks"][bank] = {
            "n_total": int(len(s)),
            "n_since_deploy": int(len(live)),
            "last_date": str(last["date"].date()) if last is not None else None,
            "last_tone": round(float(last["tone"]), 4) if last is not None else None,
            "last_uncertainty": round(float(last["uncertainty"]), 4) if last is not None else None,
        }
    out["n_since_deploy"] = int(sum(b["n_since_deploy"] for b in out["banks"].values()))
    return out


def main() -> None:
    """Score every stored statement and print a compact table."""
    docs = load_docs()
    if not docs:
        print("no documents in data/cb/ — run `python -m fxradar.cb_text --backfill --since 2020`")
        return
    scores = score_docs(docs)
    with pd.option_context("display.width", 140, "display.max_rows", 500):
        print(scores[["bank", "date", "n_tokens", "hawk", "dove", "tone", "uncertainty"]].round(4))
    print(json.dumps(live_tracking_summary(docs), indent=1))


if __name__ == "__main__":
    main()
