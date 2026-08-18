"""Arcade: a weekly regime-change forecasting game scored by Brier — practice, not trading."""

from __future__ import annotations

import html
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ui  # noqa: E402
from fxradar import arcade  # noqa: E402
from fxradar.config import DISCLAIMER  # noqa: E402

st.set_page_config(page_title="Arcade — FX Regime Radar", page_icon="📡", layout="wide")
ui.inject_css()
ui.sidebar(DISCLAIMER)
UNI_NAME, UNI, DIRS = ui.universe_selector()
PAIRS = list(UNI.pairs)
REGIMES_PATH = DIRS["data"] / "regimes.parquet"


@st.cache_data(show_spinner=False)
def load_regimes(mtime: float) -> pd.DataFrame:
    return pd.read_parquet(REGIMES_PATH)


regimes = load_regimes(os.path.getmtime(REGIMES_PATH) if REGIMES_PATH.exists() else -1.0)
conn = arcade.connect()

st.markdown(
    '<div class="fx-header"><div><span class="fx-wordmark">Arcade</span>'
    f'<span class="fx-sub">{html.escape(arcade.BANNER)}</span></div></div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="fx-card" style="padding:12px 16px"><span class="fx-muted">Once a week per pair you say how likely it is that the regime label changes within the next five trading days, and lock it. '
    "Only then do you see the model's number for the same question. Five trading days later both are scored with the Brier score — the same rule weather forecasters are judged by. "
    "Nothing here is about money; it is practice at saying probabilities you mean.</span></div>",
    unsafe_allow_html=True,
)

nickname_raw = st.text_input(
    "nickname (no account, no email — stored locally)",
    value=st.session_state.get("nick", ""),
    max_chars=24,
)
if not nickname_raw:
    st.caption("Enter a nickname to play. Nothing else happens until you do.")
    ui.footer(DISCLAIMER, "· " + arcade.BANNER)
    st.stop()
try:
    nick = arcade.clean_nickname(nickname_raw)
except ValueError as e:
    st.warning(str(e))
    st.stop()
st.session_state["nick"] = nick
arcade.record_visit(conn, nick)
live = {p: str(regimes[regimes["pair"] == p].sort_values("date").iloc[-1]["regime"]) for p in PAIRS}
badges_now = arcade.evaluate_badges(conn, nick, live_regimes=live)

# ---- observatory ------------------------------------------------------------------------
led = arcade.ledger(conn, nick)
rank = arcade.rank_for(led["resolved"], led["brier_user"])
streak = arcade.watch_streak(conn, nick)
c1, c2, c3 = st.columns(3)
with c1:
    ui.card(
        f'<div class="fx-kv"><span>rank</span><span style="font-weight:600">{html.escape(rank)}</span></div><div class="fx-kv" style="margin-top:6px"><span>watch streak</span><span class="fx-num">{streak} day{"s" if streak != 1 else ""}</span></div><div class="fx-muted" style="font-size:0.78rem;margin-top:8px">ranks come only from resolved calls and calibration — never from bold numbers</div>',
        title="Observatory",
    )
with c2:
    bu = f'{led["brier_user"]:.3f}' if led["brier_user"] is not None else "–"
    bm = f'{led["brier_model"]:.3f}' if led["brier_model"] is not None else "–"
    ui.card(
        f'<div class="fx-kv"><span>resolved calls</span><span class="fx-num">{led["resolved"]}</span></div><div class="fx-kv" style="margin-top:6px"><span>your rolling Brier</span><span class="fx-num">{bu}</span></div><div class="fx-kv" style="margin-top:6px"><span>model rolling Brier</span><span class="fx-num">{bm}</span></div><div class="fx-kv" style="margin-top:6px"><span>calls you scored better</span><span class="fx-num">{led["wins"]} / {led["resolved"]}</span></div>',
        title="Season ledger (lower Brier wins)",
    )
with c3:
    all_b = "".join(
        f'<div class="fx-kv" style="margin-top:4px"><span>{html.escape(b)}</span><span>{"✓" if b in badges_now else "·"}</span></div>'
        for b in arcade.BADGES
    )
    ui.card(
        all_b
        + '<div class="fx-muted" style="font-size:0.78rem;margin-top:8px">learning badges only</div>',
        title="Badges",
    )

