"""Phase 27/28 tests: weekly report determinism, direction-language lint, RSS/HTML safety, metrics."""

from __future__ import annotations

import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fxradar import config, metrics_page, weekly

MONDAY = "2026-08-17"
PAIRS = ["EURUSD", "USDCHF", "GBPUSD"]

# The banned list lives HERE (not in weekly.py) so no banned word is ever a literal in the module.
BANNED = [
    "rise", "fall", "up", "down", "buy", "sell", "long", "short", "target", "bullish",
    "bearish", "rally", "drop", "crash", "appreciate", "depreciate", "strengthen", "weaken",
]  # fmt: skip
BANNED_RE = re.compile(r"\b(" + "|".join(BANNED) + r")\b", re.I)


# --------------------------------------------------------------------------------------
# synthetic artifacts (no network, no disk)
# --------------------------------------------------------------------------------------
def _synthetic(with_band: bool = False) -> dict:
    dates = pd.bdate_range("2026-06-01", MONDAY)
    rng = np.random.default_rng(7)
    reg, px = [], []
    regimes_by_pair = {"EURUSD": "calm", "USDCHF": "crisis", "GBPUSD": "chop"}
    for pair in PAIRS:
        close = 1.1 + np.cumsum(rng.normal(0, 0.003, len(dates)))
        for i, d in enumerate(dates):
            px.append({"date": d, "pair": pair, "close": close[i]})
            row = {
                "date": d,
                "pair": pair,
                "regime": regimes_by_pair[pair],
                "regime_prob": 0.91,
                "hmm_entropy": 0.2,
                "days_in_regime": i + 1,
                "change_risk_5d": 0.12 + 0.2 * (pair == "USDCHF"),
                "top_drivers": np.array(["vol_ratio", "rng_hl", "hmm_entropy"]),
                "anomaly_score": 0.1,
                "anomaly_pct": 95.0 if pair == "USDCHF" else 40.0,
                "model_version": "test",
            }
            if with_band:
                row["risk_lo"], row["risk_hi"] = (
                    row["change_risk_5d"] - 0.05,
                    row["change_risk_5d"] + 0.07,
                )
            reg.append(row)
    events = pd.DataFrame(
        {
            "date": ["2026-08-17", "2026-09-10", "2026-09-16", "2026-09-24", "2026-08-10"],
            "type": ["SNB", "ECB", "Fed", "BOE", "FOMC"],
            "source": ["test"] * 5,
        }
    )
    live = {"n_forecasts": 3, "n_resolved": 0, "since": MONDAY, "metrics": None, "min_resolved": 20}
    return {
        "regimes": pd.DataFrame(reg),
        "prices": pd.DataFrame(px),
        "events": events,
        "live": live,
    }


@pytest.fixture(scope="module")
def synth() -> dict:
    return _synthetic()


@pytest.fixture(scope="module")
def built(synth: dict) -> dict:
    return weekly.build_weekly(
        synth["regimes"], synth["prices"], synth["live"], events=synth["events"], as_of="2026-08-19"
    )


# --------------------------------------------------------------------------------------
# build + determinism
# --------------------------------------------------------------------------------------
def test_report_monday_rolls_back_to_monday() -> None:
    assert str(weekly.report_monday("2026-08-19")) == MONDAY  # Wednesday → Monday
    assert str(weekly.report_monday(MONDAY)) == MONDAY
    assert str(weekly.report_monday("2026-08-23")) == MONDAY  # Sunday → the Monday before


def test_build_is_deterministic_and_uses_generic_lights(synth: dict, built: dict) -> None:
    again = weekly.build_weekly(
        synth["regimes"], synth["prices"], synth["live"], events=synth["events"], as_of="2026-08-19"
    )
    assert built == again
    assert weekly.to_markdown(built) == weekly.to_markdown(again)
    assert built["date"] == MONDAY and set(built["pairs"]) == set(PAIRS)
    lights = {p: v["light"] for p, v in built["pairs"].items()}
    assert lights == {"EURUSD": "wait", "USDCHF": "hedge", "GBPUSD": "ladder"}
    assert all(v["light_source"] == "generic rule" for v in built["pairs"].values())
    assert built["pairs"]["EURUSD"]["band_text"] == "band not yet available"
    assert "USD/CHF is in a crisis regime" in built["pairs"]["USDCHF"]["narration"]


def test_events_days_to_next_meeting_and_aliases(built: dict) -> None:
    ev = built["events"]
    assert ev["SNB"] == {"date": MONDAY, "days": 0}
    assert (
        ev["ECB"]["days"] == 24 and ev["FOMC"]["date"] == "2026-09-16"
    )  # "Fed" → FOMC; past FOMC ignored
    assert ev["BOE"]["days"] == 38
    lines = weekly.event_lines(built)
    assert lines[0].startswith("SNB today") and "ECB in 24 days" in lines[1]


