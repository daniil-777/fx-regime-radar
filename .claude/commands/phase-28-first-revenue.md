---
description: Phase 28 — Stripe, tiers, and the design-partner program (next minor tag)
---

Read CLAUDE.md golden rules first. Two days of code, then phone calls, not
commits. Four paying SMEs ≈ CHF 300/month — which sounds like nothing and
turns "project" into "company" in every investor conversation.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: keys + tier field live in the axum service (phase 24, sqlite);
paid surfaces = alerts, Treasury page, API, white-label widget; legal pages
go in docs/ + app footer. Verify, report drift, WAIT.

## Task
Stripe checkout in TEST MODE, tier enforcement on existing keys, and the
outreach kit for fifteen Swiss SMEs and fiduciaries.

## Requirements
1. Tiers: Free (weekly report + public widget) · Pro CHF 79/month (alerts on
   chosen pairs, Treasury mode, monthly PDF) · Partner CHF 500+/month (API +
   white-label). Enforcement in the phase-24 middleware; clean
   upgrade/downgrade/cancel.
2. Stripe checkout + customer portal; a webhook route on the axum service
   verifying Stripe's signature and updating the key's tier in sqlite;
   secrets via env only; TEST MODE until the first design partner converts.
3. Before any live charge: terms of use, privacy note, and the rule-7
   disclaimer on every paid surface. TODO for me: confirm Swiss FinSA
   specifics with a professional before going live.
4. Outreach kit in docs/: design-partner email in GERMAN and ENGLISH (≤150
   words — 6 months free for a monthly feedback call + signed LOI at CHF
   79/month if useful), a one-page LOI template, target criteria (Swiss
   SMEs with EUR/USD invoicing, fiduciary firms, treasury associations),
   and a tracking csv.
5. Metrics page wired to show design partners and MRR.

## Do not
No live charges before terms/privacy exist and one partner verbally agreed.
No annual-only lock-ins. No written discounts below the anchor. No direction
promises in sales copy — the ledger and the traffic light ARE the pitch.

## Verify
- Test-mode purchase upgrades a key end to end; cancel downgrades; Stripe
  signature verified; secrets absent from git history.
- I review the outreach kit line by line before anything is sent.
- CHANGELOG, commit `phase-28: first revenue rails`, next minor tag.

## Teach me
Why five design partners beat fifty signups; what an LOI proves that a free
user cannot. Quiz: (1) why anchor CHF 79 against bank-advisory minutes?
(2) after this ships, what is the next "feature"? (Ten conversations.)
Critique my answers.
