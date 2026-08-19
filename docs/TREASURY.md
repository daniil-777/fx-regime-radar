# Treasury mode — the hedge / wait / ladder traffic light

*Educational tool. Not investment advice.*

Treasury mode answers one recurring question a corporate treasurer with a foreign-currency
receivable or payable actually has: **how large could the adverse move be over the next week(s),
and is now a defensible moment to act?** It answers with risk math and a price tag in the home
currency. It never says which way the rate will move (CLAUDE.md rules 4, 5).

Code: `src/fxradar/treasury.py` (engine + rule table), `app/views/treasury.py` (page),
`data/treasury_risk.json` (artifact written by the pipeline stage `treasury.stage`),
`tests/test_treasury.py`. Standalone: `python -m fxradar.treasury`.

## Method

1. **Windows.** For every day *t* and pair we take the overlapping 5-trading-day log move of the
   close, `|log(close[t+5] / close[t])|`, and label it with the **filtered** HMM regime on day *t* —
   the regime known at the *start* of the window. Nothing in the label looks ahead (a test alters
   the last rows' regimes and checks that earlier windows are unchanged; a truncation-invariance
   test checks a shorter history reproduces the same windows).
2. **Train era only.** Only windows that *end* on or before `config.TRAIN_END` (2016-12-31) enter
   the estimate, so the 2017–2018 validation and 2019+ test eras never shape the table (rule 2).
3. **Historical simulation.** Per pair × regime: VaR at 95 % / 99 % is the empirical quantile of
   the absolute move; ES (expected shortfall) is the mean of the moves at or beyond that VaR.
   An `unconditional` cell (all regimes pooled) is stored for reference only — it is never the
   headline.
4. **Small cells.** A regime with fewer than 30 train windows is replaced by the unconditional
   numbers and flagged `fallback: true` (USDCHF crisis has ~20 train windows; the page says so).
5. **Conversion.** The page multiplies the chosen quantile by the exposure amount and converts to
   the home currency at the latest closes (`fx` block in the artifact: EURUSD, USDCHF, GBPUSD and
   the derived crosses EURCHF, GBPCHF, EURGBP). Money amounts are rounded to two significant
   figures; percentages to 0.1 %.

### Why the loss quantile of the *absolute* move

A treasurer is hurt by an adverse move in **either** direction — a receivable by one sign, a
payable by the other — and this project takes no view on the sign. Quoting the quantile of the
absolute 5-day move gives one number that is the right order of magnitude for both and keeps the
page free of direction language. It is slightly conservative compared with a one-sided loss
quantile of the same level (the absolute distribution's 95th percentile ≈ the two-sided 97.5th
percentile), which is the right side to err on for a budgeting number.

### Square-root-of-time scaling (horizons beyond one week)

The artifact holds **1-week** quantiles. For an *n*-week horizon the page multiplies by √n. This
is an approximation: it assumes independent weekly moves of constant scale and ignores regime
changes within the horizon. Over a 12-week horizon the current regime will almost surely not
persist, so the scaled number is indicative, not a conditional forecast. The page says so.

### Limits of historical simulation

* It can only show what happened in the train era (2005–2016). A move larger than anything in
  that sample has a historical probability of zero — the 2015-01-15 SNB de-peg is *in* the sample
  (which is why USDCHF's **calm** ES 99 % is large: that shock arrived from a calm regime and is
  labelled by the regime at the window start — exactly the point for a treasurer).
* Overlapping windows are strongly autocorrelated; the effective sample is ~1/5 of `n`.
  `n` is shown so the reader can judge.
* Regime labels are model output (filtered HMM, a 2016 fit); the conditioning is only as good as
  the regime model. The unconditional row is shown beneath for exactly this reason.
* Quantile estimates at 99 % from a few hundred windows are noisy; we round, and we never show
  more than one decimal of a percent.

## The traffic light (deterministic rule table, `treasury.decide`)

| light | rule |
|---|---|
| **hedge** | regime is crisis, OR change risk ≥ HIGH_RISK **and** the interval on change risk is ≥ WIDE |
| **wait** | regime is calm **and** change risk < LOW_RISK **and** (interval < NARROW or no interval) **and** no scheduled event within 5 trading days |
| **ladder** | everything else; the reason names the first condition that failed |

Thresholds (`fit_thresholds`, stored under `thresholds` in the artifact): HIGH_RISK / LOW_RISK =
80th / 40th percentile of train-era `change_risk_5d`; WIDE / NARROW = 80th / 40th percentile of the
train-era conformal band width (2 × `conformal_q`) when that column exists, else fixed defaults
0.25 / 0.12. Model agreement / consensus text (phase 21) are appended to the reason as context and
never change the light. Missing inputs (no interval, no calendar) are handled as "unknown", which
can only prevent a *hedge* on the interval branch, not create one.

What the words mean on the page: **hedge** — lock in a larger share of the exposure now with a
forward; **wait** — hold, re-check daily; **ladder** — split the exposure into tranches over the
horizon. These describe *how much / when*, never *which way*.

## Compliance posture

* The rule-7 disclaimer is on the page (sidebar + footer), in the artifact (`disclaimer`) and in
  this document. Any API text built from the artifact must carry it too.
* Every user-facing sentence is a template in `treasury.TEMPLATES`; a lint test fails if any
  template contains a direction word (rise, fall, up, down, buy, sell, long, short, target,
  bullish, bearish, rally, drop, appreciate, depreciate, strengthen, weaken — word-boundary match).
  The generated reasons in the artifact are linted the same way.
* No personalised-suitability claim: the light is a rule on published numbers, stated as such.
  No leverage suggestion. No unconditional number as the headline.
* The page performs no modelling: it multiplies artifact numbers by the user's inputs.

**TODO (owner): confirm Swiss FinSA (FIDLEG) specifics with a professional before charging for
this page or any API built on it — in particular whether generic, non-personalised risk
information of this kind stays outside the definition of a financial service, what the
disclosure duties are if it does not, and whether the wording above is sufficient.**
