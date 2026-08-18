# FX Regime Radar

A "weather station" for currency markets: an HMM nowcasts the current regime for EUR/USD, USD/CHF and GBP/USD,
an XGBoost model forecasts 5-day regime-change risk (with SHAP explanations), an autoencoder flags anomalous days,
and a small LLM call narrates the computed numbers in plain English. A daily pipeline writes small artifacts; a
Streamlit app only reads them. Built as a hiring-grade portfolio project — see `CHANGELOG.md` for progress by phase.

**Educational tool. Not investment advice.**
