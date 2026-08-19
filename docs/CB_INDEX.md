# Central-bank communication index (phases 29–30)

*Educational tool. Not investment advice.*

A hawkish / dovish / uncertainty index for the ~40 official policy statements a year from the
Fed (FOMC), ECB, SNB and Bank of England — free, timestamped, never revised — scored two ways
with a hard wall between what may touch history and what may not.

| leg | model | may score | lives in | why |
|---|---|---|---|---|
| historical | frozen word lists (`data/lexicon/`, sha256-pinned) | everything (2020→) | `cb_lexicon.py`, `cb_features.py` | no memory → history-safe |
| live | pinned FinBERT `ProsusAI/finbert@4556d13` | statements published ≥ 2026-08-17 only | `cb_finbert.py` (+ `requirements-nlp.txt`) | weights have memory → post-deploy only |
| live, **gated** | `claude-haiku-4-5` with `prompts/cb_hawkishness_v1.txt` | same, and only once the gate opens | `cb_llm.py` | see `docs/stage2-decision.md` |

Why the wall exists: [`docs/why-we-refuse-the-backtest.md`](why-we-refuse-the-backtest.md).

## 1. Documents — `python -m fxradar.cb_text --backfill --since 2020`

Official English texts only, fetched politely (1 s sleep, identifying User-Agent) from the
banks' own sites, stored once under `data/cb/<BANK>_<YYYY-MM-DD>.json`
(`{bank, type, url, published_at, fetched_at, text, sha256}`), catalogued in `data/cb/index.json`.

| bank | document | listing | fixed publication time |
|---|---|---|---|
| FOMC | "Federal Reserve issues FOMC statement" | FOMC calendar + historical year pages | 14:00 New York |
| ECB | "Monetary policy decisions" press release | `press/govcdec/mopo/<year>/…index_include` | 14:15 CET |
| SNB | quarterly "Monetary policy assessment" | the SNB decisions page | 09:30 CET |
| BOE | "Monetary Policy Summary" (not the minutes) | `…/<year>/<month>-<year>` probe | 12:00 London |

HTML → text with the stdlib `html.parser`; SNB assessments before mid-2025 are PDF-only and
need the optional `pypdf` (in `requirements-nlp.txt`). Idempotent: files on disk are never
re-fetched. No news, speeches, minutes or mirrors — ever.

## 2. Lexicon scores — `python -m fxradar.cb_lexicon`

Per document (all normalised by token count): `hawk`, `dove`, `tone = (hawk−dove)/(hawk+dove+ε)`,
`uncertainty` (Loughran-McDonald Uncertainty list, 297 words). Lower-case, hyphens → spaces,
greedy longest phrase first ("rate hike" consumes both tokens). Lists: 121 hawkish / 129 dovish
terms compiled from the published dictionaries cited in `data/lexicon/LICENSE_NOTE.md`. Any
edit breaks the pinned hash and the test; a new list is a new `LEXICON_VERSION`.

## 3. Daily features — `python -m fxradar.cb_features` → `data/cb_features.parquet`

For each bank `B ∈ {fomc, ecb, snb, boe}` and trading date `t`:
`cb_B_tone`, `cb_B_uncert`, `cb_B_tone_surprise` (= tone − mean tone of that bank's previous
4 statements, causal), `cb_B_days_since`. NaN before the first statement, forward-filled after.

**Publication-time rule** (the only place it lives: `cb_features.effective_date`): the FX day
ends 17:00 New York. A statement published before 17:00 NY counts on that date; at/after 17:00
NY it counts from the next calendar day; weekends roll to the next trading date through the
as-of merge. With the fixed times above every scheduled statement is same-day. The transform is
causal by construction and the test proves truncation invariance bit-for-bit.

Use: the orchestrator merges `cb_features.parquet` on `date` into `features_ext` for the
**challenger** forecaster only (volatility / regime targets) — never the production model,
never a direction target.

## 4. Evaluation — `python scripts/cb_event_study.py` → `reports/cb_index.md`

|tone surprise| vs the next five days' |moves| and the ten-day regime-flip rate for EURUSD and
USDCHF, high vs low surprise, with a 1000-sample placebo band. Result and its honest reading
live in `reports/cb_index.md`; figures `reports/cb_event_study_*.png`.
`cb_lexicon.live_tracking_summary()` gives the proof page the per-bank count of statements
since deploy and the last tone.

## 5. Live leg — `pip install -r requirements-nlp.txt && python -m fxradar.cb_finbert`

`score_live(docs)` raises `LiveOnlyError` on any pre-deploy document **before** transformers is
imported (tested without torch). Scores → `data/cb/finbert_scores.jsonl` (the pipeline mirrors
them into the ledger). Pin: `data/cb/finbert_pin.json`. CI never installs torch.

## 6. Stage 2 (gated) — `python -m fxradar.cb_llm`

Prints the gate with the real counts and refuses to score while it is closed; there is no
bypass flag. When open: same live-only guard, cost cap `MAX_DOCS_PER_YEAR = 60`, receipts
(`prompt_sha256`, `prompt_version`, model, date, raw response) → `data/cb/llm_receipts.jsonl`,
graceful skip + `data/ops_log.jsonl` line without a key. Customer surfaces never show LLM text.

*Educational tool. Not investment advice.*
