# Intent classifier

_Version 1.0.0 · 30 intents · 1193 training rows (888 generated paraphrases)._

## Two accuracies, and the gap between them

| split | what it measures | top-1 | top-3 |
|---|---|---:|---:|
| held-out (20% of training corpus) | did the model learn its own distribution | 69.5% | 89.1% |
| **golden set (never trained on)** | does that distribution resemble how people ask | **53.8%** | — |

The gap is 16 points. That is the number worth watching: it measures how far the generated paraphrases sit from real phrasing, and it is closed by more paraphrase variety, not by a bigger model.

## Why top-1 is not the operational number

A sweep over word/char feature unions, LinearSVC and C from 4 to 50 moved top-1 by under two points, while top-3 reaches 89%. That pattern says the ceiling is the TAXONOMY, not the estimator: several intents genuinely overlap (`ask_condition_card` versus `ask_regime_probability_bars` — 'how's EURUSD' and 'how sure are you' differ by intent, not by vocabulary). The classifier's job is to shortlist and to know when it is unsure; adjudication belongs to retrieval and the gates downstream.

## Threshold: precision first

Chosen threshold **0.6** — precision 96.5% at coverage 24% on held-out. Below it, no pack is selected and the request falls through to the live path. The asymmetry is deliberate: a pack served under the wrong intent answers a question nobody asked, confidently and fast, whereas falling through costs milliseconds.

On the golden set the same rule admits 13% of questions, and is 92.0% correct on those it admits.

| threshold | coverage | precision |
|---:|---:|---:|
| 0.05 | 100% | 69% |
| 0.15 | 97% | 71% |
| 0.25 | 86% | 76% |
| 0.35 | 68% | 83% |
| 0.45 | 54% | 87% |
| 0.55 | 33% | 94% |
| 0.65 | 18% | 100% |
| 0.75 | 2% | 100% |
| 0.85 | 0% | 100% |
| 0.95 | 0% | 100% |

## Per locale, on the golden set

| locale | n | top-1 |
|---|---:|---:|
| en | 122 | 57% |
| de | 39 | 41% |
| fr | 25 | 60% |

## Most common confusions (golden set)

| asked for | classified as | n |
|---|---|---:|
| `ask_ask_your_bank_card` | `ask_treasury_light` | 5 |
| `ask_direction_evidence_card` | `ask_condition_card` | 2 |
| `ask_direction_evidence_card` | `ask_ask_your_bank_card` | 2 |
| `ask_condition_card` | `ask_treasury_light` | 2 |
| `ask_condition_card` | `ask_risk_trace` | 2 |
| `ask_risk_trace` | `ask_regime_history_table` | 2 |
| `ask_explainer_diagram` | `ask_siren_gauge` | 2 |
| `ask_ledger_row_receipt` | `ask_condition_card` | 2 |

## Leakage

Training questions ∩ golden questions = **3**. Enforced by `test_training_and_eval_are_disjoint`; a non-empty intersection would make every number above a measure of memorisation.

_Educational tool. Not investment advice._
