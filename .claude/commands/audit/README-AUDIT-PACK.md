# The audit pack — five sessions to a verified baseline

Written after a full read of all 46 phase files (00–45) plus the roadmap.
Purpose: recover cleanly from the folder move, then put the built system
(phases 00–18, tag v2.6.0) through the review a hostile expert would give
it — ML correctness first, engineering second, surfaces third — fixing what
can be fixed and putting everything else in front of you for a decision.

## Install
Copy the five `audit-*.md` files into `.claude/commands/` in the repo. They
become slash commands. They are self-contained: each carries a pre-filled
Step 0 harvested from your own phase files, so a memoryless session verifies
facts instead of guessing them.

## Run order — and where phase 20 fits
1. `/audit-00-reanchor` — environment, integrity, green baseline, STATE.md.
   Half a day at most; the venv is expected to be dead, that's normal.
2. `/audit-01-ml-forensics` — the leakage hunt, determinism proof, and claim
   reproduction. One to two days. This is the session that protects the
   ledger's future credibility.
3. **Run phase 20 now** — unless audit-01 raised a blocker (then fix that
   blocker via the audit-04 adjudication process first, compressed). Every
   day the ledger is not running is evidence that cannot be recovered.
   Code style and UI polish do not gate the ledger; a causality bug does.
4. `/audit-02-engineering` — code quality, contracts, test teeth, Rust, CI.
5. `/audit-03-surfaces` — the app against its own specs, honesty on screen,
   the direction lint the golden rules already mandate, the orb budget.
6. `/audit-04-closeout` — adjudicate every flagged finding with you, apply
   approved fixes with public correction notes, seal `v2.6.1`.

## How to start each session in VS Code
Open the repo folder, open the terminal, run `claude` (pick the strongest
available model with `/model`), then run the slash command. Two habits make
these sessions work:
- **Respect the WAIT gates.** Each prompt stops after Step 0 with an
  adaptation table, and audit-04 stops at every adjudication. Confirm or
  correct before it proceeds — the gates are where your judgment enters.
- **Answer the Teach-me quizzes out loud.** They are interview rehearsal;
  the critique is the deliverable.

## Conventions (one deliberate deviation)
Commits are `audit-0N: ...`. There is exactly one tag, `v2.6.1 — audited
baseline`, at close-out — a patch, not a minor, because minor tags mark
feature phases and the next minor belongs to the ledger. Everything else
follows the house format: pre-filled Step 0, numbered testable
requirements, Do-not, Verify ending in CHANGELOG + commit, Teach-me.

## The hard line running through all five prompts
Finding and fixing are separated. Mechanical issues (style, hygiene,
missing tests, display defects) are fixed as found, each with a pinning
test. Anything that would change a published number, a committed artifact,
or model behavior is **flagged and stopped** — those are decided by you in
audit-04, and corrections are published openly (old value, new value, date,
cause), never applied silently. Nothing may retrain, retune, touch 2019+
as an input to a choice, weaken the two sacred tests, or regenerate a
committed artifact to make a test pass.

## What the analysis of your 46 phase files found
Worth two minutes before you start:

1. **`phase-19.md` header drift.** The file is internally titled "Phase 24 —
   signature 3D visuals" with tag "(v0.25.0)" — a leftover from renumbering
   (the ROADMAP confirms your 19 = the 3D phase). A memoryless Claude Code
   run will hit that contradiction. One-line fix before you ever run it:
   retitle the description to "Phase 19 — signature 3D visuals (next minor
   tag)" and delete the paragraph about reserved numbering.
2. **Two design systems exist on purpose — keep them straight.** The built
   app uses the phase-05 look (Inter + JetBrains Mono, card #131A26). The
   token system in your project docs (nimbus/front, Space Grotesk/IBM Plex,
   tokens.json, lint-ui) is the phase-31 target and does not exist in the
   repo yet. audit-03 is scoped accordingly; don't let any session
   "helpfully" migrate early.
3. **One golden rule is ahead of the code.** "A lint test bans direction
   words across the codebase" is a stated rule, but the built phases only
   add template lints later (24/25/27). audit-03 closes that gap now with a
   minimal `make lint-direction`.
4. **CLAUDE.md rule numbering differs from the six-file summary.** The
   phase files cite repo numbers (rule 11 = the wall, 12 = backtests,
   13 = cosmetic layers) that don't match the 11-rule summary in the
   project-knowledge pack. The audits treat the repo's CLAUDE.md as
   authoritative; consider reconciling the summary afterward.
5. **Phases 00–18 predate the Step 0 format** — expected, they're built.
   The pack compensates by pre-filling their facts into each audit's
   Step 0.
6. **Two doc-level facts to verify, not assume:** the model summary says
   "13 features" for the forecaster while phase-07's list resolves to 15
   columns after one-hots — audit-01 checks the code's truth; and the
   published PR-AUC 0.548 / Brier 0.102 must match
   `reports/forecaster_eval.md` — a docs-vs-repo mismatch there would be a
   top finding.

## After close-out
The audited baseline exists, the record is clean, and the priority is
unchanged: if the ledger is somehow still not running, that is the next
command — before any of 21–45, before more polish, before anything.
