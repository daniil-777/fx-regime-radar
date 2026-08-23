#!/usr/bin/env python3
"""Build the static customer surface into `public/` (phase 44).

Streamlit is an analyst console and it is good at that. It is structurally wrong for a treasurer on
a phone: every interaction is a server round trip, and no amount of CSS fixes a round trip. This
builds a second reader of the same artifacts — no rewrite, because rule 8 means the app computes
nothing and there is no logic to port, only rendering.

## The one decision that shapes everything here

**The state is baked into the HTML at build time.** The pipeline rebuilds these pages every morning
right after it writes the artifacts, so the regime word, the numbers and the tables are already in
the markup a visitor receives. JavaScript only enhances — switching markets, the avatar link. Three
consequences, all of them the phase's requirements falling out of one choice rather than being
chased separately:

- **All text renders before any script executes** (requirement 8), because there is no script in the
  path. A treasurer in a train tunnel sees the condition banner.
- **Zero cumulative layout shift** (requirement 15), because nothing arrives late to push anything
  down. There is no skeleton state on these pages for the simple reason that there is nothing to
  wait for.
- **One fetch** — and on a warm cache, none. `state.json` ships alongside for the service worker and
  for anyone reading the data directly, not because a page needs it to paint.

The cost is that a page is as fresh as the last build. That is exactly right for a product whose
data moves once a day, and the stale badge handles the morning the build fails.

Every colour comes from `design/tokens.json` via `fxradar.tokens`, so `make lint-ui` stays green and
one token change repaints both surfaces at once.
"""

from __future__ import annotations

import html
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fxradar import tokens as tk  # noqa: E402

PUBLIC = ROOT / "public"
STATE = PUBLIC / "state.json"

DISCLAIMER = "Educational tool. Not investment advice."
NAV = [
    ("index.html", "Overview"),
    ("pairs.html", "Pairs"),
    ("treasury.html", "Treasury"),
    ("storms.html", "Storms"),
    ("proof.html", "Proof"),
]

# What each regime word means, in a treasurer's terms rather than a modeller's. Shown under the
# banner word, because a colour and a label are only meaningful to someone who already knows them.
REGIME_GLOSS = {
    "calm": "quiet conditions, moves within the usual range",
    "trend": "persistent directional movement, low day-to-day noise",
    "chop": "large moves without follow-through",
    "crisis": "disorderly, moves well outside the usual range",
}


# ---------------------------------------------------------------------------------------------
# stylesheet, generated from the tokens
# ---------------------------------------------------------------------------------------------


