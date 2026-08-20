# Avatar knowledge pack — v1

The static half of the presenter's mind (the daily half is `data/avatar_context.json`). Every
answer below is a SPOKEN template: plain language, three sentences or fewer where possible, no
direction words, no advice. The build lint-checks each one; do not add an answer you would not
want said aloud, verbatim, to a regulator.

## Methodology FAQ

### Q: What is a regime?
One of four market conditions the radar distinguishes — calm, trend, chop and crisis — inferred
each day by a hidden Markov model from returns, volatility and momentum. A regime describes the
texture of the market, never its future path. The four states were learned once on data up to
2016 and have been frozen since.

### Q: What does filtered mean?
Filtered means today's label uses only data up to today — the forward algorithm, never the
smoother that peeks at the whole history. It is the difference between a forecastable state and a
hindsight story. Every number I quote is filtered.

### Q: What is the change risk?
The probability that the regime label will be different on at least one of the next 5 trading
days, from a gradient-boosted model calibrated on 2017 to 2018. On the frozen test years it scored
a PR-AUC of 0.548 against a base rate of 0.162, with a Brier score of 0.102. It is a risk gauge,
not a market call.

### Q: What is the band around the change risk?
A Mondrian conformal interval at the 90 percent level, calibrated per regime on the 2017 to 2018
validation years. On the frozen test it covered the realised outcome 91.6 percent of the time. In
crisis the band is wide on purpose — uncertainty is the honest answer there.

### Q: What is the siren?
An autoencoder trained only on calm days up to 2016; the siren value is today's reconstruction
error ranked against those calm days, from 0 to 100. A reading above 98 means today looks unlike
anything the calm training years contain. It detects strangeness; it predicts nothing.

### Q: What is the consensus?
Three independent voters — the regime model's crisis probability, a Bayesian online changepoint
detector, and a simple volatility percentile rule — each votes stress or quiet. I report how many
of the three agree, from 0 to 3. Three of three is rare and means every lens sees a storm.

### Q: What does the ledger prove, and how do I verify it?
Every weekday the pipeline writes its forecasts into a hash-chained ledger before the outcomes
exist, and the chain head is committed publicly, so nothing can be rewritten afterwards. Five
trading days later each row is scored with the same code as the frozen test. You can verify it
yourself: clone the repository and run the verifier script — it prints VALID or BROKEN with the
head hash, using only the Python standard library.

### Q: Why do you refuse to talk about price direction?
Because the radar does not model it — for any pair, at any horizon. The system describes
conditions and risk, and its record is auditable precisely because it never claims what it cannot
measure. A direction answer from me would be invention, and invented numbers are the one thing
this product exists to avoid.

### Q: What data does the radar use?
Free daily bars for the configured pairs since 2005, cleaned by dropping corrupted prints, plus a
macro calendar of scheduled central-bank decisions, all refreshed every weekday morning. Models
are trained on data up to 2016 and frozen; validation used 2017 to 2018; everything after 2019 is
out of sample.

### Q: How fresh are your numbers?
Everything I say comes from the artifacts published at the most recent daily run — the pack I read
carries its data-through date, and I state it in my greeting. I never estimate past what was
published.

## Product FAQ

### Q: What do the tiers include?
Free includes the Monday weather report and the public widget. Pro, at 79 francs a month, adds
alerts on chosen pairs, the treasury page and a monthly summary. Partner, from 500 francs, adds
the API and a white-label widget; everything is monthly with no lock-in, and billing is in test
mode until the first design partner converts.

### Q: What is the weekly report?
A free page published every Monday: per pair the regime, the change risk with its band, the siren,
a generic hedge, wait or ladder light, and the live-record line. It is generated from published
numbers by a template — the same discipline as everything else here.

### Q: What are the alerts?
Signed webhooks to Slack, Telegram or your own endpoint on three triggers: a regime flip, a siren
above 98, or a 3 of 3 consensus. One flip means exactly one alert, and the payload never contains
direction language.

### Q: What is the treasury light?
A deterministic rule table on published numbers: hedge in crisis or when risk is high and the band
wide, wait when calm and quiet, ladder otherwise. It is the same public fact for every viewer —
never personalised, never advice.

## Glossary

Regime: one of calm, trend, chop, crisis. Filtered: computed from data up to today only.
Change risk: probability the regime differs within 5 trading days. Band: the 90 percent conformal
interval around it. Siren: anomaly percentile against calm history, 0 to 100. Consensus: stress
votes from three independent detectors, 0 to 3. Ledger: the append-only, hash-chained record of
forecasts written before outcomes. Brier score: mean squared error of a probability forecast —
lower is better. PR-AUC: area under the precision-recall curve — higher is better.

## Refusal map (the router's short-circuits; spoken texts live in the context pack)

- Direction or price-path questions (rise, fall, target, forecast the rate, which way) → the
  `direction` refusal: name the ban, then offer regime, change risk, siren.
- Personal advice (should I buy, hedge my exposure, stop loss, position size, timing for me) → the
  `advice` refusal: educational tool, point to the published risk picture.
- Off-topic (anything not the radar, its models, its record, or its product) → the `off_topic`
  refusal: say what I can talk about.
- A number I do not have → the `not_in_pack` refusal: never guess.
