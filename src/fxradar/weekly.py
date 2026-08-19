"""Weekly FX weather report (phase 27): one free, useful page every Monday.

Reads the committed artifacts (regimes, prices, live record, optional calendar / treasury light)
and writes, for the report Monday, `docs/weekly/<YYYY-MM-DD>.md`, an e-mail-safe light-mode HTML
twin, the RSS feed `docs/feed.xml`, `docs/weekly/index.md`, and one ops-log line so a silent
Monday is visible. Everything is deterministic given the artifacts: the only date in the output is
the report Monday (`--date` / `as_of`), never "now".

Guardrails: the narration is the narrator's deterministic TEMPLATE path (`narrate.build_stats` +
`narrate.template_narrate`), never the LLM; the traffic light is GENERIC (computed from the public
regime only, never from a reader's position); no direction language anywhere (a lint test scans
every string literal in this module); every rendering carries config.DISCLAIMER.
"""

from __future__ import annotations

import argparse
import ast
import html
import json
import logging
import os
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import pandas as pd

from fxradar import config, narrate
from fxradar import tokens as tk

log = logging.getLogger(__name__)

WEEKLY_DIR = config.DOCS_DIR / "weekly"
FEED_PATH = config.DOCS_DIR / "feed.xml"
INDEX_PATH = WEEKLY_DIR / "index.md"
OPS_LOG_PATH = config.DATA_DIR / "ops_log.jsonl"
EVENTS_PATH = config.DATA_DIR / "events.csv"
TREASURY_PATH = config.DATA_DIR / "treasury_risk.json"
LIVE_RECORD_PATH = config.DATA_DIR / "live_record.json"
DETAIL_PATH = config.DATA_DIR / "siren_detail.parquet"

DEFAULT_APP_URL = "https://fx-regime-radar.streamlit.app"
DEFAULT_REPO_URL = "https://github.com/daniil-777/fx-regime-radar"
PROOF_PATH = "/proof"
RSS_KEEP = 52  # one year of Mondays
EVENT_TYPES = ["SNB", "ECB", "FOMC", "BOE"]
EVENT_ALIASES = {"FED": "FOMC", "FEDERAL RESERVE": "FOMC", "BANK OF ENGLAND": "BOE"}
REGIME_ORDER = ["calm", "trend", "chop", "crisis"]
LIGHT_ORDER = ["hedge", "wait", "ladder"]

# The e-mail HTML palette (BRIEF rule 8, light variant). ONE dict, moved to tokens.json later.
LIGHT_TOKENS = {  # the light (e-mail) variant from design/tokens.json — no hex literals here
    "bg": tk.LIGHT["bg"],
    "card": tk.LIGHT["card"],
    "line": tk.LIGHT["line"],
    "text": tk.LIGHT["text"],
    "muted": tk.LIGHT["text_secondary"],
    "accent": tk.ACCENT,
    **tk.REGIME_COLORS,
}
FONT_UI = tk.FONT_UI
FONT_DISPLAY = tk.FONT_DISPLAY
FONT_MONO = tk.FONT_MONO

# Every user-facing sentence lives here so the direction-language lint has one place to look
# (the test also scans the whole module source, so nothing can hide outside this dict).
TEMPLATES = {
    "title": "FX weather report — week of {date}",
    "subtitle": "Regimes, 5-day change risk and anomaly level for EUR/USD, USD/CHF and GBP/USD "
    "as of the {as_of} close. Computed numbers only — never a price call.",
    "light_hedge": "Regime is crisis: the generic rule favours acting on open exposures now "
    "rather than waiting.",
    "light_wait": "Regime is calm: the generic rule favours waiting and re-checking next Monday.",
    "light_ladder": "Regime is neither calm nor crisis: the generic rule favours splitting a "
    "decision into steps (a ladder) instead of one date.",
    "light_note": "Generic traffic light from the public regime only — the same for every reader, "
    "never personalised, never advice.",
    "band_missing": "band not yet available",
    "band": "band {lo}–{hi}",
    "events_missing": "calendar not available",
    "events_none": "no scheduled {kind} meeting in the calendar",
    "event_line": "{kind} in {days} days ({date})",
    "event_today": "{kind} today ({date})",
    "live_line": "Live forward record: {n} forecasts since {since}, {resolved} resolved, "
    "Brier {brier}. Every forecast is hash-chained before its outcome exists.",
    "brier_pending": "not yet scored (fewer than {min_resolved} forecasts resolved)",
    "proof_line": "Proof page (ledger, drift monitor, frozen test beside the live record): {url}",
    "footer": "{disclaimer} The report is generated from published artifacts every Monday; "
    "nothing here is a forecast of price direction.",
    "rss_title": "FX Regime Radar — weekly FX weather report",
    "rss_description": "Free Monday report: regimes, 5-day change risk, anomaly level and a "
    "generic traffic light for EUR/USD, USD/CHF and GBP/USD. {disclaimer}",
    "index_title": "Weekly FX weather reports",
    "index_intro": "One free page every Monday, generated from the published artifacts. "
    "Subscribe via RSS: {feed}. {disclaimer}",
    "empty_summary": "no report yet",
}