def test_band_and_treasury_light_when_available(synth: dict) -> None:
    s = _synthetic(with_band=True)
    treasury = {"pairs": {"EURUSD": {"light": "ladder", "light_reason": "from the artifact"}}}
    w = weekly.build_weekly(s["regimes"], s["prices"], None, treasury=treasury, as_of=MONDAY)
    assert w["pairs"]["EURUSD"]["band_text"].startswith("band 7%–19%")
    assert w["pairs"]["EURUSD"]["light"] == "ladder"
    assert w["pairs"]["EURUSD"]["light_source"] == "treasury_risk.json"
    assert w["pairs"]["USDCHF"]["light"] == "hedge"  # pair missing from the artifact → generic
    assert w["events"] is None and weekly.event_lines(w) == ["calendar not available"]
    assert "not yet scored" in weekly.live_line(w)  # no live record → pending, never 0


def test_live_line_shows_brier_when_scored(synth: dict) -> None:
    live = {
        "n_forecasts": 60,
        "n_resolved": 45,
        "since": "2026-05-04",
        "metrics": {"brier": 0.0912},
    }
    w = weekly.build_weekly(synth["regimes"], synth["prices"], live, as_of=MONDAY)
    assert "60 forecasts since 2026-05-04, 45 resolved, Brier 0.091." in weekly.live_line(w)


# --------------------------------------------------------------------------------------
# renderers
# --------------------------------------------------------------------------------------
def test_markdown_has_front_matter_disclaimer_and_proof_link(built: dict) -> None:
    md = weekly.to_markdown(built)
    fm = weekly.read_front_matter(md)
    assert fm["date"] == MONDAY and fm["title"].endswith(MONDAY)
    assert fm["summary"] == "EUR/USD calm · USD/CHF crisis · GBP/USD chop"
    assert config.DISCLAIMER in md
    assert built["proof_url"].endswith("/proof") and built["proof_url"] in md
    assert "never personalised" in md


def test_html_is_email_safe(built: dict) -> None:
    h = weekly.to_html(built)
    assert "<script" not in h.lower() and "<style" not in h.lower() and "<link" not in h.lower()
    assert "max-width:600px" in h and 'role="presentation"' in h
    assert config.DISCLAIMER in h
    urls = set(re.findall(r"https?://[^\s\"'<>]+", h))
    assert urls and all(u.startswith(built["app_url"]) for u in urls), urls
    for regime in ["calm", "crisis", "chop"]:  # word + dot, never colour-only
        assert weekly.LIGHT_TOKENS[regime] in h and f"— {regime}" in h
    assert weekly.LIGHT_TOKENS["bg"] == "#FFFFFF" and weekly.LIGHT_TOKENS["card"] == "#F4F6FA"
    assert "IBM Plex Mono" in h and "font-feature-settings:'tnum'" in h


def test_rss_is_well_formed_and_keeps_52(tmp_path: Path, built: dict) -> None:
    entries = [
        {
            "date": str(pd.Timestamp(MONDAY) - pd.Timedelta(weeks=i)),
            "title": f"t{i}",
            "summary": "s",
        }
        for i in range(60)
    ]
    entries = [{**e, "date": e["date"][:10]} for e in entries]
    xml = weekly.to_rss(entries, base_url="https://example.org/weekly")
    root = ET.fromstring(xml)
    items = root.findall("./channel/item")
    assert len(items) == weekly.RSS_KEEP
    assert items[0].find("title").text == "t0"
    assert config.DISCLAIMER in root.find("./channel/description").text
    assert config.DISCLAIMER in items[0].find("description").text
    assert items[0].find("pubDate").text == "Mon, 17 Aug 2026 06:30:00 +0000"


def test_write_outputs_roundtrip_feed_index_and_ops_log(
    tmp_path: Path, built: dict, monkeypatch
) -> None:
    wdir, feed = tmp_path / "weekly", tmp_path / "feed.xml"
    paths = weekly.write_outputs(built, weekly_dir=wdir, feed_path=feed)
    assert paths["md"].exists() and paths["html"].exists() and feed.exists()
    assert weekly.collect_entries(wdir)[0]["date"] == MONDAY
    assert MONDAY in (wdir / "index.md").read_text()
    ET.fromstring(feed.read_text())
    ops = tmp_path / "ops_log.jsonl"
    weekly.log_ops("weekly_report_published", MONDAY, path=ops)
    rec = json.loads(ops.read_text().strip())
    assert rec["event"] == "weekly_report_published" and rec["date"] == MONDAY and "ts" in rec


# --------------------------------------------------------------------------------------
# direction-language lint: every string literal in weekly.py + the rendered outputs
# --------------------------------------------------------------------------------------
def test_no_direction_language_in_templates_or_module(built: dict) -> None:
    hits = {}
    for s in list(weekly.TEMPLATES.values()) + weekly.module_string_literals():
        found = BANNED_RE.findall(s)
        if found:
            hits[s[:60]] = sorted(set(w.lower() for w in found))
    assert not hits, hits
    # and the rendered synthetic outputs (which include the narrator's template sentences)
    for text in (weekly.to_markdown(built), weekly.to_html(built)):
        assert not BANNED_RE.search(text), BANNED_RE.search(text).group(0)


