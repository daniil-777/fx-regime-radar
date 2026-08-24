"""Ask — one input, five outcomes, every answer templated from data with receipts (phase 46).

Routing is rules first and a small model second; the model only ever emits an enum. Documents
come from five official central-bank sites, cached per day, quoted verbatim with receipts.
This page computes no numbers: it reads the daily artifact and fetches documents.
"""

from __future__ import annotations

import html
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ask import log as asklog  # noqa: E402
from ask import render as askrender  # noqa: E402
from ask import retrieve as askretrieve  # noqa: E402
from ask.route import route_with_meta  # noqa: E402

import ui  # noqa: E402
from fxradar import config  # noqa: E402
from fxradar.config import DISCLAIMER  # noqa: E402

ui.sidebar(DISCLAIMER)
st.title("Ask")

_PRESS = {
    "SNB": "https://www.snb.ch/en/news-publications/press-releases",
    "ECB": "https://www.ecb.europa.eu/press/html/index.en.html",
    "Fed": "https://www.federalreserve.gov/newsevents/pressreleases.htm",
    "BoE": "https://www.bankofengland.co.uk/news",
    "BIS": "https://www.bis.org/press/index.htm",
}
_DOMAIN = {
    "SNB": "snb.ch",
    "ECB": "ecb.europa.eu",
    "Fed": "federalreserve.gov",
    "BoE": "bankofengland.co.uk",
    "BIS": "bis.org",
}


@st.cache_data(show_spinner=False)
def _tag() -> str:
    try:
        t = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            capture_output=True,
            text=True,
            cwd=config.ROOT,
            timeout=3,
        )
        return t.stdout.strip().lstrip("v") or "2.41.0"
    except Exception:
        return "2.41.0"


@st.cache_data(show_spinner=False)
def _latest_stats(mtime: float) -> dict:
    r = pd.read_parquet(config.REGIMES_PATH)
    latest = r[r["date"] == r["date"].max()]
    return {row.pair: row._asdict() for row in latest.itertuples()}


def _stats_for(question: str) -> dict:
    """The pair the question names, else the lead pair — always named on the card."""
    stats = _latest_stats(config.REGIMES_PATH.stat().st_mtime)
    q = question.lower()
    for p in config.PAIRS:
        if p.lower() in q.replace("/", ""):
            return stats[p]
    return stats[config.PAIRS[0]]


def _chip(text: str) -> str:
    return (
        f'<span style="font-family:{ui.FONT_MONO};font-size:11px;color:{ui.MUTED};'
        f'border:1px solid {ui.LINE};border-radius:99px;padding:2px 9px;">{html.escape(text)}</span>'
    )


def _card_html(card) -> str:
    strip = card.strip or {}
    regime = strip.get("regime", "")
    color = ui.REGIME_COLORS.get(regime, ui.TEXT)
    quote = (
        f'<blockquote style="border-left:2px solid {ui.LINE};margin:12px 0;padding:4px 14px;'
        f'color:{ui.TEXT};font-style:italic;">{html.escape(card.quote)}</blockquote>'
        if card.quote
        else ""
    )
    chips = " ".join(_chip(c) for c in card.receipts)
    src = (
        f'&nbsp;<a href="{html.escape(card.source_url)}" style="color:{ui.ACCENT};font-size:12px;">view source ↗</a>'
        if card.source_url
        else ""
    )
    receipts = (
        f'<div style="margin:10px 0;display:flex;gap:6px;flex-wrap:wrap;align-items:center;">{chips}{src}</div>'
        if chips or src
        else ""
    )
    strip_html = (
        f'<div style="border-top:1px solid {ui.LINE};margin-top:14px;padding-top:10px;">'
        f'<span style="color:{color};font-weight:500;">{html.escape(regime)}</span>'
        f'<span style="font-family:{ui.FONT_MONO};font-size:12.5px;color:{ui.MUTED};'
        f'font-variant-numeric:tabular-nums;"> · {html.escape(strip.get("pair", ""))} · {html.escape(strip.get("text", ""))}</span></div>'
    )
    return (
        f'<div style="min-height:280px;">'
        f'<div style="font-size:17px;color:{ui.TEXT};">{html.escape(card.verdict)}</div>'
        f'<div style="font-family:{ui.FONT_MONO};font-size:11.5px;color:{ui.DIM};margin:2px 0 10px;">{html.escape(card.subline)}</div>'
        f'<div style="color:{ui.MUTED};max-width:70ch;">{html.escape(card.body)}</div>'
        f"{quote}{receipts}{strip_html}"
        f'<div style="font-size:12px;color:{ui.DIM};margin-top:12px;">{html.escape(card.footer_note)}</div>'
        f'<div style="font-family:{ui.FONT_MONO};font-size:11.5px;color:{ui.DIM};margin-top:4px;">{html.escape(card.trust_line)}</div>'
        f"</div>"
    )


