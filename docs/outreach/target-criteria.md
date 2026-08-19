# Design-partner criteria (phase 28)

Fifteen conversations, not fifteen thousand e-mails. A design partner is someone who makes the
same recurring decision the product answers — *how much currency risk to carry this week* —
and will tell us, monthly, whether the page helped. Keep this file free of personal data; names
and addresses stay in your mail client, never in the repo (see `docs/PRIVACY.md`).

## Who qualifies

| Segment | Why they care | Qualifier |
|---|---|---|
| **Swiss SMEs invoicing in EUR or USD** | Their margin moves with EUR/CHF-via-USD and USD/CHF; most hedge by habit or not at all. | Turnover CHF 5–200 m, ≥ 20 % of revenue or cost in a foreign currency, a named person owns the hedging decision. |
| **Fiduciary / Treuhand firms** | One partner serves ten to fifty SMEs and wants a defensible, generic answer to "should we hedge now?". | Offers treasury or controlling mandates; willing to forward a weekly page to clients. |
| **Treasury associations & CFO networks** | Distribution: one webinar or newsletter slot reaches hundreds of qualified readers. | Swiss or DACH membership; accepts educational content with the disclaimer. |
| **Lecturers (treasury / risk courses)** | Students practise calibration on the arcade; the weekly report is a free teaching artifact. | Any course that touches FX risk or forecasting. |

## Who does not qualify (for now)

* Anyone asking for a price forecast, a trade signal, or a "when to convert" call — we do not
  offer direction and will not start to.
* Asset managers, prop traders and retail traders: different buyer, different regulation.
* Companies with a bank-managed hedging programme and no internal owner of the decision.

## What we offer (the only terms in writing)

* Six months of the Pro tier free, in exchange for one 30-minute feedback call per month.
* A signed letter of intent (`LOI-template.md`) at CHF 79 / month *if, after the six months,
  the partner finds it useful*. No discount below the anchor in writing; no annual lock-in.
* The pitch is the ledger and the traffic light: every forecast hash-chained before its outcome
  exists, and a generic hedge / wait / ladder answer with the cost of waiting in francs.

## How to use `tracking.csv`

Columns: `company, type, contact_role, status, monthly_chf, notes`.
Status moves `todo → contacted → call → loi → signed` (or `declined`). Only rows with
`status = signed` feed `design_partners` and `mrr_chf` on the public metrics page
(`python -m fxradar.metrics_page`). Replace the PLACEHOLDER rows with real companies (company
name is fine; never a person's name or e-mail).

Educational tool. Not investment advice.