def stylesheet() -> str:
    t = tk.TOKENS
    s, txt, reg, acc = t["surface"], t["text"], tk.REGIME_COLORS, t["accent"]
    f, rad = t["font"], t["radius"]
    return f"""
:root{{color-scheme:dark;
--nimbus:{s['nimbus']};--front:{s['front']};--line:{s['line']};--line-hex:{s['line_hex']};
--grid:{s['grid']};
--tx1:{txt['primary']};--tx2:{txt['secondary']};--tx3:{txt['dim']};
--calm:{reg['calm']};--trend:{reg['trend']};--chop:{reg['chop']};--crisis:{reg['crisis']};
--beacon:{acc['beacon']};
--disp:{f['display']};--ui:{f['ui']};--mono:{f['mono']};
--r-card:{rad['card']}px;--r-pill:{rad['pill']}px;
--sp:8px}}
*{{box-sizing:border-box}}
html{{-webkit-text-size-adjust:100%}}
body{{margin:0;background:var(--nimbus);color:var(--tx1);
font:400 15px/1.55 var(--ui);
padding-top:env(safe-area-inset-top);padding-bottom:env(safe-area-inset-bottom)}}
.wrap{{max-width:1120px;margin:0 auto;padding:0 24px 64px}}
a{{color:var(--beacon);text-decoration:none}}
a:hover{{text-decoration:underline}}
:focus-visible{{outline:2px solid var(--beacon);outline-offset:2px;border-radius:4px}}

/* header ------------------------------------------------------------------------------------ */
header{{position:sticky;top:0;z-index:10;background:var(--nimbus);
border-bottom:1px solid var(--line);padding-top:env(safe-area-inset-top)}}
.bar{{max-width:1120px;margin:0 auto;padding:12px 24px;display:flex;align-items:center;
gap:16px;flex-wrap:wrap}}
.brand{{font-family:var(--disp);font-weight:500;font-size:16px;color:var(--tx1);white-space:nowrap}}
nav{{display:flex;gap:4px;flex-wrap:wrap;margin-left:auto}}
nav a{{color:var(--tx2);padding:8px 12px;border-radius:var(--r-pill);font-size:14px;
min-height:44px;display:inline-flex;align-items:center}}
nav a:hover{{color:var(--tx1);text-decoration:none}}
nav a[aria-current=page]{{color:var(--tx1);background:var(--front)}}
.live{{display:inline-flex;align-items:center;gap:6px;color:var(--tx3);font:400 12px/1 var(--mono)}}
.dot{{width:7px;height:7px;border-radius:50%;background:var(--beacon);display:inline-block}}
/* The liveness dot uses the ACCENT, never a regime colour. Regime colours carry one meaning on
   this surface — the state of a market — and a green dot in the header that means "the build ran"
   quietly teaches the reader that green means fine. */
.dot.pulse{{animation:beat 2.4s ease-in-out infinite}}
@keyframes beat{{0%,100%{{opacity:1}}50%{{opacity:.35}}}}

/* the signature element ---------------------------------------------------------------------- */
.banner{{padding:40px 0 32px;border-bottom:1px solid var(--line);margin-bottom:32px}}
.eyebrow{{font:400 12px/1 var(--mono);color:var(--tx3);letter-spacing:.06em;
text-transform:uppercase;margin-bottom:14px}}
.word{{font-family:var(--disp);font-weight:500;font-size:clamp(44px,9vw,76px);line-height:1;
margin:0 0 10px;letter-spacing:-.02em}}
.gloss{{color:var(--tx2);font-size:15px;margin:0 0 20px;max-width:52ch}}
.metrics{{display:flex;gap:32px;flex-wrap:wrap;font-family:var(--mono);font-size:13px;
font-variant-numeric:tabular-nums}}
.metrics div{{display:flex;flex-direction:column;gap:3px}}
.metrics dt,.mlabel{{color:var(--tx3);font-size:11px;letter-spacing:.05em;text-transform:uppercase}}
.mval{{color:var(--tx1);font-size:19px;font-weight:500}}
.calm{{color:var(--calm)}}.trend{{color:var(--trend)}}.chop{{color:var(--chop)}}
.crisis{{color:var(--crisis)}}
.bg-calm{{background:var(--calm)}}.bg-trend{{background:var(--trend)}}
.bg-chop{{background:var(--chop)}}.bg-crisis{{background:var(--crisis)}}

/* cards and tables --------------------------------------------------------------------------- */
h2{{font-family:var(--disp);font-weight:500;font-size:18px;margin:40px 0 14px}}
h3{{font-size:13px;font-weight:500;color:var(--tx2);margin:0 0 10px;
letter-spacing:.05em;text-transform:uppercase}}
.card{{background:var(--front);border:1px solid var(--line);border-radius:var(--r-card);
padding:20px;animation:rise .15s ease-out}}
@keyframes rise{{from{{opacity:0}}to{{opacity:1}}}}
.grid{{display:grid;gap:16px;grid-template-columns:repeat(auto-fill,minmax(248px,1fr))}}
.scroll{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
table{{border-collapse:collapse;width:100%;font-size:14px}}
th,td{{padding:11px 12px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}}
th{{color:var(--tx3);font-size:11px;font-weight:500;letter-spacing:.05em;text-transform:uppercase}}
td.num,th.num{{text-align:right;font-family:var(--mono);font-variant-numeric:tabular-nums}}
tbody tr:last-child td{{border-bottom:0}}
.pill{{display:inline-flex;align-items:center;gap:7px;white-space:nowrap}}

/* status ------------------------------------------------------------------------------------- */
.badge{{display:inline-block;border:1px solid var(--chop);color:var(--chop);
border-radius:var(--r-pill);padding:3px 11px;font:400 12px/1.5 var(--mono)}}
.state{{border:1px solid var(--line);border-radius:var(--r-card);padding:24px;color:var(--tx2);
background:var(--front)}}
.state strong{{display:block;color:var(--tx1);font-weight:500;margin-bottom:6px}}
footer{{border-top:1px solid var(--line);margin-top:56px;padding:24px 0;color:var(--tx3);
font-size:13px}}
footer p{{margin:0 0 6px}}
.mono{{font-family:var(--mono);font-variant-numeric:tabular-nums}}
.tx2{{color:var(--tx2)}}.tx3{{color:var(--tx3)}}

@media (max-width:640px){{
  .wrap,.bar{{padding-left:16px;padding-right:16px}}
  nav{{width:100%;margin-left:0;overflow-x:auto;flex-wrap:nowrap}}
  .metrics{{gap:20px}}
}}
@media (prefers-reduced-motion:reduce){{
  *{{animation:none!important;transition:none!important}}
}}
""".strip()


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------


