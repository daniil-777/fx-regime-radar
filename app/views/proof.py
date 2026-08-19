"""Proof — "Don't trust us. Verify." Reads artifacts only (CLAUDE.md rule 8).

The live forward-test scoreboard (phase 20), conformal coverage receipt (phase 22), drift status,
the ledger download and the three-line verification instructions. Nothing on this page is
computed from models; every number is in a committed file anyone can re-derive.
"""

from __future__ import annotations

import html
import json
import os
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ui  # noqa: E402
from fxradar import config  # noqa: E402
from fxradar.config import DISCLAIMER  # noqa: E402

ui.sidebar(DISCLAIMER)
DATA = config.ROOT / "data"
REPORTS = config.ROOT / "reports"
REPO_URL = os.environ.get("FXRADAR_REPO_URL", "https://github.com/daniil-777/fx-regime-radar")


def _mtime(path: Path) -> float:
    return os.path.getmtime(path) if path.exists() else -1.0


@st.cache_data(show_spinner=False)
def load_json(path: str, mtime: float) -> dict:
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else {}


@st.cache_data(show_spinner=False)
def load_parquet(path: str, mtime: float) -> pd.DataFrame:
    return pd.read_parquet(path) if Path(path).exists() else pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_text(path: str, mtime: float) -> str:
    p = Path(path)
    return p.read_text() if p.exists() else ""


live = load_json(str(DATA / "live_record.json"), _mtime(DATA / "live_record.json"))
status = load_json(str(DATA / "status.json"), _mtime(DATA / "status.json"))
coverage = load_json(
    str(DATA / "conformal_coverage.json"), _mtime(DATA / "conformal_coverage.json")
)
board = load_json(str(REPORTS / "live_scoreboard.json"), _mtime(REPORTS / "live_scoreboard.json"))
ledger = load_parquet(str(DATA / "ledger.parquet"), _mtime(DATA / "ledger.parquet"))
head = load_text(str(DATA / "ledger_head.txt"), _mtime(DATA / "ledger_head.txt")).split()
cb_live = load_json(
    str(DATA / "cb" / "live_tracking.json"), _mtime(DATA / "cb" / "live_tracking.json")
)

st.markdown(
    '<div class="fx-header"><div><span class="fx-wordmark">Proof</span>'
    '<span class="fx-sub">don’t trust us — verify · the live record of the FX majors universe</span></div></div>',
    unsafe_allow_html=True,
)

if not live:
    ui.card(
        "No live record yet. The first daily pipeline run (`make pipeline`) writes "
        "`data/ledger.parquet` and `data/live_record.json`; this page fills itself from them.",
        title="Nothing to verify yet",
    )
    ui.footer(DISCLAIMER)
    st.stop()

# ---- trust strip -------------------------------------------------------------------------------
m = live.get("metrics") or {}
fz = live.get("frozen_test") or {}
cov_live = (coverage.get("live") or {}).get("coverage")
cov_test = (coverage.get("frozen_test") or {}).get("overall")
head_hash = head[0] if head else live.get("head_hash", "")
chain_ok = bool(live.get("chain_ok"))
ui.kpi_strip(
    [
        ui.kpi(
            "forward-test days",
            f"{live.get('days_recorded', 0)}",
            f"since {live.get('since') or '—'} · {live.get('n_forecasts', 0)} forecasts",
        ),
        ui.kpi(
            "live Brier vs frozen",
            f"{m['brier']:.3f}" if m.get("brier") is not None else "warming up",
            f"frozen test {fz.get('brier', float('nan')):.3f} · {live.get('n_resolved', 0)}/{live.get('min_resolved', 20)} resolved",
            (
                ui.REGIME_COLORS["calm"]
                if m.get("brier") is not None
                and m.get("base_rate_brier")
                and m["brier"] < m["base_rate_brier"]
                else ui.TEXT
            ),
        ),
        ui.kpi(
            "coverage vs 90 % target",
            (
                f"{cov_live:.0%}"
                if cov_live is not None
                else (f"{cov_test:.1%}" if cov_test is not None else "—")
            ),
            (
                "live, matured rows"
                if cov_live is not None
                else "frozen test (live band: warming up)"
            ),
        ),
        ui.kpi(
            "chain head",
            (head_hash[:10] + "…") if head_hash else "—",
            ("✓ verified" if chain_ok else "✗ BROKEN") + f" · {len(ledger)} rows",
            ui.REGIME_COLORS["calm"] if chain_ok else ui.REGIME_COLORS["crisis"],
        ),
        ui.kpi(
            "models",
            "stale" if status.get("model_stale") else "fresh",
            f"drift monitor · {status.get('data_through', '')}",
            ui.REGIME_COLORS["crisis"] if status.get("model_stale") else ui.REGIME_COLORS["calm"],
        ),
    ]
)