# --------------------------------------------------------------------------------------
# dates
# --------------------------------------------------------------------------------------
def report_monday(as_of: date | str | None = None) -> date:
    """The most recent Monday on or before `as_of` (default: today, UTC)."""
    d = pd.Timestamp(as_of).date() if as_of is not None else datetime.now(UTC).date()
    return d - timedelta(days=d.weekday())


def _fmt_pct(x: float | None) -> str:
    return "—" if x is None or pd.isna(x) else f"{100 * float(x):.0f}%"


# --------------------------------------------------------------------------------------
# build: artifacts in, one dict out (deterministic)
# --------------------------------------------------------------------------------------
def _latest_rows(regimes: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    cut = regimes[pd.to_datetime(regimes["date"]) <= as_of]
    return cut.sort_values("date").groupby("pair").tail(1).set_index("pair")


def _events_for(events: pd.DataFrame | None, as_of: pd.Timestamp) -> dict[str, dict] | None:
    """Next SNB / ECB / FOMC / BOE meeting on or after `as_of`; None when no calendar is available."""
    if events is None or len(events) == 0 or "date" not in events or "type" not in events:
        return None
    ev = events.copy()
    ev["date"] = pd.to_datetime(ev["date"])
    ev["type"] = ev["type"].astype(str).str.upper().str.strip().replace(EVENT_ALIASES)
    out: dict[str, dict] = {}
    for kind in EVENT_TYPES:
        nxt = ev[(ev["type"] == kind) & (ev["date"] >= as_of)].sort_values("date")
        if len(nxt):
            d = nxt.iloc[0]["date"]
            out[kind] = {"date": str(d.date()), "days": int((d - as_of).days)}
        else:
            out[kind] = None
    return out


def generic_light(regime: str) -> tuple[str, str]:
    """Traffic light from the public regime only: crisis → hedge, calm → wait, else ladder."""
    if regime == "crisis":
        return "hedge", TEMPLATES["light_hedge"]
    if regime == "calm":
        return "wait", TEMPLATES["light_wait"]
    return "ladder", TEMPLATES["light_ladder"]


def _light_for(pair: str, regime: str, treasury: dict | None) -> tuple[str, str, str]:
    """(light, reason, source) — the treasury artifact when present, else the generic rule."""
    if treasury:
        entry = (treasury.get("pairs") or {}).get(pair) or {}
        light = entry.get("light")
        if light in LIGHT_ORDER:
            return light, str(entry.get("light_reason") or ""), "treasury_risk.json"
    light, reason = generic_light(regime)
    return light, reason, "generic rule"


def _live_summary(live_record: dict | None) -> dict:
    lr = live_record or {}
    metrics = lr.get("metrics") or {}
    brier = metrics.get("brier")
    return {
        "n_forecasts": int(lr.get("n_forecasts") or 0),
        "n_resolved": int(lr.get("n_resolved") or 0),
        "since": lr.get("since") or "—",
        "brier": None if brier is None else round(float(brier), 3),
        "min_resolved": int(lr.get("min_resolved") or 20),
        "chain_ok": bool(lr.get("chain_ok", False)),
    }


def build_weekly(
    regimes: pd.DataFrame,
    prices: pd.DataFrame,
    live_record: dict | None,
    report: dict | None = None,
    events: pd.DataFrame | None = None,
    treasury: dict | None = None,
    as_of: date | str | None = None,
    detail: pd.DataFrame | None = None,
    app_url: str | None = None,
) -> dict:
    """One dict describing the report for the Monday of `as_of` — numbers and fixed phrases only.

    `report` (data/report.json) is used ONLY for the nearest-neighbour date of the siren when no
    `detail` frame is passed; its narration text is never copied (the weekly always uses the
    deterministic template so the direction-language lint covers every word).
    """
    monday = report_monday(as_of)
    as_of_ts = pd.Timestamp(monday)
    app_url = (app_url or os.environ.get("FXRADAR_APP_URL") or DEFAULT_APP_URL).rstrip("/")
    latest = _latest_rows(regimes, as_of_ts)
    data_date = str(pd.to_datetime(latest["date"]).max().date()) if len(latest) else "—"
    if detail is None:  # never touch the disk inside the builder: an empty frame = no neighbour
        detail = pd.DataFrame(columns=["pair", "date", "nn_date"])
    cut_r = regimes[pd.to_datetime(regimes["date"]) <= as_of_ts]
    cut_p = prices[pd.to_datetime(prices["date"]) <= as_of_ts]
    next_events = _events_for(events, as_of_ts)

    pairs: dict[str, dict] = {}
    for pair in [p for p in config.PAIRS if p in latest.index]:
        row = latest.loc[pair]
        stats = narrate.build_stats(pair, cut_r, detail, cut_p)
        rep = (report or {}).get(pair) or {}
        rep_stats = rep.get("stats") or {}
        if stats.get("nearest_neighbor_date") is None and rep_stats.get("date") == stats["date"]:
            stats["nearest_neighbor_date"] = rep_stats.get("nearest_neighbor_date")
        lo = row.get("risk_lo") if "risk_lo" in latest.columns else None
        hi = row.get("risk_hi") if "risk_hi" in latest.columns else None
        has_band = lo is not None and hi is not None and pd.notna(lo) and pd.notna(hi)
        regime = str(row["regime"])
        light, reason, light_source = _light_for(pair, regime, treasury)
        pairs[pair] = {
            "display": config.UNIVERSE.display(pair),
            "date": stats["date"],
            "regime": regime,
            "regime_word": narrate.REGIME_WORDS.get(regime, regime),
            "regime_prob": stats["regime_prob"],
            "days_in_regime": stats["days_in_regime"],
            "change_risk_5d": stats["change_risk_5d"],
            "risk_lo": round(float(lo), 3) if has_band else None,
            "risk_hi": round(float(hi), 3) if has_band else None,
            "band_text": (
                TEMPLATES["band"].format(lo=_fmt_pct(lo), hi=_fmt_pct(hi))
                if has_band
                else TEMPLATES["band_missing"]
            ),
            "anomaly_pct": stats["anomaly_pct"],
            "light": light,
            "light_reason": reason,
            "light_source": light_source,
            "narration": narrate.template_narrate(stats),
        }

    return {
        "date": str(monday),
        "data_date": data_date,
        "title": TEMPLATES["title"].format(date=monday),
        "subtitle": TEMPLATES["subtitle"].format(as_of=data_date),
        "pairs": pairs,
        "events": next_events,
        "live": _live_summary(live_record),
        "app_url": app_url,
        "proof_url": app_url + PROOF_PATH,
        "disclaimer": config.DISCLAIMER,
    }


# --------------------------------------------------------------------------------------
# shared phrase helpers
# --------------------------------------------------------------------------------------
def event_lines(weekly: dict) -> list[str]:
    ev = weekly.get("events")
    if ev is None:
        return [TEMPLATES["events_missing"]]
    out = []
    for kind in EVENT_TYPES:
        e = ev.get(kind)
        if not e:
            out.append(TEMPLATES["events_none"].format(kind=kind))
        elif e["days"] == 0:
            out.append(TEMPLATES["event_today"].format(kind=kind, date=e["date"]))
        else:
            out.append(TEMPLATES["event_line"].format(kind=kind, days=e["days"], date=e["date"]))
    return out


def live_line(weekly: dict) -> str:
    lv = weekly["live"]
    brier = (
        f"{lv['brier']:.3f}"
        if lv["brier"] is not None
        else TEMPLATES["brier_pending"].format(min_resolved=lv["min_resolved"])
    )
    return TEMPLATES["live_line"].format(
        n=lv["n_forecasts"], since=lv["since"], resolved=lv["n_resolved"], brier=brier
    )


def summary_line(weekly: dict) -> str:
    """'EUR/USD calm · USD/CHF calm · GBP/USD chop' — the RSS / index one-liner."""
    parts = [f"{p['display']} {p['regime']}" for p in weekly["pairs"].values()]
    return " · ".join(parts) if parts else TEMPLATES["empty_summary"]


# --------------------------------------------------------------------------------------
# renderers
# --------------------------------------------------------------------------------------
def to_markdown(weekly: dict) -> str:
    """GitHub-flavoured markdown with a small YAML front-matter block (scanned for the RSS feed)."""
    lines = [
        "---",
        f'title: "{weekly["title"]}"',
        f"date: {weekly['date']}",
        f'summary: "{summary_line(weekly)}"',
        "---",
        "",
        f"# {weekly['title']}",
        "",
        weekly["subtitle"],
        "",
        "| Pair | Regime | Confidence | Day in regime | 5-day change risk | Anomaly pct. | Light |",
        "|---|---|---:|---:|---|---:|---|",
    ]
    for p in weekly["pairs"].values():
        lines.append(
            f"| {p['display']} | {p['regime']} | {_fmt_pct(p['regime_prob'])} | {p['days_in_regime']} "
            f"| {_fmt_pct(p['change_risk_5d'])} ({p['band_text']}) | {p['anomaly_pct']:.0f} | {p['light']} |"
        )
    lines += ["", "## Pair by pair", ""]
    for p in weekly["pairs"].values():
        lines += [
            f"### {p['display']} — {p['regime']}",
            "",
            p["narration"],
            "",
            f"**Traffic light: {p['light']}.** {p['light_reason']} _{TEMPLATES['light_note']}_",
            "",
        ]
    lines += ["## Central-bank calendar", ""]
    lines += [f"- {e}" for e in event_lines(weekly)]
    lines += [
        "",
        "## Live record",
        "",
        live_line(weekly),
        "",
        TEMPLATES["proof_line"].format(url=weekly["proof_url"]),
        "",
        "---",
        "",
        f"_{TEMPLATES['footer'].format(disclaimer=weekly['disclaimer'])}_",
        "",
    ]
    return "\n".join(lines)


def _dot(regime: str) -> str:
    colour = LIGHT_TOKENS.get(regime, LIGHT_TOKENS["muted"])
    return (
        f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;'
        f'background:{colour};vertical-align:middle;margin-right:6px"></span>'
    )


def to_html(weekly: dict) -> str:
    """E-mail-safe twin: table layout, inline styles only, 600px max, light palette, no scripts."""
    t = LIGHT_TOKENS
    esc = html.escape
    num = f"font-family:{FONT_MONO};font-feature-settings:'tnum';"
    body_font = f"font-family:{FONT_UI};color:{t['text']};font-size:15px;line-height:1.5;"

    # Summary table: five compact columns so a 390px phone never scrolls sideways (the
    # confidence and the conformal band live in the per-pair cards below).
    tcell = f"padding:6px 6px;border-bottom:1px solid {t['line']};{body_font}font-size:13px;"
    thead = f"padding:6px 6px;border-bottom:2px solid {t['line']};{body_font}color:{t['muted']};font-size:11px;text-align:left;"
    rows = []
    for p in weekly["pairs"].values():
        rows.append(
            "<tr>"
            f'<td style="{tcell}"><b>{esc(p["display"])}</b></td>'
            f'<td style="{tcell}">{_dot(p["regime"])}{esc(p["regime"])}</td>'
            f'<td style="{tcell}{num}text-align:right">{_fmt_pct(p["change_risk_5d"])}</td>'
            f'<td style="{tcell}{num}text-align:right">{p["anomaly_pct"]:.0f}</td>'
            f'<td style="{tcell}">{esc(p["light"])}</td>'
            "</tr>"
        )
    table = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse;background:{t["bg"]}">'
        f'<tr><th style="{thead}">Pair</th><th style="{thead}">Regime</th><th style="{thead}text-align:right">5-day risk</th>'
        f'<th style="{thead}text-align:right">Anom. pct.</th><th style="{thead}">Light</th></tr>'
        + "".join(rows)
        + "</table>"
    )

    cards = []
    for p in weekly["pairs"].values():
        cards.append(
            f'<tr><td style="padding:0 0 12px 0"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="width:100%;background:{t["card"]};border-radius:12px"><tr><td style="padding:14px 16px;{body_font}">'
            f'<div style="font-family:{FONT_DISPLAY};font-size:17px;font-weight:600;margin-bottom:6px">'
            f'{_dot(p["regime"])}{esc(p["display"])} — {esc(p["regime"])}</div>'
            f'<div style="{num}font-size:12px;color:{t["muted"]};margin-bottom:6px">confidence {_fmt_pct(p["regime_prob"])} · day {p["days_in_regime"]} · '
            f'5-day change risk {_fmt_pct(p["change_risk_5d"])} ({esc(p["band_text"])}) · anomaly pct. {p["anomaly_pct"]:.0f}</div>'
            f'<div style="color:{t["muted"]}">{esc(p["narration"])}</div>'
            f'<div style="margin-top:10px"><b>Traffic light: {esc(p["light"])}.</b> {esc(p["light_reason"])}</div>'
            f'<div style="margin-top:6px;color:{t["muted"]};font-size:12px">{esc(TEMPLATES["light_note"])}</div>'
            "</td></tr></table></td></tr>"
        )

    events_html = "".join(
        f'<li style="{body_font}margin:2px 0"><span style="{num}font-size:13px">{esc(e)}</span></li>'
        for e in event_lines(weekly)
    )
    proof = esc(weekly["proof_url"])
    app = esc(weekly["app_url"])
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{esc(weekly['title'])}</title></head>"
        f'<body style="margin:0;padding:0;background:{t["bg"]};{body_font}">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;background:{t["bg"]}"><tr><td align="center" style="padding:20px 12px">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;table-layout:fixed;background:{t["bg"]}">'
        f'<tr><td style="padding:0 0 6px 0;font-family:{FONT_DISPLAY};font-size:22px;font-weight:700;color:{t["text"]}">'
        f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{t["accent"]};margin-right:8px"></span>{esc(weekly["title"])}</td></tr>'
        f'<tr><td style="padding:0 0 16px 0;{body_font}color:{t["muted"]}">{esc(weekly["subtitle"])}</td></tr>'
        f'<tr><td style="padding:0 0 18px 0">{table}</td></tr>'
        + "".join(cards)
        + f'<tr><td style="padding:6px 0 4px 0;font-family:{FONT_DISPLAY};font-size:16px;font-weight:600">Central-bank calendar</td></tr>'
        f'<tr><td style="padding:0 0 14px 0"><ul style="margin:0;padding-left:18px">{events_html}</ul></td></tr>'
        f'<tr><td style="padding:6px 0 4px 0;font-family:{FONT_DISPLAY};font-size:16px;font-weight:600">Live record</td></tr>'
        f'<tr><td style="padding:0 0 6px 0;{body_font}">{esc(live_line(weekly))}</td></tr>'
        f'<tr><td style="padding:0 0 18px 0;word-break:break-all;{body_font}">Proof page: <a href="{proof}" style="color:{t["text"]};text-decoration:underline">{proof}</a>'
        f' · App: <a href="{app}" style="color:{t["text"]};text-decoration:underline">{app}</a></td></tr>'
        f'<tr><td style="padding:12px 0 0 0;border-top:1px solid {t["line"]};{body_font}color:{t["muted"]};font-size:12px">'
        f'{esc(TEMPLATES["footer"].format(disclaimer=weekly["disclaimer"]))}</td></tr>'
        "</table></td></tr></table></body></html>\n"
    )