def esc(v: object) -> str:
    return html.escape(str(v), quote=True)


def num(v: object, places: int = 2, dash: str = "—") -> str:
    if v is None or isinstance(v, bool):
        return dash
    try:
        return f"{float(v):.{places}f}"
    except (TypeError, ValueError):
        return dash


def pct(v: object, dash: str = "—") -> str:
    if v is None:
        return dash
    try:
        return f"{float(v):.0f}"
    except (TypeError, ValueError):
        return dash


def regime_pill(regime: str) -> str:
    """Regime is never colour alone: a dot AND the word (design system, and 8% of men)."""
    r = esc(regime or "unknown")
    return f'<span class="pill"><span class="dot bg-{r}"></span><span class="{r}">{r}</span></span>'


def shell(page: str, title: str, state: dict, body: str, *, heading: str = "") -> str:
    stale = state.get("drift", {}).get("model_stale")
    through = esc(state.get("data_through", ""))
    nav = "".join(
        f'<a href="{h}"{" aria-current=page" if h == page else ""}>{esc(label)}</a>'
        for h, label in NAV
    )
    badge = '<span class="badge">stale — the last build did not complete</span>' if stale else ""
    # Critical CSS is inlined in full: the whole stylesheet is ~4 KB, and a second request to save
    # 4 KB costs more than it saves on any connection a treasurer is actually on.
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{esc(title)} · FX Regime Radar</title>
<meta name="description" content="Current market regime, 5-day change risk and anomaly readings for {len(all_pairs(state))} markets. {DISCLAIMER}">
<meta name="theme-color" content="{tk.TOKENS['surface']['nimbus']}">
<link rel="manifest" href="manifest.webmanifest">
<link rel="apple-touch-icon" href="icon-180.png">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<style>{stylesheet()}</style>
<!-- Fonts load without blocking the first paint: the page is readable in the system stack
     before a webfont arrives, and swapping a face in is cheaper than delaying every word. -->
