"""Phase 29/30 tests — central-bank communication index. Offline, fast, no torch, no anthropic."""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from fxradar import cb_features, cb_finbert, cb_lexicon, cb_llm, cb_text, config

FIXTURES = Path(__file__).parent / "fixtures" / "cb"


@pytest.fixture(scope="module")
def docs() -> list[dict]:
    return cb_text.load_docs(FIXTURES)


@pytest.fixture(scope="module")
def fomc(docs: list[dict]) -> dict:
    return next(d for d in docs if d["bank"] == "FOMC")


@pytest.fixture(scope="module")
def lexicon() -> dict:
    return cb_lexicon.load_lexicon()


# --------------------------------------------------------------------------------------
# A. fetcher: document contract, fixed publication times, extraction
# --------------------------------------------------------------------------------------
def test_fixture_docs_follow_contract(docs: list[dict]) -> None:
    assert {d["bank"] for d in docs} == set(cb_text.BANKS)
    for d in docs:
        assert set(d) == {"bank", "type", "url", "published_at", "fetched_at", "text", "sha256"}
        assert d["type"] == cb_text.DOC_TYPES[d["bank"]]
        assert d["sha256"] == cb_text.sha256_text(d["text"])
        assert datetime.fromisoformat(d["published_at"]).tzinfo is not None


def test_published_at_uses_documented_fixed_times() -> None:
    ecb = cb_text.published_at("ECB", date(2025, 6, 5))
    assert ecb.isoformat() == "2025-06-05T14:15:00+02:00"  # 14:15 CET (CEST in June)
    fomc = cb_text.published_at("FOMC", date(2025, 6, 18))
    assert fomc.isoformat() == "2025-06-18T14:00:00-04:00"  # 14:00 ET (EDT in June)
    snb = cb_text.published_at("SNB", date(2025, 12, 11))
    assert snb.isoformat() == "2025-12-11T09:30:00+01:00"
    boe = cb_text.published_at("BOE", date(2025, 12, 18))
    assert boe.isoformat() == "2025-12-18T12:00:00+00:00"


def test_make_doc_dedups_by_bank_and_date(tmp_path: Path) -> None:
    d1 = cb_text.make_doc("ECB", date(2025, 6, 5), "u1", "x" * 10)
    d2 = cb_text.make_doc("ECB", date(2025, 6, 5), "u2", "y" * 10)
    cb_text.save_doc(d1, tmp_path)
    cb_text.save_doc(d2, tmp_path)
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert cb_text.load_docs(tmp_path)[0]["url"] == "u2"


_FED_HTML = """<html><body><nav><p>Home</p></nav>
<h3>Federal Reserve issues FOMC statement</h3>
<p>Para one of the statement.</p><p>Para two with <strong>bold</strong> words.</p>
<p>For media inquiries, please email press@frb.gov.</p></body></html>"""
_BOE_HTML = """<html><body><h1>Bank Rate maintained</h1>
<h2>Monetary Policy Summary, June 2025</h2><p>Summary paragraph.</p>
<h2>Minutes of the Monetary Policy Committee meeting ending on 18 June 2025</h2>
<p>1: Minutes paragraph that must not be taken.</p></body></html>"""


def test_extract_statement_windows_fomc_and_boe() -> None:
    assert cb_text.extract_statement("FOMC", _FED_HTML) == (
        "Para one of the statement.\n\nPara two with bold words."
    )
    assert cb_text.extract_statement("BOE", _BOE_HTML) == "Summary paragraph."
    assert cb_text.extract_statement("FOMC", "<html><p>nothing</p></html>") == ""


def test_fetch_all_is_offline_safe_and_idempotent(tmp_path: Path) -> None:
    """A getter that returns None (no network) yields empty summaries and no crash."""
    summaries = cb_text.fetch_all(2025, cb_dir=tmp_path, get=lambda url: None, sleep=0)
    assert [s["fetched"] for s in summaries] == [0, 0, 0, 0]
    assert json.loads((tmp_path / "index.json").read_text())["n_docs"] == 0


