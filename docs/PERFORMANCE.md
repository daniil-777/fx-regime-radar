# Performance budgets

The static customer surface has budgets, and CI fails when they are exceeded. This page says what
each budget is, which ones are enforced automatically, and — importantly — which ones are not yet
measured and what it would take to measure them.

_Educational tool. Not investment advice._

## Why a budget rather than a measurement

A measurement tells you the site was fast on the day someone looked. Six months later nobody
remembers the number, every regression arrives as a reasonable-looking change, and the person making
it has no way to know they have crossed a line. A budget in CI is the version that survives contact
with a team: it fails the build on the day the site stops being fast, and it names what grew.

## The budgets

| budget | target | status |
|---|---:|---|
| Overview cold load (HTML + state + JS) | ≤ 200 KB | **enforced** — currently 23.6 KB |
| `public/state.json` | ≤ 50 KB | **enforced** — currently 6.7 KB |
| any single page | ≤ 120 KB | **enforced** |
| cumulative layout shift | 0 | **enforced structurally** (see below) |
| text readable with scripting disabled | yes | **enforced** |
| touch targets | ≥ 44 px | **enforced** |
| ambient animations | ≤ 2 | **enforced** |
| first contentful paint, throttled 4G | < 1.2 s | *not yet measured* |
| time to interactive, throttled 4G | < 2.0 s | *not yet measured* |
| Lighthouse performance / accessibility | ≥ 90 / ≥ 90 | *not yet measured* |

`make budgets` runs the enforced set — 83 checks — and CI runs it on every push.

**The last three rows are honest gaps, not oversights.** They need a real browser on a throttled
network profile, which this repository's CI does not currently have. `scripts/check_budgets.py`
deliberately prints nothing in their place: a plausible-looking 1.1 s that nobody measured is worse
than a blank, because the blank eventually gets filled in and the fabricated number never does.

To close them, add a job running Lighthouse CI against the built `public/` directory on the
`mobileSlow4G` profile and assert the three thresholds. That is a small job; it is listed here
rather than done because it needs a browser in CI that this project has otherwise been careful to
avoid, and that trade-off is the operator's call.

## Why CLS is structural rather than measured

Zero cumulative layout shift is normally something you measure and then chase. Here it falls out of
one design decision: **the state is baked into the HTML at build time**. The regime word, every
number and every table are already in the markup the visitor receives, so nothing arrives late and
nothing can push anything down. There is no skeleton state on these pages because there is nothing
to wait for.

So the budget check does not measure a shift; it checks the two things that could cause one — an
image without reserved dimensions, and a script that inserts content into the flow above existing
content. `app.js` is permitted exactly one in-flow insertion: the "a newer reading is published"
badge, which only appears when a cached page is out of date, and where the shift is the message.

## The comparison with Streamlit

This is the evidence the second surface was worth building.

| | Streamlit console | static surface |
|---|---:|---:|
| Overview payload | see note | **23.6 KB** |
| bytes of JavaScript required before any text renders | the framework bundle | **0** |
| requests to first paint | several | **1** |
| works with scripting disabled | no | **yes** |
| works offline | no | **yes** — last reading, badged |
| server round trip per interaction | yes | **no** |

**Note on the Streamlit figure.** Its installed static bundle is 19.4 MB of JavaScript; a single
page load transfers a chunked subset of that, commonly one to two megabytes. The exact transferred
figure needs the same browser runner as the three unmeasured budgets above, so it is described
rather than stated. The structural rows do not need a browser and are the ones that matter anyway:
Streamlit cannot render a word without executing its bundle, and it cannot render anything at all
without a live server, because every interaction is a round trip.

**That last row is why CSS could never have fixed this.** Streamlit's model is a server-rendered
session: a tap sends a message, the server re-runs the script, the client patches the DOM. On a
train that is not a slow interface, it is a broken one. The static surface has no round trip to be
slow, because there is no interaction that needs the server to read the market state.

## What was not ported, and why that was cheap

Rule 8 says the pipeline writes and the app reads. Because the Streamlit app computes nothing, there
was no logic to port — only rendering. That is the entire reason this phase is a build rather than a
rewrite, and it is worth noticing that a discipline adopted in phase 03 for a completely different
reason (keeping the app fast) is what made a second surface affordable in phase 44.

Streamlit stays deployed as the analyst console — arcade, strategy lab, stress lab, research lab,
ops. It is good at that, it is behind authentication, and it is linked from nowhere public.
