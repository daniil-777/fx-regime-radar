# Interview notes — FX Regime Radar

Written in my own voice, for rehearsal. Each answer is followed by the hard follow-up an interviewer
is likely to push with, and how I'd handle it. Numbers are the frozen ones in `reports/`.

---

## 1. Why an HMM rather than k-means for regimes?

Both find clusters in feature space, but only the HMM has a **transition matrix**: it assumes the
market is in one of a few sticky hidden states and that today's state is most likely yesterday's.
That does two things k-means cannot: it produces a *probability* per day (so I get confidence and
entropy, not just a label), and it resists flipping the label on every noisy day — the fitted
diagonals are 0.95–0.985, so a change needs accumulating evidence. k-means would relabel on single
outliers and gives no notion of persistence.

**Hard question:** *"Your five-seed agreement is 40–100 %. Isn't that just k-means instability with
extra steps?"* — Yes, EM finds local optima and the trend/chop split is where they differ; the
calm/crisis ends are stable. I report it rather than hide it, I treat trend vs chop as soft, and the
production fix is several restarts keeping the best likelihood plus a check against the previous
labelling before a refit replaces it. The downstream models consume probabilities and entropy, which
are more stable than the argmax label.

## 2. Filtered vs smoothed — and why it matters

Filtered probabilities are P(state today | data up to today); smoothed are P(state today | the whole
series, including the future). Smoothed labels look cleaner on a chart precisely because they use
hindsight, so any feature or output built from them leaks the future. I implement the forward
algorithm myself (per-frame Gaussian log-likelihoods + transition matrix, logsumexp-normalised each
step) and never call `predict_proba` for outputs. Weather analogy: filtered is "is it a storm, given
everything up to now?"; smoothed is "knowing next week's weather too, was today a storm?" — only the
first exists in real time.

**Hard question:** *"How do you know your filtered implementation is right?"* — Two tests: on a toy
model, filtered probs at every t equal hmmlearn's smoothed posterior on the prefix X[:t+1] (the last
step of a prefix has no future, so the two must agree, atol 1e-8); and truncating the series never
changes earlier filtered rows, while it demonstrably changes smoothed ones.

## 3. How is leakage prevented? Name the tests.

Rule: every feature at day t uses rows ≤ t. Enforced by **truncation-invariance tests**: build features
on the full series and on the series minus its last 30 rows; the overlapping rows must be *exactly*
equal (`assert_frame_equal(check_exact=True)`). Present for `features.py`, for HMM scoring
(`score_pair`), for the assembled forecaster matrix, and for siren scoring; plus a one-pair truncation
test (cutting one pair never changes rows dated before its cutoff for any pair) and a causality test on
the naive vol rule and the toy MA strategy. Models are fit on data ≤ 2016-12-31 with scalers fit on the
same window; the app never computes anything.

