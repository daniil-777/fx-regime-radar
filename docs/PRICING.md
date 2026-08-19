# Pricing & tiers (phase 28) — TEST MODE

> **TEST MODE until the first design partner converts.** Stripe runs in test mode; no live
> charge happens before `docs/TERMS.md` and `docs/PRIVACY.md` are final and one partner has
> verbally agreed. Educational tool. Not investment advice.

| Tier | Price | What it includes | Who it is for |
|---|---|---|---|
| **Free** | CHF 0 | The weekly FX weather report (`docs/weekly/`, RSS), the public widget, the proof page and the live ledger. | Anyone. Free forever — this is the lead engine, not a trial. |
| **Pro** | **CHF 79 / month** | Alerts on the pairs you choose (regime change, siren), Treasury mode (hedge / wait / ladder with the cost of waiting in your currency), a monthly PDF of the weekly pages. | Swiss SMEs invoicing in EUR / USD / GBP; fiduciary firms with a handful of clients. |
| **Partner** | **CHF 500+ / month** | Everything in Pro plus API access (keys, rate limits per tier) and a white-label widget / report for your own clients. Priced per conversation from CHF 500. | Fiduciary firms, treasury associations, platforms embedding the light. |

## Terms that never change
* **Monthly, cancel any time.** No annual-only lock-in, no minimum term. Downgrade takes effect
  at the end of the paid month; upgrade is immediate.
* **One anchor, no written discounts.** CHF 79 is anchored against a few minutes of bank
  advisory time per month. Design partners get six months free (see `docs/outreach/`), never a
  lower written price.
* **Same numbers for every tier.** Paid tiers add delivery, convenience and coverage — not a
  "better" forecast. The free report and the paid alert read the same artifact.
* **No direction, ever.** No tier predicts price direction or gives investment advice; the
  disclaimer "Educational tool. Not investment advice." stays on every paid surface.

## How tiers are enforced (summary)
Tier is a field on the API key in the axum service's sqlite (`api_keys.tier`); the Stripe
webhook updates it on checkout, portal change and cancellation (see the rust service docs).
The metrics page (`data/metrics.json`) counts active keys and signed design partners honestly —
zeros are real zeros.

**TODO (operator):** confirm Swiss FinSA specifics with a professional before going live.