# --------------------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------------------
def test_metrics_honest_zeros_when_nothing_exists(tmp_path: Path) -> None:
    m = metrics_page.build_metrics(
        data_dir=tmp_path / "data", docs_dir=tmp_path / "docs", generated_at="x"
    )
    for key in [
        "ledger_days_live",
        "forecasts_recorded",
        "forecasts_resolved",
        "report_subscribers",
        "active_api_keys",
        "design_partners",
        "mrr_chf",
        "weekly_reports_published",
    ]:
        assert m[key] == 0, key
    assert m["latest_weekly_report"] is None and m["generated_at"] == "x"
    table = metrics_page.readme_table(m)
    assert "| Ledger days live | 0 |" in table and "| MRR (CHF) | 0 |" in table


def test_metrics_reads_ledger_keys_partners_and_reports(tmp_path: Path) -> None:
    data, docs = tmp_path / "data", tmp_path / "docs"
    data.mkdir(), (docs / "outreach").mkdir(parents=True), (docs / "weekly").mkdir()
    (data / "live_record.json").write_text(
        json.dumps({"days_recorded": 12, "n_forecasts": 36, "n_resolved": 21})
    )
    with sqlite3.connect(data / "keys.db") as con:
        con.execute(
            "CREATE TABLE api_keys (id INTEGER PRIMARY KEY, key_hash TEXT, label TEXT, tier TEXT, "
            "created_at TEXT, revoked INTEGER)"
        )
        con.executemany(
            "INSERT INTO api_keys (key_hash, label, tier, created_at, revoked) VALUES (?,?,?,?,?)",
            [("h1", "a", "pro", "t", 0), ("h2", "b", "free", "t", 0), ("h3", "c", "pro", "t", 1)],
        )
    (docs / "outreach" / "tracking.csv").write_text(
        "company,type,contact_role,status,monthly_chf,notes\n"
        "A,sme,cfo,signed,79,\nB,fid,partner,signed,500,\nC,sme,cfo,contacted,,\nD,sme,cfo,declined,79,\n"
    )
    (docs / "weekly" / "2026-08-10.md").write_text("---\ndate: 2026-08-10\n---\n")
    (docs / "weekly" / "2026-08-17.md").write_text("---\ndate: 2026-08-17\n---\n")
    (data / "subscribers.json").write_text(json.dumps({"subscribers": ["x", "y"]}))
    m = metrics_page.build_metrics(data_dir=data, docs_dir=docs, generated_at="x")
    assert m["ledger_days_live"] == 12 and (m["forecasts_recorded"], m["forecasts_resolved"]) == (
        36,
        21,
    )
    assert m["active_api_keys"] == 2
    assert m["design_partners"] == 2 and m["mrr_chf"] == 579.0
    assert m["weekly_reports_published"] == 2 and m["latest_weekly_report"] == "2026-08-17"
    assert m["report_subscribers"] == 2
    assert "| MRR (CHF) | 579 |" in metrics_page.readme_table(m)


def test_metrics_keys_db_without_table_is_zero(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    sqlite3.connect(data / "keys.db").close()  # empty db, no api_keys table
    m = metrics_page.build_metrics(data_dir=data, docs_dir=tmp_path / "docs", generated_at="x")
    assert m["active_api_keys"] == 0


def test_tracking_csv_has_header_and_no_personal_data() -> None:
    path = config.DOCS_DIR / "outreach" / "tracking.csv"
    df = pd.read_csv(path)
    assert list(df.columns) == ["company", "type", "contact_role", "status", "monthly_chf", "notes"]
    assert len(df) == 15 and set(df["status"]) == {"todo"}
    assert df["company"].str.startswith("PLACEHOLDER").all()
    assert not df.astype(str).apply(lambda c: c.str.contains("@")).any().any()


# --------------------------------------------------------------------------------------
# app pages (artifact-only, disclaimer present)
# --------------------------------------------------------------------------------------
@pytest.mark.skipif(not metrics_page.METRICS_PATH.exists(), reason="metrics.json not built")
def test_metrics_page_renders() -> None:
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(config.ROOT / "app/views/metrics.py"), default_timeout=60).run()
    assert not at.exception, at.exception
    assert config.DISCLAIMER in [c.value for c in at.sidebar.caption]
    txt = " ".join(m.value for m in at.markdown)
    assert "Zeros are real zeros" in txt and config.DISCLAIMER in txt


@pytest.mark.skipif(not list(weekly.WEEKLY_DIR.glob("????-??-??.md")), reason="no weekly report")
def test_weekly_page_renders_latest_report() -> None:
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(config.ROOT / "app/views/weekly.py"), default_timeout=60).run()
    assert not at.exception, at.exception
    txt = " ".join(m.value for m in at.markdown)
    assert "FX weather report" in txt and config.DISCLAIMER in txt
