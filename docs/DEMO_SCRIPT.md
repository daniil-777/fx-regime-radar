# Demo script — 90 seconds

**0:00 — Open the live link.** "This is FX Regime Radar, a weather station for currency markets.
It updates itself every weekday from a scheduled job; the app only reads small files, so it paints
in about a second. Data through — *point at the header* — and updated — *timestamp*."

**0:10 — Weather cards.** "One card per pair. The pill is today's regime from a hidden Markov
model — calm, trend, chop or crisis — with its confidence bar and how many days it has held.
Below it a 20-day sparkline of the close, then the *change-risk gauge*: an XGBoost model's calibrated
probability that the regime is different within five trading days, and the three features that
drove that number today. The paragraph underneath is a three-sentence narration of exactly these
numbers — from a small language model when a key is set, from a template otherwise; the badge tells you which."

**0:35 — Timeline.** "The chart is the close with the regime painted behind it. *Click max.* The dashed
line is 2017: everything to the right is out of sample — the model was fitted on 2005–2016 and has
scored forward since. 2008, 2011, 2015, 2020, 2022 show up in red as you would hope; the calm
stretches are green. Notice the labels are *filtered* — computed only from data up to each day, never
with hindsight."

**0:55 — Anatomy table.** "This table asks whether the labels mean anything out of sample: calm has the
lowest volatility, crisis the highest, mean returns inside every label are basically zero — regimes
describe conditions, not direction, and I don't pretend otherwise."

**1:05 — Siren.** "The dials are an autoencoder trained only on confident calm days; the number is
today's reconstruction error as a percentile of calm history. *Scroll to the loudest-days table, switch
to USD/CHF.* The loudest day in its history is 15 January 2015 — the Swiss franc floor removal — with
no event knowledge, just numbers. It detects; it does not predict."

**1:20 — Honesty.** "Every model ships with a validation report that says what did not work: seed
sensitivity of the regime labels, the HMM not beating a one-line volatility rule on timing, a toy trend
strategy not being best inside 'trend'. The forecaster's PR-AUC of 0.55 against 0.43 for logistic
regression on the same features is the one number I'd defend — never accuracy."

**1:30 — Close.** "Three ML paradigms — unsupervised regimes, supervised change risk, self-supervised
anomaly detection — correctly matched to three problems, no price prediction anywhere, and every
number on the screen was computed by a job I can show you the tests for. Educational tool, not advice."