# ---- scoreboard ----------------------------------------------------------------------------------
ui.card(
    '<div class="fx-muted" style="font-size:0.84rem;line-height:1.5">Every weekday the pipeline appends the forecasts it just published '
    "(one row per pair, newest date only, never backfilled) to an append-only SHA-256 hash-chained ledger "
    "<em>before</em> the outcome exists. Five trading days later each row is resolved against the regimes that "
    "actually arrived and scored with the same code as the frozen test — PR-AUC, precision/recall at the frozen "
    "threshold, Brier; never accuracy. Each model version is its own segment, so a refit cannot launder an old record. "
    f"Numbers appear at {live.get('min_resolved', 20)} resolved rows; null means not defined yet, never 0.</div>",
    title="What this page proves — and what it does not",
)
if board:
    tbl = pd.DataFrame(board)[
        [
            "model_version",
            "family",
            "since",
            "through",
            "n_forecasts",
            "n_resolved",
            "brier",
            "base_rate_brier",
            "pr_auc",
            "precision",
            "recall",
        ]
    ]
    tbl.columns = [
        "model version",
        "family",
        "since",
        "through",
        "forecasts",
        "resolved",
        "Brier ↓",
        "base-rate Brier",
        "PR-AUC ↑",
        "precision",
        "recall",
    ]
    ui.card(
        ui.html_table(
            tbl.fillna("—"),
            {
                "Brier ↓": "{:.3f}",
                "base-rate Brier": "{:.3f}",
                "PR-AUC ↑": "{:.3f}",
                "precision": "{:.2f}",
                "recall": "{:.2f}",
            },
        )
        + f'<div class="fx-muted" style="font-size:0.78rem;margin-top:8px">Frozen test (2019+, scored once): PR-AUC <span class="fx-num">{fz.get("pr_auc", float("nan")):.3f}</span> · Brier <span class="fx-num">{fz.get("brier", float("nan")):.3f}</span> (base rate <span class="fx-num">{fz.get("base_rate_brier", float("nan")):.3f}</span>) · n = <span class="fx-num">{fz.get("n", 0):,}</span></div>',
        title="Live scoreboard by model segment",
    )

# ---- coverage receipt ---------------------------------------------------------------------------
if coverage:
    ft = coverage.get("frozen_test", {})
    roll = ft.get("rolling_120d", {})
    qs = coverage.get("q", {})
    left, right = st.columns([3, 2])
    with left:
        if roll:
            xs = pd.to_datetime(list(roll.keys()))
            fig = go.Figure()
            fig.add_hline(y=0.9, line=dict(color=ui.MUTED, width=1, dash="dash"))
            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=list(roll.values()),
                    mode="lines",
                    line=dict(color=ui.REGIME_COLORS["trend"], width=1.4),
                    name="rolling coverage",
                    hovertemplate="%{x|%Y-%m-%d}<br>%{y:.1%}<extra></extra>",
                )
            )
            fig.update_layout(
                template=ui.PLOTLY_TEMPLATE,
                height=260,
                margin=dict(l=40, r=10, t=24, b=30),
                yaxis=dict(tickformat=".0%", range=[0.7, 1.0]),
                showlegend=False,
                title=dict(
                    text="Empirical coverage on the frozen test (120-day rolling) vs the 90 % line",
                    font=dict(size=13),
                ),
            )
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    with right:
        rows = pd.DataFrame(
            {
                "regime": list(qs.keys()),
                "band half-width q": list(qs.values()),
                "test coverage": [ft.get("per_regime", {}).get(r) for r in qs],
            }
        )
        t_html = ui.html_table(
            rows.fillna("—"), {"band half-width q": "{:.2f}", "test coverage": "{:.1%}"}
        )
        for r in qs:
            t_html = t_html.replace(f"<td>{r}</td>", f"<td>{ui.regime_pill(r)}</td>")
        ui.card(
            t_html
            + f'<div class="fx-muted" style="font-size:0.78rem;margin-top:8px">Mondrian split conformal, α = 0.1, calibrated on the 2017–2018 validation years only '
            f'(also used for the forecaster’s early stopping and threshold — a documented dual use). Overall frozen-test coverage <span class="fx-num">{(ft.get("overall") or 0):.1%}</span> on n = <span class="fx-num">{ft.get("n", 0):,}</span>. '
            "Time series are not exchangeable, so we report <em>empirical</em> coverage instead of citing the theorem. "
            f'Live: <span class="fx-num">{(coverage.get("live") or {}).get("n", 0)}</span> matured rows with a band'
            + (
                f' · coverage <span class="fx-num">{cov_live:.0%}</span>'
                if cov_live is not None
                else ""
            )
            + ".</div>",
            title="Coverage receipt",
        )