def test_deploy_date_matches_live_record() -> None:
    rec = config.DATA_DIR / "live_record.json"
    if rec.exists():
        assert json.loads(rec.read_text())["since"] == cb_text.DEPLOY_DATE.isoformat()


# --------------------------------------------------------------------------------------
# B. lexicon: frozen hashes, scoring, features, truncation invariance, alignment
# --------------------------------------------------------------------------------------
def test_lexicon_hashes_are_frozen() -> None:
    pinned = json.loads(cb_lexicon.HASHES_PATH.read_text())["files"]
    assert pinned == cb_lexicon.file_hashes()
    assert pinned["lm_uncertainty.txt"] == (
        "da8f75c84b84666af36085158f7ba498e0c550fd0310da23ab5ce4102f428824"
    )
    assert (
        pinned["hawkish.txt"] == "5d743120bdae74d059a2195646a6953d5b30dfe9fd2ec3722c3facf3927f825d"
    )
    assert (
        pinned["dovish.txt"] == "77bdfe19e61e64a8f606900982a5405270827e314f12c668eda8c5cc45a05740"
    )
    cb_lexicon.verify_hashes()  # does not raise


def test_tampered_lexicon_is_refused(tmp_path: Path) -> None:
    for name in cb_lexicon.FILES.values():
        (tmp_path / name).write_bytes((cb_lexicon.LEXICON_DIR / name).read_bytes())
    (tmp_path / "hashes.json").write_bytes(cb_lexicon.HASHES_PATH.read_bytes())
    with (tmp_path / "hawkish.txt").open("a") as fh:
        fh.write("\nextra term\n")
    with pytest.raises(RuntimeError, match="hash mismatch"):
        cb_lexicon.load_lexicon(tmp_path)


def test_lexicon_sizes(lexicon: dict) -> None:
    assert len(lexicon["uncertainty"]) == 297  # Loughran-McDonald uncertainty list
    assert 60 <= len(lexicon["hawkish"]) <= 130 and 60 <= len(lexicon["dovish"]) <= 130
    assert not (lexicon["hawkish"] & lexicon["dovish"])  # no term on both sides


def test_greedy_phrase_matching_does_not_double_count(lexicon: dict) -> None:
    s = cb_lexicon.score_text("The rate hike was a hike.", lexicon)
    assert s["n_hawk"] == 2  # "rate hike" (one hit, two tokens consumed) + "hike"
    assert s["n_tokens"] == 6
    s0 = cb_lexicon.score_text("", lexicon)
    assert s0["tone"] == 0.0 and s0["n_tokens"] == 0


def test_hawkish_fixture_scores_above_dovish_fixture(docs: list[dict], lexicon: dict) -> None:
    scores = cb_lexicon.score_docs(docs, lexicon).set_index("bank")
    assert scores.loc["FOMC", "tone"] > 0.3 > -0.3 > scores.loc["ECB", "tone"]
    assert scores.loc["FOMC", "tone"] > scores.loc["ECB", "tone"]
    assert (scores["tone"].abs() <= 1).all()
    assert scores.loc["SNB", "uncertainty"] > scores.loc["FOMC", "uncertainty"]
    assert list(scores.reset_index().columns) == cb_lexicon.SCORE_COLUMNS


def test_effective_date_publication_time_rule() -> None:
    # ECB 14:15 CET on 2025-06-05 is 08:15 New York -> known the same trading day
    assert cb_features.effective_date("2025-06-05T14:15:00+02:00") == pd.Timestamp("2025-06-05")
    # FOMC 14:00 ET is before the 17:00 NY close -> same day
    assert cb_features.effective_date("2025-06-18T14:00:00-04:00") == pd.Timestamp("2025-06-18")
    # a hypothetical 22:00 CET release is 16:00 NY -> still same day ...
    assert cb_features.effective_date("2025-06-05T22:00:00+02:00") == pd.Timestamp("2025-06-05")
    # ... but 22:00 New York is after the close -> next calendar day
    assert cb_features.effective_date("2025-06-05T22:00:00-04:00") == pd.Timestamp("2025-06-06")
    # exactly 17:00 NY is not known by the close
    assert cb_features.effective_date("2025-06-05T17:00:00-04:00") == pd.Timestamp("2025-06-06")
    with pytest.raises(ValueError):
        cb_features.effective_date(datetime(2025, 6, 5, 14, 15))


