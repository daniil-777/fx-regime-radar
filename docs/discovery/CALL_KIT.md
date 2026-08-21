# Ten calls before the next line of code

The gate: after phase 27, coding stops until ten treasurers or fiduciaries have been interviewed.
This file exists so those calls take an afternoon, not a fortnight.

The point is **not** to pitch. Every question below asks about what the person already did, paid for,
or suffered — never what they think of the idea. Opinions are free and worthless; behaviour is
evidence. If you catch yourself explaining the radar for more than sixty seconds, you have stopped
interviewing and started selling.

## Who to call (aim for a spread, not ten of the same person)

| Segment | Why they matter | Where to find ten |
|---|---|---|
| Corporate treasurer, SME exporter (CHF/EUR revenue split) | Feels FX pain monthly, owns the hedge decision | Swiss SME associations, XING/LinkedIn "Treasurer" + Kanton, chambers of commerce |
| Group treasury analyst, mid-cap | Runs the spreadsheet the radar would replace | LinkedIn, treasury associations (SwissTreasurer, ACT) |
| Fiduciary / Treuhänder | Advises many SMEs at once — one call covers ten companies | Swiss fiduciary directories (TREUHAND|SUISSE) |
| Independent asset manager / family office | Buys research; understands "risk budget, not direction" | FinSA-registered adviser lists |
| CFO of a 20–200 person exporter | Signs the invoice | Warm intros first |

Two of each is a good mix. Warm intros convert several times better than cold calls — ask each
person at the end for one name (question 10).

## The call (12 minutes, and say so at the start)

**Opening (20 seconds, no pitch):**
> "I'm researching how mid-sized Swiss companies actually handle currency risk — I'm not selling
> anything and there's nothing to buy. Twelve minutes, and I'd mostly like to hear how you do it
> today. Would that be alright?"

**Closing (always):**
> "That's really helpful. Two last things: is there anyone else you'd trust on this that I should
> speak with? And would it be alright if I came back to you when I have something to show?"

## The ten questions

Ask in this order. Follow the tangents — the best material is always in the digression.

1. **Walk me through the last time currency movement actually cost you money.** (What happened, how
   much, who noticed first?)
2. **What did you do the next morning?** (Behaviour, not policy. Did anything change?)
3. **How do you decide how much to hedge, today?** (Listen for: a fixed policy, a bank's advice, a
   gut call, or nothing at all.)
4. **Who else has to agree before a hedge goes on?** (Board? CFO? A written policy? This is the
   real sales cycle.)
5. **What do you currently pay for anything FX-related?** (Bank spreads, a platform, an adviser, an
   FX broker's "free" research. Numbers, not ranges.)
6. **When did you last change something about how you do this — and what triggered it?** (No trigger
   in three years = a market that will not move for a new tool either.)
7. **Show me the spreadsheet or report you actually look at.** (Ask them to screen-share. The single
   most informative minute of the call.)
8. **What would have to be true for you to stop using that?** (Their switching cost, in their words.)
9. **If a tool told you "conditions are unusual, consider covering more" — who would you have to
   convince, and what evidence would they demand?** (Tests whether *the radar's actual output* is
   decision-grade for them. Do NOT describe our product first.)
10. **Who else should I talk to?**

## What would make you kill or change the product

Write the answer down before the calls, so you cannot rationalise afterwards:

- **Kill / rethink** if fewer than 3 of 10 can name a specific FX loss in the last two years, or if
  8+ say the bank decides and they never question it.
- **Reposition to fiduciaries** if the treasurers are indifferent but the Treuhänder see it as a
  client-facing tool (one buyer, many end users — a much better wedge).
- **Kill the Pro tier at 79 CHF** if nobody currently pays for anything FX-related; a tool that
  replaces a free spreadsheet has to be free or bundled.
- **Reframe the whole product as compliance evidence** if the recurring pain is "justifying the
  hedge decision afterwards" rather than making it. (Our hash-chained ledger is unusually strong
  here — that would be the finding, and it changes phases 36–38 substantially.)

## Logging

One row per call in `docs/discovery/call_log.csv` — fill it in within ten minutes of hanging up,
while the wording is fresh. Quote them verbatim; paraphrase loses the signal.

When ten rows exist, write three paragraphs at the bottom of that file: what surprised you, what
you were wrong about, and what it changes in the build order. **That summary is the artifact that
reopens coding** — and it belongs in the portfolio: "I interviewed ten treasurers before building
the answer engine" is a stronger interview story than any model in this repo.
