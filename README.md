# FX Regime Radar

A "weather station" for currency markets: an HMM nowcasts the current regime for EUR/USD, USD/CHF and GBP/USD,
an XGBoost model forecasts 5-day regime-change risk (with SHAP explanations), an autoencoder flags anomalous days,
and a small LLM call narrates the computed numbers in plain English. A daily pipeline writes small artifacts; a
Streamlit app only reads them. Built as a hiring-grade portfolio project — see `CHANGELOG.md` for progress by phase.

**Educational tool. Not investment advice.**

## Run locally

```bash
make setup      # venv + pinned dependencies
make pipeline   # data → features → HMM scoring → data/*.parquet (loads saved models)
make run        # Streamlit dashboard, reads artifacts only
make test       # pytest (no network needed)
```

## Deploy

1. **Push to GitHub.** The workflow `.github/workflows/daily.yml` runs weekdays at 06:00 UTC
   (and on demand from the Actions tab), refreshes the artifacts under `data/` and commits them
   with `data: daily refresh [skip ci]`. It needs no secrets. Check the first run is green under
   *Actions*.
2. **Streamlit Community Cloud** (free): go to https://share.streamlit.io → *New app* → pick the
   repo and branch → main file path `app/app.py` → *Deploy*. The app redeploys automatically on
   every commit, so the daily data commit keeps it fresh; the header shows "Data through …" and
   "updated …" straight from the artifacts.
3. **Secrets (phase 09).** Live narration needs `ANTHROPIC_API_KEY`: add it under
   *App settings → Secrets* on Streamlit Cloud and as a repository secret on GitHub. Without it
   everything still runs on the deterministic template — by design.
4. **Model refits are manual and deliberate:** `make refit TRAIN_END=... HMM_VERSION=...` locally,
   or the `refit-models` workflow (inputs: train_end, version). Refits regenerate
   `reports/hmm_validation.md`; read it before merging.

If a daily fetch fails, the pipeline exits nonzero, nothing under `data/` changes, and the app keeps
serving the last good state with its "Data through" date — no silent staleness.

## Narration (phase 09)

Each weather card carries three plain-English sentences generated from the computed numbers only
(regime, confidence, age, 5-day change risk and its drivers, anomaly status). With
`ANTHROPIC_API_KEY` set — locally in the environment or `.streamlit/secrets.toml` (gitignored), on
Streamlit Cloud under *App settings → Secrets*, on GitHub as a repository secret passed to the
daily workflow — the sentences come from `claude-haiku-4-5` (badge **AI**); without a key, or on
any API failure, a deterministic template writes them (badge **auto**). The model never sees
anything but a small JSON of numbers and never predicts prices or gives advice.

**Cost:** three calls per weekday, roughly 450 input + 120 output tokens each, at Haiku pricing
($1 / $5 per million tokens) ≈ $0.002 per day — about **5 cents per month**.