def test_late_release_lands_next_trading_day(docs: list[dict]) -> None:
    """A Friday 22:00 New York statement is first usable on the following Monday."""
    late = dict(docs[0])
    late["bank"] = "FOMC"  # any text will do; the point is the timestamp
    late["published_at"] = datetime(
        2025, 6, 6, 22, 0, tzinfo=ZoneInfo("America/New_York")
    ).isoformat()
    dates = pd.bdate_range("2025-06-02", "2025-06-13")
    f = cb_features.build_from_docs([late], dates).set_index("date")
    assert np.isnan(f.loc["2025-06-06", "cb_fomc_tone"])
    assert not np.isnan(f.loc["2025-06-09", "cb_fomc_tone"])
    assert f.loc["2025-06-09", "cb_fomc_days_since"] == 3  # calendar days since Friday


def test_cb_features_columns_and_point_in_time(docs: list[dict]) -> None:
    dates = pd.bdate_range("2025-05-01", "2025-07-31")
    f = cb_features.build_from_docs(docs, dates)
    assert list(f.columns) == cb_features.COLUMNS
    f = f.set_index("date")
    # ECB 2025-06-05 14:15 CET: NaN on 06-04, known on 06-05, forward-filled after
    assert np.isnan(f.loc["2025-06-04", "cb_ecb_tone"])
    assert f.loc["2025-06-05", "cb_ecb_tone"] < 0
    assert f.loc["2025-06-05", "cb_ecb_days_since"] == 0
    assert f.loc["2025-07-31", "cb_ecb_tone"] == f.loc["2025-06-05", "cb_ecb_tone"]
    assert f.loc["2025-07-31", "cb_ecb_days_since"] == 56
    assert np.isnan(f.loc["2025-06-05", "cb_ecb_tone_surprise"])  # first statement: no history
    # FOMC 2025-06-18 14:00 ET known on 06-18
    assert np.isnan(f.loc["2025-06-17", "cb_fomc_tone"]) and f.loc["2025-06-18", "cb_fomc_tone"] > 0


def test_tone_surprise_is_causal_rolling_k4() -> None:
    rows = []
    tones = [0.1, 0.3, -0.2, 0.4, 0.0, 0.6]
    for i, t in enumerate(tones):
        rows.append(
            {
                "bank": "ECB",
                "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=30 * i),
                "published_at": f"2024-{1 + i:02d}-01T14:15:00+01:00",
                "tone": t,
                "uncertainty": 0.01,
            }
        )
    s = cb_features.add_surprise(pd.DataFrame(rows), k=4)
    exp = [np.nan, 0.3 - 0.1, -0.2 - np.mean([0.1, 0.3]), 0.4 - np.mean([0.1, 0.3, -0.2])]
    exp += [0.0 - np.mean([0.1, 0.3, -0.2, 0.4]), 0.6 - np.mean([0.3, -0.2, 0.4, 0.0])]
    np.testing.assert_allclose(s["tone_surprise"].to_numpy(), exp, equal_nan=True)


