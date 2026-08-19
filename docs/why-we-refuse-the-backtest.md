# Why we refuse to backtest the language models

*Two-minute version, for anyone. Educational tool. Not investment advice.*

## The problem in one picture

Imagine grading a student on a history exam — but the student has already read the textbook
chapter about how every question turned out. Of course they ace it. The grade tells you
nothing about how they would do on next year's events.

Large language models and financial text models (FinBERT, GPT-class models, Claude) are that
student. They were trained on an enormous pile of text written *after* the central-bank
statements we care about — news stories, blog posts, research notes, forum threads — much of
which says, in plain words, what happened to the euro or the franc in the days after each
statement. That knowledge is not stored in a database you could delete. It is baked into the
model's weights, the millions of numbers that make it work. We call this **parametric
look-ahead**: the look-ahead lives in the parameters.

So if we asked such a model "how hawkish is this 2015 ECB statement?" and then checked
whether its answers lined up with the market moves that followed, we would be testing how well
it *remembers the ending of the story*, not how well it reads central banks. The resulting
accuracy number would look wonderful and mean nothing. A reviewer who has seen this trick once
never trusts a historical LLM backtest again — and neither do we.

## What we do instead

1. **History is scored only by a word list.** Our hawkish/dovish/uncertainty index for
   statements before 2026-08-17 comes from a few hundred frozen dictionary terms
   (`data/lexicon/`, hashes pinned). A word list has no memory: it cannot know what the
   franc did in 2015. Whatever it finds in old statements is a fair test.
2. **Models with memory score the future only.** FinBERT and any LLM may score a statement
   only if it was published *after* our deploy date, 2026-08-17 — the day the live ledger
   started. The code refuses earlier dates and a test proves the refusal. Not even "just to
   look": a number you have seen cannot be unseen.
3. **The hash-chained ledger is the exam hall.** Every weekday the pipeline writes its
   forecasts into an append-only ledger where each row carries the SHA-256 hash of the row
   before it (`data/ledger.parquet`). Rows are written *before* the outcome exists and cannot
   be changed or backfilled afterwards without breaking the chain. When a model-with-memory
   scores a new statement, that score goes into the same ledger, with a receipt: the exact
   prompt (hashed and versioned), the model name and version string, the date, and the raw
   reply. Years later, anyone can re-check which model said what, when — and whether the
   market had already told it the answer (it had not: the reply predates the outcome).
4. **We publish the live record, not a backtest.** The proof page shows how the lexicon,
   FinBERT and (if ever enabled) the LLM did on statements published after deploy, scored with
   the same functions as everything else, next to the frozen pre-deploy test of the rest of the
   system. It starts empty and fills at the speed of the real calendar — about forty
   statements a year across the four banks. That slowness is the point.

## Why this is worth more than an accuracy number

An impressive historical score for a model that has read the future is easy to produce and
impossible to trust. A small, slow, honest live record — every entry timestamped, hashed, and
written before the outcome — is hard to produce and impossible to fake. When someone asks
"does your language-model index work?", the honest answer today is: *we don't know yet; here
is the ledger; come back in a year.* That answer is the deliverable.

*See also: `docs/stage2-decision.md` (the current gate status with the numbers) and
`docs/CB_INDEX.md` (how the index is built). Educational tool. Not investment advice.*