def to_rss(entries: list[dict], base_url: str | None = None) -> str:
    """RSS 2.0 for the newest RSS_KEEP entries ({date, title, summary}); dates are Mondays 06:30 UTC."""
    base_url = (
        base_url
        or os.environ.get("FXRADAR_WEEKLY_URL")
        or f"{DEFAULT_REPO_URL}/blob/main/docs/weekly"
    ).rstrip("/")
    entries = sorted(entries, key=lambda e: e["date"], reverse=True)[:RSS_KEEP]
    desc = TEMPLATES["rss_description"].format(disclaimer=config.DISCLAIMER)

    def _pub(d: str) -> str:
        ts = pd.Timestamp(d).replace(hour=6, minute=30, tzinfo=UTC)
        return ts.strftime("%a, %d %b %Y %H:%M:%S +0000")

    items = []
    for e in entries:
        link = f"{base_url}/{e['date']}.md"
        items.append(
            "    <item>\n"
            f"      <title>{xml_escape(e['title'])}</title>\n"
            f"      <link>{xml_escape(link)}</link>\n"
            f'      <guid isPermaLink="false">fx-regime-radar-weekly-{e["date"]}</guid>\n'
            f"      <pubDate>{_pub(e['date'])}</pubDate>\n"
            f"      <description>{xml_escape(e['summary'])}. {xml_escape(config.DISCLAIMER)}</description>\n"
            "    </item>"
        )
    last = _pub(entries[0]["date"]) if entries else _pub(str(report_monday()))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n'
        "  <channel>\n"
        f"    <title>{xml_escape(TEMPLATES['rss_title'])}</title>\n"
        f"    <link>{xml_escape(base_url)}</link>\n"
        f"    <description>{xml_escape(desc)}</description>\n"
        "    <language>en</language>\n"
        f"    <lastBuildDate>{last}</lastBuildDate>\n"
        + "\n".join(items)
        + ("\n" if items else "")
        + "  </channel>\n</rss>\n"
    )