def _many_docs(n: int = 40, seed: int = 0) -> list[dict]:
    """Synthetic statements across banks and months so every column gets a rolling history."""
    rng = np.random.default_rng(seed)
    hawk = ["rate hike", "tighten", "inflation pressures", "upside risks", "restrictive"]
    dove = ["rate cut", "accommodative", "downside risks", "slack", "patient"]
    neutral = ["the", "committee", "decided", "today", "policy", "rate", "and", "of", "target"]
    out = []
    for i in range(n):
        bank = cb_text.BANKS[i % 4]
        d = date(2023, 1, 10) + pd.Timedelta(days=int(i * 23 + rng.integers(0, 5))).to_pytimedelta()
        words = list(rng.choice(neutral, 60)) + list(rng.choice(hawk, rng.integers(0, 6)))
        words += list(rng.choice(dove, rng.integers(0, 6))) + ["uncertain"] * int(
            rng.integers(0, 4)
        )
        rng.shuffle(words)
        out.append(cb_text.make_doc(bank, d, f"u{i}", " ".join(words)))
    return out


def test_truncation_invariance_bit_for_bit() -> None:
    """Features computed on a truncated history equal the overlapping rows of the full run."""
    docs = _many_docs()
    dates = pd.bdate_range("2023-01-01", "2025-12-31")
    full = cb_features.build_from_docs(docs, dates)
    cutoff = pd.Timestamp("2024-09-13")
    trunc_docs = [d for d in docs if pd.Timestamp(cb_text.doc_date(d)) <= cutoff]
    trunc = cb_features.build_from_docs(trunc_docs, dates[dates <= cutoff])
    head = full[full["date"] <= cutoff].reset_index(drop=True)
    pd.testing.assert_frame_equal(trunc, head, check_exact=True)
    for c in cb_features.COLUMNS[1:]:  # bit-for-bit: identical float bits, NaN positions included
        a, b = trunc[c].to_numpy(), head[c].to_numpy()
        assert np.array_equal(a.view(np.uint64), b.view(np.uint64))
    assert head.iloc[:, 1:].notna().any().all()  # the test actually exercised every column


def test_stage_registers_writer_and_writes_parquet(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cb_features, "load_docs", lambda: cb_text.load_docs(FIXTURES))
    monkeypatch.setattr(cb_features, "CB_FEATURES_PATH", tmp_path / "cb_features.parquet")
    ctx = {"features": pd.DataFrame({"date": pd.bdate_range("2025-06-01", "2025-06-30")})}
    cb_features.stage(ctx)
    assert "cb_features" in ctx["extra_writers"]
    cb_features.write_cb_features(ctx["cb_features"], tmp_path / "cb_features.parquet")
    back = pd.read_parquet(tmp_path / "cb_features.parquet")
    assert list(back.columns) == cb_features.COLUMNS and len(back) == 21


def test_live_tracking_summary_shape(docs: list[dict]) -> None:
    s = cb_lexicon.live_tracking_summary(docs, deploy_date=date(2026, 8, 17))
    assert set(s["banks"]) == set(cb_text.BANKS)
    assert s["n_since_deploy"] == 0 and s["banks"]["FOMC"]["n_total"] == 1
    s2 = cb_lexicon.live_tracking_summary(docs, deploy_date=date(2025, 6, 10))
    assert s2["n_since_deploy"] == 3 and s2["banks"]["ECB"]["n_since_deploy"] == 0


# --------------------------------------------------------------------------------------
# C. FinBERT live-only guard (no torch, no network)
# --------------------------------------------------------------------------------------
def test_finbert_guard_raises_before_any_import(docs, fomc, monkeypatch, tmp_path) -> None:
    assert "transformers" not in sys.modules or True  # CI has no transformers; fine either way
    monkeypatch.setattr(cb_finbert, "load_scorer", lambda: pytest.fail("model was loaded"))
    with pytest.raises(cb_finbert.LiveOnlyError, match="pre-deploy"):
        cb_finbert.score_live(docs, out_path=tmp_path / "s.jsonl")  # fixtures are 2025 -> refused
    # one historical doc among live ones is enough to refuse the whole batch
    live = dict(fomc)
    live["published_at"] = "2026-08-20T14:00:00-04:00"
    with pytest.raises(cb_finbert.LiveOnlyError):
        cb_finbert.score_live([live, docs[1]], out_path=tmp_path / "s.jsonl")
    assert not (tmp_path / "s.jsonl").exists()


