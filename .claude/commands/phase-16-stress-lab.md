---
description: Phase 16 — stress lab: shocks, bootstrap, breakeven (v2.4.0)
---

Read CLAUDE.md golden rule 12. Prerequisite: phase 15. A strategy that has
only met friendly history is untested. This phase attacks your own work.

## Task
Build `src/fxradar/stress.py` and produce `reports/stress_report.md` — the
document a risk manager would demand before letting any strategy near money.

## Requirements
1. Historical replays: isolate the SNB week (Jan 2015), the COVID crash
   (Feb–Mar 2020), and 2022; table of each strategy's and the blend's return,
   max drawdown, and worst single day inside each window. Verify the siren
   stop actually fired where it should have — report dates.
2. Cost shocks: rerun the full test period at 2x, 3x and 5x the cost model;
   for each strategy compute the BREAKEVEN COST — the multiplier at which
   net Sharpe crosses zero. This one number is what practitioners ask first;
   present it prominently.
3. Execution shock: one extra day of lag on all fills; report Sharpe decay.
   A strategy that dies from one day of slippage was never real.
4. Volatility shock: scale crisis-regime returns by 1.5x; report drawdowns.
5. Block bootstrap: resample net returns in 20-day blocks (preserving
   autocorrelation), 1,000 paths of one year; report the distribution of max
   drawdown — median, 5th percentile pain case — as a small histogram png.
6. Parameter robustness: vary each strategy parameter ±30%; heatmap of net
   Sharpe. A flat plateau means robust; a sharp spike at the chosen values
   means overfit — write the verdict either way.
7. Report structure: one page per test, a verdict sentence each, and a final
   summary table. Dashboard: a compact stress panel on the Strategy lab page
   (replay table + drawdown histogram). Update the README results section.

## Do not
No re-tuning parameters after seeing stress results — that is how overfitting
launders itself. No hiding ugly results; ugly results with commentary are
the portfolio's strongest pages. No claims of live-trading readiness.

## Verify
- Run the full lab; read me the report verdict by verdict; show the
  breakeven-cost table, the drawdown histogram, and the robustness heatmap.
- `make test` green. CHANGELOG, commit `phase-16: stress lab`, tag `v2.4.0`.

## Teach me
Explain: why block bootstrap instead of shuffling days, and why breakeven
cost is a better summary than Sharpe alone. Then run the final exam: quiz me
across phases 14–16 with four rapid questions a quant interviewer would ask,
and grade my answers.