def _ask(question: str) -> None:
    stats = _stats_for(question)
    tag = _tag()
    routed, meta = route_with_meta(question)
    evidence = None
    holder = st.empty()
    t_render0 = time.perf_counter()
    if routed.kind == "official_fact":
        domain = _DOMAIN.get(routed.institution, "snb.ch")
        holder.markdown(
            f'<div style="min-height:280px;color:{ui.DIM};">Checking {domain}…</div>',
            unsafe_allow_html=True,
        )
        evidence = askretrieve.find_official(routed)
        if evidence is None:
            press = _PRESS.get(routed.institution, _PRESS["SNB"])
            holder.markdown(
                f'<div style="min-height:280px;color:{ui.MUTED};">{domain} didn\'t respond. '
                f'Retry, or open the <a href="{press}" style="color:{ui.ACCENT};">official press page ↗</a>.</div>',
                unsafe_allow_html=True,
            )
            asklog.append(
                question,
                {
                    **_slipdict(routed, meta),
                    "gate": "none",
                    "url": "",
                    "content_sha256": "",
                    "receipt_id": "",
                    "credits": 0,
                    "cache_hit": False,
                    "latency_ms": _lat(meta, 0, 0, 0),
                },
            )
            return
    card = askrender.apply_gates(
        routed,
        askrender.render(routed, evidence, stats, list(config.PAIRS), tag),
        evidence,
        stats,
        tag,
    )
    render_ms = round((time.perf_counter() - t_render0) * 1000, 1)
    with holder.container():
        ui.card(_card_html(card))
    ev_lat = evidence.latency_ms if evidence else {}
    asklog.append(
        question,
        {
            **_slipdict(routed, meta),
            "gate": card.gate,
            "url": evidence.url if evidence else "",
            "content_sha256": evidence.content_sha256 if evidence else "",
            "receipt_id": evidence.receipt_id if evidence else "",
            "credits": evidence.credits if evidence else 0,
            "cache_hit": bool(ev_lat.get("cache_hit", False)),
            "latency_ms": _lat(meta, ev_lat.get("search", 0), ev_lat.get("extract", 0), render_ms),
        },
    )


def _slipdict(routed, meta) -> dict:
    return {
        "kind": routed.kind,
        "institution": routed.institution,
        "doc_type": routed.doc_type,
        "window": routed.window,
        "asset": routed.asset,
        "language": routed.language,
        "router": routed.router,
        "override": meta.get("override", "none"),
        "model_id": meta.get("model_id", "none"),
        "prompt_version": "ask-route-v1",
    }


def _lat(meta, search, extract, render_ms) -> dict:
    return {
        "rules": meta.get("latency_rules_ms", 0),
        "model": meta.get("latency_model_ms", 0),
        "search": search,
        "extract": extract,
        "render": render_ms,
    }


question = st.text_input(
    "Your question", placeholder="What did the ECB decide?", label_visibility="collapsed"
)
go = st.button("Ask", type="primary", use_container_width=False)
c1, c2, c3 = st.columns(3)
ex1 = c1.button("What's the regime today?", use_container_width=True)
ex2 = c2.button("What did the SNB say this month?", use_container_width=True)
ex3 = c3.button("Should I buy euros now?", use_container_width=True)

asked = (
    question
    if (go and question.strip())
    else (
        "What's the regime today?"
        if ex1
        else "What did the SNB say this month?" if ex2 else "Should I buy euros now?" if ex3 else ""
    )
)
if asked:
    _ask(asked)
else:
    st.markdown(
        f'<div style="min-height:280px;color:{ui.DIM};">Ask about today\'s conditions, an official '
        f"central-bank statement, or anything else — every answer says where it came from.</div>",
        unsafe_allow_html=True,
    )

ui.footer(DISCLAIMER)