**Hard question:** *"Truncation invariance can't catch a look-ahead that's already inside the input
data."* — Correct: it proves the transformation is causal, not that the source is. That is why the
data layer excludes the in-progress day (Yahoo's bar for today changes during the day) and documents
that Yahoo's daily close is a start-of-day snapshot; the SNB shock shows in the 01-16 close and I say
so rather than shift data around.

## 4. Why the embargo?

The forecaster's label at day t looks at t+1..t+5. Without a gap, the last training rows would carry
information about the first validation days (their labels overlap the same future window), and
consecutive days are strongly autocorrelated anyway. So five trading days are dropped on *both* sides
of every split boundary, per pair, and a test asserts the gap exists. It costs ~30 rows; it buys an
evaluation I can defend.

**Hard question:** *"Why five, not twenty?"* — Five is the label horizon; that removes the mechanical
overlap. Autocorrelation of features (vol_60 has a 60-day window) means some dependence remains, which
is why I don't tune on validation beyond early stopping and one threshold, and why the test set is
scored once.

## 5. Why not accuracy?

The test positive rate is 16 %. A model that always says "no change" scores 84 % accuracy and is
useless. I report PR-AUC (ranking quality on the positive class), precision and recall at a threshold
chosen on validation, and Brier score with a calibration plot — and always next to three baselines:
base rate, logistic regression on the same features, a one-feature rule. XGBoost: PR-AUC 0.548 vs 0.431
(logistic) and 0.162 (base rate).

**Hard question:** *"0.55 vs 0.43 — is the non-linear model worth it?"* — It is a clear lift (+0.12
PR-AUC), it is better calibrated after Platt scaling (Brier 0.102 vs 0.116), and it gives per-day SHAP
drivers, which is what the narration and the card need. If the lift had been thin I would have shipped
the logistic model — the report is written to say so if it happens.

## 6. What does calibration mean here?

A calibrated 30 % means that of all days I said 30 %, about 30 % actually saw a regime change. For a
desk it is the difference between a score and a probability you can budget with. `scale_pos_weight`
deliberately distorts XGBoost's probabilities upward (recall first), so I recalibrate with a
two-parameter Platt fit on validation and show raw vs calibrated Brier (0.128 → 0.102) and the curve.

**Hard question:** *"Platt on the same validation set you picked the threshold on?"* — Yes, both are
validation decisions; the test set stayed untouched until one final scoring. Two parameters cannot
overfit 1 500 rows meaningfully, and the test calibration curve confirms it.

## 7. Why is the neural net tiny, and why no transformer from scratch?

The siren has ~200 parameters (8-3-8 on 9 inputs) and is trained on 2 788 calm days. That is the
right size for the data: the bottleneck forces it to learn the *shape* of normal and nothing more. A
transformer has millions of parameters and would need orders of magnitude more data to learn anything
a rolling-window feature set does not already give me — on ~16 000 daily rows it would memorise, not
generalise, and it would be indefensible in review. Model complexity should match data size, and daily
FX data is small.

**Hard question:** *"Why an autoencoder instead of a z-score?"* — A z-score is per feature; the
autoencoder learns the *joint* shape, so a day where each feature is individually ordinary but the
combination is unheard-of still scores high (and I keep the per-feature errors so I can say which
combination). Test: on the SNB day the siren ranks 2015-01-16 first for USD/CHF without any event
knowledge.

## 8. How is the LLM prevented from hallucinating?

It only ever sees a JSON of computed numbers and a fixed system prompt that says: use only the JSON,
exactly three sentences, never predict prices, never advise, never add facts. Temperature 0.3, small
Haiku model, 350 tokens. A deterministic template writes the same three sentences when there is no key
or any call fails, and the app never calls the API — it reads `report.json`. A test asserts the request
contains the system prompt and only JSON-derived user content.

**Hard question:** *"The model can still paraphrase wrongly."* — It can misword; it cannot invent an
input, and every number it could mention is on the card next to it, so a wrong paraphrase is visible.
For a product I would add a post-check that every number in the text appears in the JSON and fall back
to the template otherwise.

## 9. What would you build next?

Rank-ordered: (1) multiple restarts + a stability gate for HMM refits, and a probability-weighted
regime feature instead of the argmax; (2) intraday or at least NY-close data to remove the Yahoo
close quirk; (3) a proper walk-forward re-evaluation of the forecaster with expanding windows so the
scoreboard is a distribution, not a point; (4) more pairs and cross-asset context (rates, equity vol);
(5) a Rust serving path with golden-vector self-tests (phases 11–13 in the plan) and a cost-aware
backtest that turns these signals into a risk overlay reported net of costs — always with the same
stance unconditioned beside it (phases 14–16).

**Hard question:** *"Could this be a product?"* — Not as-is: yfinance is not licensed for commercial
redistribution, and anything that looks like signals to retail brushes against advice regulation. Version
1 is educational and says so; a paid tier would need licensed data, a compliance review, and an honest
track record — which is itself the answer to "how do you think about it".