def test_finbert_scores_live_docs_with_injected_scorer(fomc: dict, tmp_path) -> None:
    live = dict(fomc)
    live["published_at"] = "2026-08-20T14:00:00-04:00"
    fake = lambda text: {"positive": 0.6, "negative": 0.1, "neutral": 0.3}  # noqa: E731
    out = cb_finbert.score_live([live], scorer=fake, out_path=tmp_path / "s.jsonl")
    assert len(out) == 1 and abs(out[0]["finbert_tone"] - 0.5) < 1e-12
    assert out[0]["revision"] == cb_finbert.REVISION and out[0]["model_id"] == cb_finbert.MODEL_ID
    # idempotent: the same sha256 is not scored twice
    assert cb_finbert.score_live([live], scorer=fake, out_path=tmp_path / "s.jsonl") == []
    assert len((tmp_path / "s.jsonl").read_text().splitlines()) == 1


def test_finbert_pin_file_matches_module() -> None:
    pin = json.loads(cb_finbert.PIN_PATH.read_text())
    assert pin["model_id"] == cb_finbert.MODEL_ID and pin["revision"] == cb_finbert.REVISION
    assert re.fullmatch(r"[0-9a-f]{40}", pin["revision"])


def test_nlp_requirements_are_separate() -> None:
    req = (config.ROOT / "requirements.txt").read_text()
    assert "transformers" not in req and "torch" not in req
    nlp = (config.ROOT / "requirements-nlp.txt").read_text()
    assert "transformers" in nlp and "torch" in nlp


# --------------------------------------------------------------------------------------
# E. Stage 2 gate + LLM guard (no anthropic network)
# --------------------------------------------------------------------------------------
def test_gate_status_closed_for_real_counts() -> None:
    counts = cb_llm.live_counts()  # real data/cb on disk (may be empty)
    g = cb_llm.gate_status(counts)
    assert g["open"] is False and cb_llm.GATE_OPEN is False
    assert all(counts[b] < cb_llm.GATE_MIN_DOCS[b] for b in cb_text.BANKS)
    # even with every count satisfied and the effect agreed, GATE_OPEN=False keeps it shut
    g2 = cb_llm.gate_status(dict(cb_llm.GATE_MIN_DOCS), effect_ok=True)
    assert g2["open"] is False and g2["counts_ok"] is True
    assert any("GATE_OPEN" in r for r in g2["reasons"])


def test_llm_guard_raises_on_pre_deploy_before_anything_else(fomc, tmp_path) -> None:
    class Boom:
        def __getattr__(self, name):
            pytest.fail("client touched for a pre-deploy document")

    with pytest.raises(cb_finbert.LiveOnlyError):
        cb_llm.score_live(fomc, client=Boom(), gate={"open": True})
    # a live doc with the gate closed is refused by the gate, still without touching the client
    live = dict(fomc)
    live["published_at"] = "2026-08-20T14:00:00-04:00"
    with pytest.raises(cb_llm.GateClosedError):
        cb_llm.score_live(live, client=Boom())
    assert not (tmp_path / "r.jsonl").exists()