# ---- the call cards ---------------------------------------------------------------------
st.markdown(
    '<div style="font-weight:600;margin:10px 0 6px 2px">This week\'s calls</div>',
    unsafe_allow_html=True,
)
cols = st.columns(len(PAIRS))
for col, p in zip(cols, PAIRS, strict=True):
    pre = arcade.pre_lock_payload(regimes, p)
    with col:
        locked_id = st.session_state.get(f"locked_{p}_{pre.week_key}")
        if locked_id is None and arcade.already_called_this_week(conn, nick, p, pre.call_date):
            row = conn.execute(
                "SELECT id FROM calls WHERE nickname=? AND pair=? ORDER BY id DESC LIMIT 1",
                (nick, p),
            ).fetchone()
            locked_id = row[0] if row else None
        head = f'<div style="display:flex;justify-content:space-between;align-items:center"><span style="font-weight:600">{UNI.display(p)}</span>{ui.regime_pill(pre.regime)}</div><div class="fx-muted" style="font-size:0.8rem;margin:6px 0">as of {pre.call_date} · day {pre.days_in_regime} of this regime · week {pre.week_key}</div>'
        if locked_id is None:
            st.markdown(
                f'<div class="fx-card" style="margin-bottom:6px">{head}<div class="fx-muted" style="font-size:0.82rem">How likely is it that this label is different at some point in the next 5 trading days?</div></div>',
                unsafe_allow_html=True,
            )
            prob = (
                st.slider("your probability", 0, 100, 25, 5, key=f"slider_{p}", format="%d%%") / 100
            )
            if st.button("lock my call", key=f"lock_{p}"):
                try:
                    cid = arcade.place_call(conn, regimes, nick, p, prob)
                    st.session_state[f"locked_{p}_{pre.week_key}"] = cid
                    st.rerun()
                except ValueError as e:
                    st.warning(str(e))
        else:
            v = arcade.post_lock_view(conn, locked_id)
            outcome = (
                "pending" if v["outcome"] is None else ("changed" if v["outcome"] else "no change")
            )
            body = (
                head
                + f'<div class="fx-kv" style="margin-top:8px"><span>your call</span><span class="fx-num">{v["prob"] * 100:.0f}%</span></div><div class="fx-kv" style="margin-top:4px"><span>model (revealed after lock)</span><span class="fx-num">{v["model_risk"] * 100:.0f}%</span></div><div class="fx-kv" style="margin-top:4px"><span>outcome</span><span>{outcome}</span></div>'
            )
            if v["outcome"] is not None:
                body += f'<div class="fx-kv" style="margin-top:4px"><span>Brier you / model</span><span class="fx-num">{v["brier_user"]:.3f} / {v["brier_model"]:.3f}</span></div>'
            ui.card(body)

# ---- storm gallery ----------------------------------------------------------------------
st.markdown(
    '<div style="font-weight:600;margin:14px 0 6px 2px">Storm gallery — verified episodes, unlocked by reading</div>',
    unsafe_allow_html=True,
)
opened = arcade.unlocked_storms(conn, nick)
gcols = st.columns(3)
for i, storm in enumerate(arcade.load_storms()):
    with gcols[i % 3]:
        is_open = storm["id"] in opened
        with st.expander(
            f'{"✓ " if is_open else ""}{storm["title"]} — {UNI.display(storm["pair"])} {storm["date"]}',
            expanded=False,
        ):
            if not is_open:
                arcade.open_storm(conn, nick, storm["id"])
            st.markdown(
                f'<div class="fx-muted" style="font-size:0.82rem">siren percentile {storm["siren_pct"]:.0f} · regime next day: {storm["regime_next_day"]}</div>',
                unsafe_allow_html=True,
            )
            for line in storm["story"].strip().split("\n"):
                st.markdown(
                    f'<div style="font-size:0.9rem;line-height:1.5">{html.escape(line)}</div>',
                    unsafe_allow_html=True,
                )

st.caption(
    "Storage: a local sqlite file (data/arcade.db). On free-tier hosting it is reset on redeploy; the v3 Postgres migration makes it durable."
)
ui.footer(DISCLAIMER, "· " + arcade.BANNER)
