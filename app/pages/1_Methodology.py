"""Methodology page: the pipeline, the HMM and its metaphor, filtered vs smoothed, limitations."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ui  # noqa: E402
from fxradar.config import DISCLAIMER  # noqa: E402

st.set_page_config(page_title="Methodology — FX Regime Radar", page_icon="📡", layout="wide")
ui.inject_css()
ui.sidebar(DISCLAIMER)

st.markdown(
    '<div class="fx-header"><div><span class="fx-wordmark">Methodology</span><span class="fx-sub">how the weather station works</span></div></div>',
    unsafe_allow_html=True,
)

ui.card(
    """
<p><b>The pipeline.</b> Every weekday a scheduled job downloads daily prices for EUR/USD, USD/CHF and GBP/USD,
cleans obviously corrupted prints (dropped, never repaired), builds a small set of strictly backward-looking
features (returns, 20/60-day volatility, a 5-day/60-day volatility ratio, one-month momentum, intraday range,
cross-pair correlation), scores the current market <i>regime</i> with a hidden Markov model, and writes small
files. This dashboard only reads those files — it never trains or downloads anything, which is why it loads in
about a second.</p>
""",
    title="Pipeline writes, app reads",
)

ui.card(
    """
<p><b>A hidden Markov model</b> assumes the market is always in one of a few unobserved <i>moods</i> — here four:
<span class="fx-pill" style="color:#34D399;background:#34D39922">calm</span>
<span class="fx-pill" style="color:#60A5FA;background:#60A5FA22">trend</span>
<span class="fx-pill" style="color:#FBBF24;background:#FBBF2422">chop</span>
<span class="fx-pill" style="color:#F87171;background:#F8717122">crisis</span> —
and that each mood produces returns, volatility and momentum with its own typical pattern. Moods are sticky:
today's mood is most likely yesterday's. That stickiness (the transition matrix) is exactly what a plain
clustering method lacks: k-means would happily flip labels every day, an HMM only changes its mind when the
evidence accumulates.</p>
<p><b>The mood metaphor.</b> You cannot measure a person's mood directly, but you can watch behaviour and update
your belief day by day. Regime labels are the same: an inference from observed behaviour, with a confidence
number attached. The confidence bar on each weather card is that belief; "day N of this regime" is how long
the belief has been stable.</p>
<p><b>Naming the moods.</b> The model learns four anonymous states on 2005–2016 data only. They are named by a
fixed rule from that training period: lowest average volatility = calm, highest = crisis; of the two in
between, the one with stronger average momentum = trend, the other = chop. The rule is frozen with the model.</p>
""",
    title="The regime model, in plain English",
)

ui.card(
    """
<p><b>Filtered</b> probabilities answer "given everything up to and including today, which mood are we in?" —
that is what a forecaster on the day could know, and it is the only kind used anywhere in this project.
<b>Smoothed</b> probabilities answer "knowing how the following weeks played out, which mood was it?" — they look
better on a chart and are useless in real time, so they never appear here.</p>
<p>The same discipline applies to every feature: a value dated <i>t</i> uses rows up to <i>t</i> only, and a test
recomputes everything on a truncated history and checks that the overlapping rows are identical.</p>
""",
    title="Filtered vs smoothed — the honesty rule",
)

ui.card(
    """
<p><b>The orb</b> on the dashboard is a display of the same numbers as the cards: the regime sets its colour and
motion (calm drifts, trend spins, chop jitters, crisis is fast and chaotic), the change risk multiplies the jitter,
and a siren reading above 98 fires a decaying pulse. It computes nothing.</p>
<p>The model is trained once on 2005–2016 and scored forward; the dashed line on the chart marks where the
out-of-sample period begins (2017). Everything to the right is data the model had never seen when it was fitted.
The regime anatomy table is computed on that out-of-sample period only.</p>
""",
    title="Out of sample",
)

ui.card(
    """
<ul>
<li><b>Daily data only.</b> Intraday storms are averaged away; the source's daily close is a start-of-day snapshot,
so returns run one day behind highs and lows.</li>
<li><b>Label noise.</b> Filtered labels can flicker near state boundaries, and the trend/chop split is sensitive to
the random seed of the fit (a five-seed check gives 40–100 % label agreement). Read the confidence with the label.</li>
<li><b>Descriptive, not predictive.</b> A regime describes recent conditions. Nothing here predicts price direction —
by design.</li>
<li><b>Frozen naming rule and rare events.</b> One extreme episode (the January-2015 Swiss franc shock) can capture a
whole state; for USD/CHF the "crisis" label essentially never fires and its 2008–2011 stress is labelled "chop".</li>
<li><b>Single training window.</b> 2020 and 2022 are scored by a model that never learnt from them; a periodic
expanding refit is planned.</li>
<li><b>Gaussian emissions.</b> Fat tails are absorbed by the high-volatility state rather than modelled.</li>
</ul>
""",
    title="Limitations",
)

# arcade badge hook: reading this page unlocks "methodology reader" for the current nickname
if st.session_state.get("nick"):
    try:
        from fxradar import arcade

        _conn = arcade.connect()
        arcade.record_event(_conn, st.session_state["nick"], "methodology_opened")
        _conn.close()
    except Exception:  # the reading surface must never break because of the game
        pass

ui.footer(DISCLAIMER)