# --------------------------------------------------------------------------------------
# feed + index: scan docs/weekly/*.md front-matter (no YAML dependency)
# --------------------------------------------------------------------------------------
_FM_RE = re.compile(r"^---\n(.*?)\n---", re.S)


def read_front_matter(text: str) -> dict:
    m = _FM_RE.match(text)
    out: dict[str, str] = {}
    if not m:
        return out
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


def collect_entries(weekly_dir: Path = WEEKLY_DIR) -> list[dict]:
    """{date, title, summary} for every docs/weekly/YYYY-MM-DD.md, newest first."""
    out = []
    for p in sorted(weekly_dir.glob("????-??-??.md"), reverse=True):
        fm = read_front_matter(p.read_text())
        out.append(
            {
                "date": fm.get("date", p.stem),
                "title": fm.get("title", TEMPLATES["title"].format(date=p.stem)),
                "summary": fm.get("summary", TEMPLATES["empty_summary"]),
            }
        )
    return out


def to_index(entries: list[dict], feed_rel: str = "../feed.xml") -> str:
    lines = [
        f"# {TEMPLATES['index_title']}",
        "",
        TEMPLATES["index_intro"].format(feed=feed_rel, disclaimer=config.DISCLAIMER),
        "",
    ]
    lines += [f"- [{e['date']}]({e['date']}.md) — {e['summary']}" for e in entries]
    return "\n".join(lines) + "\n"