<link rel="preload" as="style" href="{tk.FONT_IMPORT}" onload="this.rel='stylesheet'">
</head>
<body>
<header><div class="bar">
<span class="brand">FX Regime Radar</span>
<span class="live"><span class="dot pulse"></span>through {through}</span>
<nav aria-label="Sections">{nav}</nav>
</div></header>
<main class="wrap">
{f'<h1 class="word" style="font-size:28px;margin:32px 0 8px">{esc(heading)}</h1>' if heading else ""}
{badge}
{body}
</main>
<footer class="wrap">
<p><strong>{DISCLAIMER}</strong></p>
<p>Regimes, change risk and anomaly scores only. This system models no price direction and gives no personal recommendation.</p>
<p class="mono tx3">data through {through} · built {esc(state.get("generated_at", ""))} · <a href="state.json">state.json</a></p>
</footer>
<script src="app.js" defer></script>
</body>
</html>
"""


def all_pairs(state: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for uni in state.get("markets", {}).values():
        out.update(uni.get("pairs", {}))
    return out


def lead_pair(state: dict) -> tuple[str, dict]:
    fx = state.get("markets", {}).get("fx", {}).get("pairs", {})
    if fx:
        code = next(iter(fx))
        return code, fx[code]
    pairs = all_pairs(state)
    code = next(iter(pairs), "")
    return code, pairs.get(code, {})


# ---------------------------------------------------------------------------------------------
# pages
# ---------------------------------------------------------------------------------------------


def condition_banner(code: str, p: dict, state: dict) -> str:
    regime = str(p.get("regime", "unknown"))
    lo, hi = p.get("risk_lo"), p.get("risk_hi")
    band = f"{num(lo)} to {num(hi)}" if lo is not None and hi is not None else "—"
    return f"""<section class="banner">
<p class="eyebrow">{esc(p.get("label", code))} · through {esc(state.get("data_through", ""))}</p>
<p class="word {esc(regime)}">{esc(regime)}</p>
<p class="gloss">{esc(REGIME_GLOSS.get(regime, ""))} — day {esc(p.get("days_in_regime", "—"))} of this regime.</p>
<div class="metrics">
<div><span class="mlabel">change risk, 5 day</span><span class="mval">{num(p.get("change_risk_5d"))}</span><span class="tx3">band {esc(band)}</span></div>
<div><span class="mlabel">siren</span><span class="mval">{pct(p.get("anomaly_pct"))}<span class="tx3" style="font-size:13px"> of 100</span></span><span class="tx3">how unusual today is</span></div>
<div><span class="mlabel">model agreement</span><span class="mval">{esc(p.get("agreement", "—"))}<span class="tx3" style="font-size:13px"> of 3</span></span><span class="tx3">independent voters</span></div>
</div>
</section>"""


def market_table(uni: dict, name: str) -> str:
    rows = []
    for code, p in uni.get("pairs", {}).items():
        lo, hi = p.get("risk_lo"), p.get("risk_hi")
        band = f"{num(lo)}–{num(hi)}" if lo is not None and hi is not None else "—"
        rows.append(
            f"<tr><td>{esc(p.get('label', code))}</td>"
            f"<td>{regime_pill(str(p.get('regime', '')))}</td>"
            f"<td class=num>{num(p.get('change_risk_5d'))}</td>"
            f"<td class='num tx3'>{esc(band)}</td>"
            f"<td class=num>{pct(p.get('anomaly_pct'))}</td>"
            f"<td class=num>{esc(p.get('days_in_regime', '—'))}</td>"
            f"<td class=num>{esc(p.get('agreement', '—'))}/3</td></tr>"
        )
    return f"""<h2>{esc(uni.get("label", name))}</h2>
