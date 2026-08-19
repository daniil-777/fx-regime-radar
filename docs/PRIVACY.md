# Privacy note — DRAFT

**DRAFT — plain-language draft for review. Not legal advice. TODO: confirm Swiss FinSA and
data-protection (FADP / nDSG) specifics with a professional before going live.**

Educational tool. Not investment advice.

## In brief
We store as little as possible, and today that is nothing about readers.

| Surface | What we store | Where | Why |
|---|---|---|---|
| Weekly report (`docs/weekly/`, RSS) | **Nothing.** No subscriber list exists; the RSS feed is pulled by your reader. | — | — |
| Public app / widget | **Nothing** beyond the hosting provider's standard access logs (IP, time, page), which we do not read or export. | Streamlit Community Cloud / our host | Operating the site |
| Public metrics page | Aggregate counts only (days live, number of keys, number of partners, MRR). | `data/metrics.json` in the public repo | Transparency |
| Pro / Partner subscription | Company name, a contact role, the subscription tier and status, a hashed API key. Payment details live with Stripe, never with us. | sqlite on the service host; Stripe | Providing the paid tier |
| Design-partner tracking | Company name, contact *role* and status — never a person's name, e-mail or phone number. | `docs/outreach/tracking.csv` (public repo) | Running the programme |

## E-mail delivery (when it exists)
The weekly report is not e-mailed today. When an e-mail hook is enabled (see
`docs/EMAIL_HOOK.md`) it will be **opt-in only**, with one-click unsubscribe, the list held by
the e-mail provider, and `report_subscribers` on the metrics page showing the honest count.

## Your rights
You may ask what we hold about your company and have it deleted: {contact e-mail}. API keys are
revoked and purged on cancellation. We do not pass data to anyone.

## What we never do
No tracking pixels in the report, no third-party analytics in the app, no personal market
positions collected (the traffic light is generic by design), no data brokers.

*Last updated: {date}. Draft status: not yet reviewed by a professional.*