def log_ops(event: str, report_date: str, path: Path = OPS_LOG_PATH) -> None:
    """Append one JSON line to data/ops_log.jsonl (the timestamp is the real publish time)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": event,
        "date": report_date,
    }
    with path.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")


# --------------------------------------------------------------------------------------
# lint helper (the banned-word list itself lives in tests/test_weekly.py, so no banned word
# is ever a literal in this module)
# --------------------------------------------------------------------------------------
def module_string_literals() -> list[str]:
    """Every string literal in this module's source (so the lint sees HTML/RSS scaffolding too)."""
    src = Path(__file__).read_text()
    return [
        n.value
        for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


# --------------------------------------------------------------------------------------
# I/O edges
# --------------------------------------------------------------------------------------
def _load_json(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def write_outputs(weekly: dict, weekly_dir: Path = WEEKLY_DIR, feed_path: Path = FEED_PATH) -> dict:
    """Write md + html for the report, then rebuild index.md and feed.xml from the directory."""
    weekly_dir.mkdir(parents=True, exist_ok=True)
    md_path = weekly_dir / f"{weekly['date']}.md"
    html_path = weekly_dir / f"{weekly['date']}.html"
    md_path.write_text(to_markdown(weekly))
    html_path.write_text(to_html(weekly))
    entries = collect_entries(weekly_dir)
    (weekly_dir / "index.md").write_text(to_index(entries))
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    feed_path.write_text(to_rss(entries))
    return {"md": md_path, "html": html_path, "index": weekly_dir / "index.md", "feed": feed_path}


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Write this Monday's weekly FX weather report.")
    ap.add_argument("--date", default=None, help="any date; the report is for its Monday")
    args = ap.parse_args(argv)

    regimes = pd.read_parquet(config.REGIMES_PATH)
    prices = pd.read_parquet(config.PRICES_PATH)
    events = pd.read_csv(EVENTS_PATH) if EVENTS_PATH.exists() else None
    detail = pd.read_parquet(DETAIL_PATH) if DETAIL_PATH.exists() else None
    weekly = build_weekly(
        regimes,
        prices,
        _load_json(LIVE_RECORD_PATH),
        _load_json(config.REPORT_PATH),
        events=events,
        treasury=_load_json(TREASURY_PATH),
        as_of=args.date,
        detail=detail,
    )
    paths = write_outputs(weekly)
    log_ops("weekly_report_published", weekly["date"])
    for k, p in paths.items():
        print(f"wrote {k}: {p.relative_to(config.ROOT)}")
    print(
        f"ops log: {OPS_LOG_PATH.relative_to(config.ROOT)} ← weekly_report_published {weekly['date']}"
    )


if __name__ == "__main__":
    main()