<div class="card scroll"><table>
<thead><tr><th>market</th><th>regime</th><th class=num>change risk</th><th class=num>band</th>
<th class=num>siren</th><th class=num>days</th><th class=num>agree</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>"""


def page_overview(state: dict) -> str:
    code, p = lead_pair(state)
    body = [condition_banner(code, p, state)]
    counts: dict[str, int] = {}
    for blk in all_pairs(state).values():
        counts[str(blk.get("regime", "?"))] = counts.get(str(blk.get("regime", "?")), 0) + 1
    chips = "".join(
        f'<div class="card"><h3>{esc(r)}</h3>'
        f'<p class="mono" style="font-size:30px;margin:0;color:var(--{esc(r)})">{n}</p>'
        f'<p class="tx3" style="margin:4px 0 0;font-size:13px">of {len(all_pairs(state))} markets</p></div>'
        for r, n in sorted(counts.items(), key=lambda kv: -kv[1])
    )
    body.append(f'<h2>Today across every board</h2><div class="grid">{chips}</div>')
    for name, uni in state.get("markets", {}).items():
        body.append(market_table(uni, name))
    return shell("index.html", "Overview", state, "\n".join(body))


def page_pairs(state: dict) -> str:
    body = []
    for name, uni in state.get("markets", {}).items():
        cards = []
        for code, p in uni.get("pairs", {}).items():
            lo, hi = p.get("risk_lo"), p.get("risk_hi")
            band = f"{num(lo)} to {num(hi)}" if lo is not None and hi is not None else "—"
            cards.append(
                f'<div class="card"><h3>{esc(p.get("label", code))}</h3>'
                f'<p style="margin:0 0 12px;font-family:var(--disp);font-size:26px" class="{esc(p.get("regime", ""))}">{esc(p.get("regime", ""))}</p>'
                f"<table><tbody>"
                f'<tr><td class=tx3>change risk</td><td class=num>{num(p.get("change_risk_5d"))}</td></tr>'
                f'<tr><td class=tx3>band</td><td class="num tx3">{esc(band)}</td></tr>'
                f'<tr><td class=tx3>siren</td><td class=num>{pct(p.get("anomaly_pct"))}</td></tr>'
                f'<tr><td class=tx3>day of regime</td><td class=num>{esc(p.get("days_in_regime", "—"))}</td></tr>'
                f'<tr><td class=tx3>agreement</td><td class=num>{esc(p.get("agreement", "—"))}/3</td></tr>'
                f"</tbody></table></div>"
            )
        body.append(
            f'<h2>{esc(uni.get("label", name))}</h2><div class="grid">{"".join(cards)}</div>'
        )
    return shell(
        "pairs.html", "Pairs", state, "\n".join(body), heading="Every market, side by side"
    )


def page_treasury(state: dict) -> str:
    lights = state.get("treasury", {})
    pairs = all_pairs(state)
    if not lights:
        body = (
            '<div class="state"><strong>No treasury reading published today.</strong>'
            "The daily build writes this file after the models score. If it is missing, the "
            "build did not finish — the Overview still shows the market state it did compute.</div>"
        )
    else:
        rows = []
        for code, blk in lights.items():
            label = pairs.get(code, {}).get("label", code)
            rows.append(
                f'<div class="card"><h3>{esc(label)}</h3>'
                f'<p style="margin:0 0 10px;font-family:var(--disp);font-size:24px">{esc(blk.get("light", "—"))}</p>'
                f'<p class="tx2" style="margin:0;font-size:14px">{esc(blk.get("reason", ""))}</p></div>'
            )
        body = f'<div class="grid">{"".join(rows)}</div>'
    note = (
        '<div class="state" style="margin-top:24px"><strong>What this is, and what it is not.</strong>'
        "This light reflects how much risk the current regime carries and how close the next "
        "scheduled event is. It is not a view on where the rate will go, and it is not a "
        "recommendation for your situation. Sizing a hedge against a real exposure is a "
        "conversation with your bank or a licensed adviser.</div>"
    )
    return shell(
        "treasury.html", "Treasury", state, body + note, heading="Risk conditions for hedgers"
    )


def page_storms(state: dict) -> str:
    body = (
        '<div class="state"><strong>Storm replays live in the full console.</strong>'
        "Named episodes — the 2015 franc, Brexit, March 2020, 2022 — are replayed day by day "
        'against the model that was frozen before them. <a href="index.html">Today\'s reading</a> '
        "is on the Overview.</div>"
    )
    return shell("storms.html", "Storms", state, body, heading="When the weather turned")


def page_proof(state: dict) -> str:
    led = state.get("ledger", {})
    resolved = led.get("n_resolved") or 0
    live = num(led.get("live_brier"), 3) if resolved else "not yet"
    rows = [
        ("days live", led.get("days_live", "—")),
        ("forecasts written", led.get("n_forecasts", "—")),
        ("resolved so far", resolved),
        ("live Brier score", live),
        ("frozen Brier (validation)", num(led.get("frozen_brier"), 3)),
        ("frozen PR-AUC", num(led.get("frozen_pr_auc"), 3)),
        ("coverage, frozen", num(led.get("coverage_frozen"), 3)),
        ("chain head", led.get("chain_head_short", "—")),
    ]
    table = "".join(
        f"<tr><td class=tx2>{esc(k)}</td><td class=num>{esc(v)}</td></tr>" for k, v in rows
    )
    intro = (
        '<div class="state"><strong>Every forecast is written down before its outcome is known.</strong>'
        "The ledger is append-only and hash-chained: each row carries the hash of the one before "
        "it, so editing any past forecast changes every hash after it and the head no longer "
        "matches. You do not have to take our word for the record — recompute the chain from the "
        "published file and compare the head.</div>"
    )
    body = f"""{intro}
