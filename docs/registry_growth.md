# How the registry grows — and why twelve cards ship as specifications

The registry holds fifty cards. Forty are built; ten are `status: planned` — real specifications
with intents, bindings and captions, that the resolver refuses and the retrieval index excludes.
They exist so the shape of the answer space is decided once, and so the cost of a new card is a
status flip rather than a design argument.

> Catalog note: `docs/REGISTRY-50.md` summarises its own totals as 20/18/12, but the per-card table
> assigns 20 tier-1, 20 tier-2 and 10 tier-3. The table is the data, so the code follows it, and
> `test_registry_holds_fifty_cards` pins 20/20/10. Fixing the summary line is a catalog edit.

## Why not build all fifty

Every built card costs forever: golden questions, a resolution contract, a caption in three
locales, a place in the disambiguation rules, and a share of the reviewer's attention. A card that
nobody asks for costs all of that and returns nothing. Building the last twelve on speculation is
the one reliable way to make this expensive without making it better.

## The promotion rule

A `planned` card becomes `built` only when the gap log shows real demand:

- the same unmet intent appears in **N distinct sessions** (default `N = 5`), and
- those sessions span **at least two weeks** (so one curious afternoon does not promote a card).

Promotion is a deliberate commit, in this order — the order is the point:

1. **Add the golden questions first.** At least three unseen paraphrases per card.
   `test_golden_set_covers_every_built_card` fails if you flip the status first, which is the
   guard-rail: you cannot promote a card you have not specified how to test.
2. **Add or confirm the bindings** against a real artifact, and extend `_sample_bundle()` in
   `tests/test_visual_registry.py`. `test_every_built_card_resolves_against_a_sample_bundle` then
   proves the card resolves before a customer meets it.
3. **Write the disambiguation rule** naming its new rivals, both directions.
4. **Flip `status: planned` → `built`** and bump `registry_version` (the cache key contains it, so
   every stale board is invalidated by the bump alone).
5. **Re-run the retrieval gate.** Recall@6 must hold at ≥ 98%. A new card competes for the six
   slots — a promotion that pushes another card out of the slice is a regression, and this is the
   test that sees it.

## What the gap log records

`reports/visual_gap_log.md` gets one row per question where the model wanted a visual that does not
exist, or picked the catch-all `metric_table` when the question deserved better. Rows carry the
session id, the date, the question, the model's stated wish, and the closest planned card. It is
written by the serving path (phase 36) and reviewed weekly alongside the transcripts.

The log is also the honest record of what the assistant cannot yet do — worth reading before
believing any demo.
