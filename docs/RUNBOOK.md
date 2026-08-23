# Runbook

What to do when something is wrong, written for the version of you that is tired and being asked
for an ETA. Every procedure here states its expected recovery time, because "we're working on it"
and "twelve minutes" are different answers and only one of them is useful to the person asking.

_Educational tool. Not investment advice._

---

## The shape of the system

Three pieces, deliberately independent:

| piece | where | fails how |
|---|---|---|
| static customer surface | CDN, built from the repo | stays up when everything else is down |
| API (avatar, scenarios, alerts) | Oracle VM, behind Caddy | pages still render; interactive features stop |
| daily pipeline | GitHub Actions, 06:00 UTC weekdays | yesterday's numbers, stale badge shown |

The split is the point. **The proof page is served from the CDN, not the VM**, so the evidence that
this system records its forecasts honestly stays reachable when the machine serving the forecasts is
not. For a product whose central claim is verifiability, hosting the verification on the thing being
verified would be the wrong architecture even if it were more convenient.

---

## The daily build failed

**Symptom.** No new commit to `data/` after 07:00 UTC, or the Action shows red.

**What the user sees.** Yesterday's reading, with the stale badge on every page and the drift card
appended. This is by design and is not an incident on its own — a treasurer reading a one-day-old
regime label under a badge that says so has most of the truth. It becomes an incident on day two.

**Do.**
1. Open the Action log; the failing stage names itself.
2. If a data source failed, re-run the job — the pipeline is idempotent and re-fetches.
3. If a model stage failed, check `data/pipeline_status.json` from the last good run for the last
   stage that completed.
4. Do **not** hand-edit artifacts to make the site look current. The stale badge is the honest state,
   and a hand-edited artifact breaks the ledger's chain and cannot be un-broken.

**Expected recovery:** one Action run, about 6 minutes.

---

## The API is down

**Symptom.** Uptime check on `GET /api/health` fails, or the avatar does not connect.

**What the user sees.** Every page still renders completely — the numbers are baked into the HTML.
The avatar, scenario pricing and alert preferences stop. Nothing shows an error, because nothing on
a page depends on the API to paint.

**Do.**
1. `systemctl status fxradar-serve` on the VM; `journalctl -u fxradar-serve -n 200`.
2. On a self-test failure at startup the service **refuses to serve** rather than serving wrong
   numbers. The log names the golden vector that mismatched. This is working as designed; fix the
   bundle, do not bypass the self-test.
3. `systemctl restart fxradar-serve`.
4. If the VM is unreachable, the static site is unaffected — say so in any status note, because "the
   site is down" and "the assistant is down" are very different messages to send.

**Expected recovery:** restart, under 2 minutes. VM rebuild, under 30.

---

## Roll back the static site

**When.** A build shipped a broken page, wrong copy, or a regression the budgets did not catch.

**Do.**
1. `git revert <commit>` on the artifact commit, push. The CDN rebuilds from the repository.
2. If the CDN is slow to pick it up, purge the cache for the affected paths.

**Expected recovery:** 3–5 minutes, dominated by CDN propagation.

---

## Roll back the cutover (DNS)

**When.** The static surface is live on the apex domain and something is wrong with it that a page
revert does not fix.

**Do.**
1. Point the apex record back at the VM (Streamlit or the previous host).
2. Lower the TTL **before** any planned cutover — a 300-second TTL is the difference between a
   five-minute rollback and an hour of waiting. Doing this after you need it does not help.
3. Both surfaces stay deployed in parallel until this procedure has been rehearsed, not merely
   written down.

**Expected recovery:** one TTL, so 5 minutes at a 300-second TTL.

**Rehearsal status:** ☐ not yet rehearsed. This box is unticked on purpose. A rollback procedure
that has never been executed is a hypothesis, and the phase's own verify block asks for it to be
timed — that requires the live DNS and hosting accounts, so it belongs to the operator rather than
to the build.

---

## Restore the ledger

The ledger is the one artifact that cannot be regenerated. Everything else — features, regimes,
packs, indices, pages — is a pure function of prices and code, and can be rebuilt by re-running the
pipeline. The ledger is a record of what was claimed before the outcome was known, and a lost row is
lost evidence.

**Backup.** `data/ledger.parquet` is committed to git on every pipeline run, so every commit is a
backup and the history is the archive. That is the primary. A second copy off GitHub is worth having
before this carries anything anyone relies on.

**Restore.**
1. `git log --oneline -- data/ledger.parquet` to find the last good revision.
2. `git checkout <sha> -- data/ledger.parquet`.
3. `python scripts/verify_ledger.py` — recompute the chain and confirm the head.
4. If the head does not match, **stop**. A chain that does not verify is the situation the chain
   exists to detect; do not overwrite it to make it verify.

**Expected recovery:** under 5 minutes. **Timed on real data:** ☐ not yet — see the note under DNS
rollback; this one is executable locally and should be timed before launch.

---

## The assistant is answering something wrong

1. Open `/ops/traces` with the operator key. Find the turn.
2. The trace names the route, the deciding stage, every gate verdict and the provenance of every
   value. Most wrong answers are a routing decision, not a generation problem, and the deciding
   stage tells you which.
3. Hit **Replay** to confirm it reproduces, so you have a repro before you have a theory.
4. Hit **Promote to golden**. Review the expected route and cards — they record what *did* happen,
   and the point is to make them what *should* happen — then append to `eval/golden.yaml`.
5. Fix, then `make eval-ci`. The promoted item now guards the fix.

That loop, not any panel, is why the trace view exists.

---

## What is deliberately not automated

**Nothing edits an artifact to make a surface look healthier.** Not the stale badge, not the ledger,
not a coverage number. Every failure mode above resolves by fixing the cause or by showing the user
an honest degraded state. A system that repairs its own appearance is a system whose reports cannot
be trusted, and this product has no value at all if its reports cannot be trusted.