<h2>The record so far</h2>
<div class="card scroll"><table><tbody>{table}</tbody></table></div>
<p class="tx3" style="font-size:13px;margin-top:14px">A live Brier score reads "not yet" until
forecasts mature. It is not zero — zero would mean a perfect score, and nothing has resolved.</p>"""
    return shell("proof.html", "Proof", state, body, heading="The record, and how to check it")


# ---------------------------------------------------------------------------------------------
# PWA
# ---------------------------------------------------------------------------------------------


def manifest() -> str:
    return json.dumps(
        {
            "name": "FX Regime Radar",
            "short_name": "FX Radar",
            "description": f"Market regime, change risk and anomaly readings. {DISCLAIMER}",
            "start_url": "./index.html",
            "scope": "./",
            "display": "standalone",
            "background_color": tk.TOKENS["surface"]["nimbus"],
            "theme_color": tk.TOKENS["surface"]["nimbus"],
            "icons": [
                {"src": "icon-180.png", "sizes": "180x180", "type": "image/png"},
                {
                    "src": "icon-512.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any maskable",
                },
            ],
        },
        indent=1,
    )


def service_worker(context_version: str) -> str:
    """Cache the shell and the last state.

    A cold open offline shows yesterday's reading behind a stale badge rather than a blank screen.
    That is the right default for daily data — a reading one day old is still most of the truth, and
    a blank page is none of it. It would be the WRONG default for anything intraday, where a stale
    number is not a weaker version of the answer but a different one.
    """
    files = json.dumps(
        [
            "./",
            "./index.html",
            "./pairs.html",
            "./treasury.html",
            "./storms.html",
            "./proof.html",
            "./app.js",
            "./state.json",
            "./manifest.webmanifest",
        ]
    )
    return f"""// Generated by scripts/build_static.py — do not edit.
const VERSION = "fxradar-{context_version}";
const SHELL = {files};

self.addEventListener("install", (e) => {{
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
}});

self.addEventListener("activate", (e) => {{
  // One cache per context version, so yesterday's pages are dropped the morning after rather than
  // lingering behind a version that no longer exists.
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
}});