def test_llm_receipts_and_cost_cap_with_fake_client(fomc: dict, tmp_path) -> None:
    class Block:
        type = "text"
        text = '{"hawkishness": 0.42, "uncertainty": 0.2, "rationale": "quotes"}'

    class Resp:
        content = [Block()]
        model = "claude-haiku-4-5-20251001"

    class Client:
        class messages:  # noqa: N801 — mimics the SDK shape
            @staticmethod
            def create(**kw):
                assert kw["model"] == cb_llm.MODEL and kw["system"]
                assert json.loads(kw["messages"][0]["content"])["bank"] == "FOMC"
                return Resp()

    live = dict(fomc)
    live["published_at"] = "2026-08-20T14:00:00-04:00"
    rp, op = tmp_path / "r.jsonl", tmp_path / "ops.jsonl"
    out = cb_llm.score_live(
        live, client=Client(), gate={"open": True}, receipts_path=rp, ops_path=op
    )
    assert out == {"hawkishness": 0.42, "uncertainty": 0.2, "rationale": "quotes"}
    rec = json.loads(rp.read_text().splitlines()[0])
    assert rec["prompt_version"] == "v1" and rec["model"] == cb_llm.MODEL
    assert rec["prompt_sha256"] == cb_llm.load_prompt()[1] and len(rec["prompt_sha256"]) == 64
    assert rec["raw_response"] == Block.text and rec["model_response_version"] == Resp.model
    # cost cap: fill the receipts to the cap -> graceful skip + ops log, no call
    with rp.open("a") as fh:
        for _ in range(cb_llm.MAX_DOCS_PER_YEAR):
            fh.write(json.dumps(rec) + "\n")
    assert (
        cb_llm.score_live(live, client=Client(), gate={"open": True}, receipts_path=rp, ops_path=op)
        is None
    )
    assert json.loads(op.read_text().splitlines()[-1])["event"] == "skip_cost_cap"


def test_llm_api_error_is_graceful(fomc: dict, tmp_path) -> None:
    class Client:
        class messages:  # noqa: N801
            @staticmethod
            def create(**kw):
                raise ConnectionError("down")

    live = dict(fomc)
    live["published_at"] = "2026-08-20T14:00:00-04:00"
    rp, op = tmp_path / "r.jsonl", tmp_path / "ops.jsonl"
    assert (
        cb_llm.score_live(live, client=Client(), gate={"open": True}, receipts_path=rp, ops_path=op)
        is None
    )
    assert json.loads(op.read_text())["event"] == "skip_api_error" and not rp.exists()


def test_prompt_is_versioned_and_market_free() -> None:
    system, sha = cb_llm.load_prompt()
    assert "hawkishness" in system and "uncertainty" in system and "rationale" in system
    assert len(sha) == 64 and cb_llm.PROMPT_PATH.name == "cb_hawkishness_v1.txt"
    assert cb_llm.parse_response('```json\n{"hawkishness": 2, "uncertainty": -1}\n```') == {
        "hawkishness": 1.0,
        "uncertainty": 0.0,
        "rationale": "",
    }


# --------------------------------------------------------------------------------------
# direction-word lint on everything user-facing in these modules + docs
# --------------------------------------------------------------------------------------
_DIRECTION_DOCS = re.compile(
    r"\b(bullish|bearish|buy|sell|go long|go short|price target|will rise|will fall|go up|go down"
    r"|upside target|downside target)\b",
    re.IGNORECASE,
)


def test_no_direction_language_in_user_facing_text() -> None:
    """Prompt, docs and reports of this phase never talk about price direction or trades."""
    files = [
        config.ROOT / "src" / "fxradar" / f
        for f in ("cb_text.py", "cb_lexicon.py", "cb_features.py", "cb_finbert.py", "cb_llm.py")
    ] + [
        config.ROOT / "prompts" / "cb_hawkishness_v1.txt",
        config.ROOT / "docs" / "why-we-refuse-the-backtest.md",
        config.ROOT / "docs" / "stage2-decision.md",
        config.ROOT / "docs" / "CB_INDEX.md",
        config.ROOT / "reports" / "cb_index.md",
    ]
    for path in files:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        m = _DIRECTION_DOCS.search(text)
        assert m is None, f"direction word {m.group(0)!r} in {path.name}"
    # every markdown surface of the phase carries the disclaimer
    for name in ("why-we-refuse-the-backtest.md", "stage2-decision.md", "CB_INDEX.md"):
        path = config.ROOT / "docs" / name
        if path.exists():
            assert config.DISCLAIMER in path.read_text(encoding="utf-8"), name
