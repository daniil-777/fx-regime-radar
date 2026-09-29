---
description: Audit 00 — re-anchor after the folder move: environment, integrity, green baseline, STATE.md (audit series — tag v2.6.1 at close-out)
---

Read CLAUDE.md golden rules first. The project folder was moved on disk and all
prior Claude Code sessions are gone. Nothing of value lived in those sessions —
the repo, the tags, and the phase files are the memory — but the local
environment is now broken in predictable ways and must be rebuilt before any
audit can be trusted. This session produces a fully green baseline and one
honest inventory of what actually exists.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled from the phase files, state as of tag `v2.6.0` (phases 00–18 built;
19–45 written but NOT run — their files/artifacts must NOT exist yet):
- Package `src/fxradar/` with `__init__.py` (`__version__`), `data.py`,
  `features.py`, `hmm_model.py`, `validate.py`, `forecaster.py`, `siren.py`,
  `narrate.py`, `export.py`, `backtest.py`, `strategies.py`, `stress.py`,
  `arcade.py`.
- `app/app.py`, `app/ui.py`, `app/orb.py`, `app/pages/` (Methodology,
  Strategy lab, Arcade — exact filenames may differ).
- `pipelines/run_daily.py` (register-a-step pattern).
- `rust/fxradar-serve/` (bundle.rs, features.rs, hmm.rs, infer.rs, selftest
  binary, axum service), `rust/BENCH.md`, `docker-compose.yml`.
- `.github/workflows/daily.yml` — weekdays 06:00 UTC, commits `data/`.
- `data/`: prices.parquet, features.parquet, regimes_base.parquet,
  regimes.parquet, report.json, backtests.parquet, arcade.db, storms.yaml.
- `models/`: `hmm_{pair}_v0.4.0.joblib` × 3 pairs (EURUSD, USDCHF, GBPUSD),
  `forecaster_v1.1.0.json`, `siren_v1.2.0.joblib`, `bundle_v*/` with
  manifest.json + goldens.parquet + feature_spec.yaml + two ONNX files.
- `reports/`: prices_overview.png, hmm_validation.md, forecaster_eval.md,
  siren_validation.md, strategy_eval.md, stress_report.md, plus pngs.
- `docs/`: model_cards.md, INTERVIEW_NOTES.md, DEMO_SCRIPT.md,
  bundle_format.md, screenshots/.
- Makefile targets: setup, test, lint, fmt, run, pipeline.
- Git: commits in `phase-NN:` convention; tags v0.1.0 … v2.6.0.
- NOT yet present (do not create): ledger.py, verify_ledger.py, bocpd.py,
  design/tokens.json, `make lint-ui`, any `lab/` directory.
Verify every line against the real tree, print an adaptation table
(expected → actual, including anything extra or missing), report drift, WAIT.

## Task
Rebuild the local environment, prove nothing was lost or corrupted in the
move, get every check green (or list every red with its cause), and write
`docs/STATE.md` — the single-page truth of what exists — so the audit
sessions that follow stand on verified ground.

## Requirements
A. Safety first
1. `git status` and `git stash list`. Every dirty or untracked file is listed
   VERBATIM in the session before anything else happens. Untracked files may
   be un-committed work — never delete, never `git clean`, never stash without
   my explicit line-item approval. WAIT here if anything is dirty.
2. `git fsck --full`, `git log --oneline -15`, `git tag --list | sort -V`,
   `git remote -v`, and a fetch to prove the remote is reachable. Expected:
   fsck clean, tags end at v2.6.0, HEAD at or past the v2.6.0 commit.

B. Environment rebuild (the move's known casualty)
3. The old venv is dead by design — its scripts hard-code the old absolute
   path. Delete it and rebuild via `make setup` with Python 3.11+. Then
   `pip check` must report zero broken requirements. Expected outcome: this
   is routine, not a finding.
4. Rust toolchain present (`cargo --version`); `cargo build` in
   `rust/fxradar-serve` succeeds.
5. List every environment variable the repo reads (grep for `os.environ`,
   `getenv`, `st.secrets`, `std::env`). Expected: ANTHROPIC_API_KEY only, plus
   any service URL switch (e.g. FXRADAR_API_URL). Print the list so I can
   restore my local `.env`/secrets; confirm none of these values appear
   anywhere in git history (`git log -S` spot-checks).

C. Stale-path scan (the move's silent casualty)
6. Ask me for the OLD folder path, then `grep -rn` the repo (excluding .git
   and the venv) for: that path, `/Users/`, `/home/`, `file://`, and any other
   absolute filesystem path. Every hit is either fixed to a relative path /
   env variable, or justified in one line (e.g. a doc example). Zero
   unexplained hits.

D. Green baseline
7. `make lint` and `make test` — record test count and wall time. `cargo test`
   and `cargo clippy` — clippy must be clean.
8. Run the bundle selftest against the committed bundle; expect the recorded
   parity tolerances to hold (features ≤ 1e-8, model outputs ≤ 1e-6).
9. `make pipeline` once, end to end, with stage timings. Then
   `git diff --stat data/` — the diff should be limited to genuinely new
   market days; any change to historical rows is a red flag to report, not
   repair.
10. `make run`, confirm the app boots and every page renders with the
    disclaimer in the footer, then stop it. No screenshots yet — audit-03
    owns the app.
11. External state: confirm the GitHub Action's recent runs are green (the
    Action never noticed the move — it runs in the cloud) and the Streamlit
    Community Cloud app is alive and shows a current "data through" date.

E. The inventory
12. Write `docs/STATE.md`: one table row per phase 00–18 — phase, tag, key
    files, key artifacts, present yes/no — plus a "not yet built" line naming
    the ledger explicitly as the next scheduled work, and a "reds" section
    listing every check from this session that did not pass, with cause.

## Do not
No fixes beyond environment mechanics and stale paths. No deleting or
regenerating committed artifacts in `data/` or `models/`. No training, no
refits, no dependency upgrades, no refactors of anything found ugly — note it
in STATE.md for the later audits instead. No touching phases 19–45.

## Verify
- Adaptation table confirmed by me; dirty-file list resolved by me.
- `make lint`, `make test`, `cargo test`, `cargo clippy`, selftest: all green,
  or each red listed in STATE.md with a one-line cause.
- Stale-path scan output shown with zero unexplained hits.
- `docs/STATE.md` exists and I have read it.
- CHANGELOG entry under an "Audit series" heading; commit
  `audit-00: re-anchor after folder move`. No tag yet.

## Teach me
Explain: why a git repo survives a folder move untouched while a virtualenv
dies (where each stores absolute state); and why the daily GitHub Action kept
running perfectly while my laptop was broken — what that says about where the
system of record actually lives. Then quiz me: (1) which single file in this
repo would be hardest to recover if lost, and why is the answer "none of
them" supposed to be true here? (2) if `git status` had shown 40 untracked
files, what would the wrong first move have been? Critique my answers.