# ---- drift status -----------------------------------------------------------------------------------
if status:
    feats = (
        pd.DataFrame(status.get("features", {}))
        .T.reset_index()
        .rename(columns={"index": "feature"})
    )
    if len(feats):
        feats = feats[["feature", "psi", "train_p75", "train_p95", "status", "ks"]]
        hmm = pd.DataFrame(status.get("hmm", {})).T.reset_index().rename(columns={"index": "pair"})
        c1, c2 = st.columns([3, 2])
        with c1:
            ui.card(
                ui.html_table(
                    feats,
                    {"psi": "{:.2f}", "train_p75": "{:.2f}", "train_p95": "{:.2f}", "ks": "{:.2f}"},
                )
                + f'<div class="fx-muted" style="font-size:0.78rem;margin-top:8px">PSI of the last {status.get("window_days", 60)} days against 10 quantile bins fitted on train (≤ {status.get("train_end", "")}). '
                "A 60-day window of a slow, regime-switching feature sits at PSI 3–8 even inside the training era, so the status is judged against the train-era distribution of window-PSIs (> p95 drifted, > p75 watch). KS = two-sample statistic.</div>",
                title="Feature drift",
            )
        with c2:
            ui.card(
                ui.html_table(
                    hmm[["pair", "recent_mean_loglik", "train_p5", "train_median", "stale"]],
                    {
                        "recent_mean_loglik": "{:.2f}",
                        "train_p5": "{:.2f}",
                        "train_median": "{:.2f}",
                    },
                )
                + '<div class="fx-muted" style="font-size:0.78rem;margin-top:8px">Mean per-day predictive log-likelihood of the last 60 days under each pair’s saved HMM vs the train-era distribution of the same quantity; below the train 5th percentile = stale. '
                f'Flag today: <b>{"STALE — refit is the human’s call" if status.get("model_stale") else "fresh"}</b>.</div>',
                title="HMM staleness",
            )

# ---- central-bank live tracking (phase 29) ------------------------------------------------------
if cb_live:
    ui.card(
        '<pre class="fx-num" style="font-size:0.8rem;white-space:pre-wrap">'
        + html.escape(json.dumps(cb_live, indent=1))
        + "</pre>",
        title="Central-bank letter index — live tracking (post-deploy documents only)",
    )

# ---- verify yourself ----------------------------------------------------------------------------
ui.card(
    f'<div style="font-size:0.86rem;line-height:1.6">Three lines, standard library only, on a fresh clone:</div>'
    f'<pre class="fx-num" style="font-size:0.8rem;background:{ui.BG};border:1px solid {ui.BORDER};border-radius:8px;padding:10px 12px;margin:8px 0">'
    f"git clone {html.escape(REPO_URL)} &amp;&amp; cd fx-regime-radar\n"
    "python scripts/verify_ledger.py            # prints VALID/BROKEN + head hash\n"
    "cat data/ledger_head.txt                    # compare with the hash committed by the daily Action</pre>"
    f'<div class="fx-muted" style="font-size:0.8rem">Head: <span class="fx-num">{html.escape(head_hash)}</span>'
    + (f" · through {html.escape(head[1])} · {html.escape(head[2])} rows" if len(head) >= 3 else "")
    + ". The daily GitHub Action commits <code>data/ledger_head.txt</code> with every refresh — GitHub’s commit timestamps are the external notarisation of the chain head. "
    "What the chain guarantees: no row was edited, inserted or deleted after it was hashed. What it does not: that the forecasts were good — that is what the scoreboard above is for.</div>",
    title="Verify independently",
)
if len(ledger):
    show = ledger.sort_values("date", ascending=False).head(12).copy()
    cols = [
        c
        for c in [
            "date",
            "pair",
            "regime",
            "change_risk_5d",
            "risk_lo",
            "risk_hi",
            "agreement",
            "anomaly_pct",
            "model_version",
            "git_sha",
            "outcome",
            "row_hash",
        ]
        if c in show.columns
    ]
    show = show[cols].astype(object)
    show["date"] = pd.to_datetime(show["date"]).dt.strftime("%Y-%m-%d")
    show["row_hash"] = show["row_hash"].str[:12] + "…"
    ui.card(
        ui.html_table(
            show.astype(object).where(show.notna(), None),
            {
                "change_risk_5d": "{:.3f}",
                "risk_lo": "{:.2f}",
                "risk_hi": "{:.2f}",
                "anomaly_pct": "{:.0f}",
            },
        ),
        title="Newest ledger rows",
    )
    st.download_button(
        "Download ledger (parquet)",
        data=(DATA / "ledger.parquet").read_bytes(),
        file_name="ledger.parquet",
        mime="application/octet-stream",
    )
    if (DATA / "ledger.jsonl").exists():
        st.download_button(
            "Download ledger (jsonl, for the stdlib verifier)",
            data=(DATA / "ledger.jsonl").read_bytes(),
            file_name="ledger.jsonl",
            mime="application/jsonl",
        )

ui.footer(DISCLAIMER, "· Everything on this page is recomputable from committed files.")