self.addEventListener("fetch", (e) => {{
  if (e.request.method !== "GET") return;
  // Network first, cache as the floor. The freshest reading wins whenever the network can supply
  // one; the cache exists so that "no network" means "yesterday, labelled" and never a blank page.
  e.respondWith(
    fetch(e.request)
      .then((res) => {{
        const copy = res.clone();
        caches.open(VERSION).then((c) => c.put(e.request, copy)).catch(() => {{}});
        return res;
      }})
      .catch(() => caches.match(e.request).then((hit) => hit || caches.match("./index.html")))
  );
}});
"""


APP_JS = """// Progressive enhancement only. Every number on these pages is already in the HTML the server
// sent; nothing here is required to read the market state. If this file fails to load, the page is
// still correct — which is the whole reason the state is baked at build time.
(function () {
  "use strict";

  // Register the service worker so a cold open offline shows yesterday's reading with a badge.
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("sw.js").catch(function () {});
    });
  }

  // If the cached page is older than the published state, say so rather than showing a stale
  // number as though it were today's. The badge is the honest version of a fast page.
  var meta = document.querySelector('[data-through]');
  fetch("state.json", { cache: "no-cache" })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (fresh) {
      if (!fresh || !meta) return;
      if (fresh.data_through && fresh.data_through !== meta.getAttribute("data-through")) {
        var b = document.createElement("p");
        b.className = "badge";
        b.setAttribute("role", "status");
        b.textContent = "A newer reading is published — reload for " + fresh.data_through;
        var main = document.querySelector("main");
        if (main) main.insertBefore(b, main.firstChild);
      }
    })
    .catch(function () {});
})();
"""


def write_icons() -> dict[str, int]:
    """The home-screen icon: the four regime colours as a quadrant on the app ground.

    Drawn from `design/tokens.json` rather than shipped as a binary, so a palette change repaints
    the icon with everything else and no one has to remember a PNG exists. Deterministic — the same
    tokens produce the same bytes, so a rebuild does not churn the repository.
    """
    from PIL import Image, ImageDraw  # noqa: PLC0415

    out: dict[str, int] = {}
    reg = tk.REGIME_COLORS
    order = [reg["calm"], reg["trend"], reg["chop"], reg["crisis"]]
    for size in (180, 512):
        img = Image.new("RGB", (size, size), tk.TOKENS["surface"]["nimbus"])
        d = ImageDraw.Draw(img)
        # A generous safe margin: maskable icons are cropped to a circle on Android, and a design
        # that runs to the edge loses its corners on exactly the platform that asked for it.
        m = round(size * 0.22)
        cell = (size - 2 * m) // 2
        gap = max(2, round(size * 0.012))
        for i, colour in enumerate(order):
            x = m + (i % 2) * (cell + gap)
            y = m + (i // 2) * (cell + gap)
            d.rounded_rectangle(
                [x, y, x + cell - gap, y + cell - gap],
                radius=max(2, round(cell * 0.18)),
                fill=colour,
            )
        path = PUBLIC / f"icon-{size}.png"
        img.save(path, "PNG", optimize=True)
        out[path.name] = path.stat().st_size
    return out


# ---------------------------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------------------------


def build(state: dict | None = None) -> dict[str, int]:
    if state is None:
        if not STATE.exists():
            raise SystemExit(
                "public/state.json is missing — run `python -m fxradar.public_state` first."
            )
        state = json.loads(STATE.read_text())

    PUBLIC.mkdir(parents=True, exist_ok=True)
    pages = {
        "index.html": page_overview(state),
        "pairs.html": page_pairs(state),
        "treasury.html": page_treasury(state),
        "storms.html": page_storms(state),
        "proof.html": page_proof(state),
        "app.js": APP_JS,
        "manifest.webmanifest": manifest(),
        "sw.js": service_worker(str(state.get("context_version", "0"))),
    }
    # The data-through stamp the enhancement script compares against.
    for name in list(pages):
        if name.endswith(".html"):
            pages[name] = pages[name].replace(
                '<main class="wrap">',
                f'<main class="wrap" data-through="{esc(state.get("data_through", ""))}">',
                1,
            )

    written: dict[str, int] = {}
    for name, content in pages.items():
        path = PUBLIC / name
        path.write_text(content)
        written[name] = len(content.encode())

    # The widget travels with the site so the avatar is reachable from the static surface.
    widget_src = ROOT / "rust/fxradar-serve/static/avatar.html"
    if widget_src.exists():
        shutil.copyfile(widget_src, PUBLIC / "avatar.html")
        written["avatar.html"] = (PUBLIC / "avatar.html").stat().st_size
    written.update(write_icons())
    written["state.json"] = STATE.stat().st_size if STATE.exists() else 0
    return written


def main() -> None:
    sizes = build()
    total = sizes.get("index.html", 0) + sizes.get("state.json", 0) + sizes.get("app.js", 0)
    print(f"built {len([k for k in sizes if k.endswith('.html')])} pages into public/")
    for name, size in sorted(sizes.items(), key=lambda kv: -kv[1]):
        print(f"  {name:24s} {size:>7,} B")
    print(f"\nOverview first load (html + state + js): {total:,} B")


if __name__ == "__main__":
    main()
