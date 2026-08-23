#!/usr/bin/env python3
"""Performance budgets for the static surface, enforced rather than aspired to (phase 44).

A one-off measurement tells you the site was fast the day someone looked. A budget in CI tells you
the day it stopped being fast, which is the only version that survives contact with a team — every
regression arrives as a reasonable-looking change, and the person making it is never the person who
remembers the number.

## What this checks, and what it cannot

This runs in CI with no browser, so it measures **bytes and structure**: the payload of a cold load,
whether text is reachable without executing script, whether anything can shift the layout after
paint, whether touch targets are large enough, and the accessibility basics that are decidable from
markup.

It does **not** measure first contentful paint, time-to-interactive or a Lighthouse score, because
those need a real browser on a throttled profile. Those three budgets are listed in
`docs/PERFORMANCE.md` with the runner that produces them; this script deliberately does not print a
guess in their place. A fabricated 1.1 s is worse than an absent one — the absent number gets
measured eventually, the fabricated one never does.

The structural checks below are how the paint budgets are *met*, so a regression in FCP almost
always shows up here first as a script in the critical path or an uninlined stylesheet.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"

# Cold load of the Overview: the HTML a visitor receives, plus everything needed to paint it.
# The state artifact is counted even though the baked page does not wait for it, because the
# service worker fetches it on the same visit and a budget that ignores real bytes is decoration.
OVERVIEW_BUDGET = 200_000
STATE_BUDGET = 50_000
# Any single page. A page that quietly grows past this is carrying data that belongs in a table.
PAGE_BUDGET = 120_000
MIN_TOUCH_PX = 44


class Result:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.notes: list[str] = []

    def check(self, ok: bool, message: str) -> None:
        (self.notes if ok else self.failures).append(("ok   " if ok else "FAIL ") + message)


def bytes_of(name: str) -> int:
    p = PUBLIC / name
    return p.stat().st_size if p.exists() else 0


def check_payload(r: Result) -> None:
    overview = bytes_of("index.html") + bytes_of("state.json") + bytes_of("app.js")
    r.check(
        overview <= OVERVIEW_BUDGET,
        f"Overview cold load {overview:,} B of {OVERVIEW_BUDGET:,} B budget",
    )
    r.check(
        bytes_of("state.json") <= STATE_BUDGET,
        f"state.json {bytes_of('state.json'):,} B of {STATE_BUDGET:,} B",
    )
    for page in PUBLIC.glob("*.html"):
        if page.name == "avatar.html":
            continue  # the widget is its own surface with its own budget
        size = page.stat().st_size
        r.check(size <= PAGE_BUDGET, f"{page.name} {size:,} B of {PAGE_BUDGET:,} B")


def check_text_renders_without_script(r: Result) -> None:
    """The train-tunnel test: strip every script and the market state must still be readable."""
    for page in PUBLIC.glob("*.html"):
        if page.name == "avatar.html":
            continue
        html = page.read_text()
        stripped = re.sub(r"<script\b.*?</script>", "", html, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", stripped)
        r.check(
            len(text.split()) > 40,
            f"{page.name} renders {len(text.split())} words with every script removed",
        )
    index = (PUBLIC / "index.html").read_text()
    head = index.split("</head>")[0]
    r.check("<style>" in head, "critical CSS is inlined in the head")
    blocking = [
        m.group(0)
        for m in re.finditer(r'<link\b[^>]*rel="stylesheet"[^>]*>', head)
        if 'media="print"' not in m.group(0)
    ]
    r.check(
        not blocking,
        f"no render-blocking stylesheet in the head ({len(blocking)} found)",
    )
    for m in re.finditer(r"<script\b([^>]*)>", index):
        attrs = m.group(1)
        if "src=" in attrs:
            r.check(
                "defer" in attrs or "async" in attrs,
                f"script is deferred, not render-blocking:{attrs[:60]}",
            )


def check_no_layout_shift(r: Result) -> None:
    """Zero CLS is structural here: nothing arrives after paint that could move anything.

    So rather than measuring a shift, check the two things that would cause one — an image without
    intrinsic dimensions, and a script that inserts content into the document flow above existing
    content.
    """
    for page in PUBLIC.glob("*.html"):
        html = page.read_text()
        for img in re.finditer(r"<img\b([^>]*)>", html):
            attrs = img.group(1)
            r.check(
                ("width=" in attrs and "height=" in attrs) or "aspect-ratio" in attrs,
                f"{page.name}: img reserves its space ({attrs[:50]})",
            )
    app = (PUBLIC / "app.js").read_text()
    inserts = re.findall(r"insertBefore|prepend\(", app)
    # One is expected and intentional: the "a newer reading is published" badge. It is inserted
    # only when the cached page is out of date, which is a state where a shift is the point.
    r.check(
        len(inserts) <= 1,
        f"app.js performs {len(inserts)} in-flow insertion(s) (1 allowed: the newer-reading badge)",
    )


def check_touch_targets(r: Result) -> None:
    css = (PUBLIC / "index.html").read_text()
    nav_rule = re.search(r"nav a\{([^}]*)\}", css)
    r.check(
        bool(nav_rule)
        and f"min-height:{MIN_TOUCH_PX}px" in (nav_rule.group(1) if nav_rule else ""),
        f"navigation targets are at least {MIN_TOUCH_PX} px tall",
    )
    r.check(
        ":hover" in css and ":focus-visible" in css,
        "keyboard focus is styled, not only hover",
    )
    hover_only = re.findall(r"([.#\w-]+):hover\{[^}]*\}", css)
    for sel in hover_only:
        pair = f"{sel}:focus" in css or f"{sel}:focus-visible" in css or ":focus-visible{" in css
        r.check(pair, f"{sel}:hover has a non-hover equivalent (no hover-only affordance)")


def check_accessibility_basics(r: Result) -> None:
    for page in PUBLIC.glob("*.html"):
        if page.name == "avatar.html":
            continue
        html = page.read_text()
        r.check('<html lang="' in html, f"{page.name} declares a language")
        r.check("<title>" in html, f"{page.name} has a title")
        r.check(
            'name="viewport"' in html and "viewport-fit=cover" in html,
            f"{page.name} sets a viewport with safe-area support",
        )
        r.check(
            "prefers-reduced-motion" in html,
            f"{page.name} honours prefers-reduced-motion",
        )
        # Regime must never be colour-only — but only where a regime is actually being shown.
        # A dot that carries some other meaning is not a regime indicator and must not be scored
        # as one; that distinction is the reason the liveness dot uses the accent colour.
        for m in re.finditer(
            r'<span class="dot bg-(\w+)"></span><span class="\w+">(\w+)</span>', html
        ):
            r.check(
                m.group(1) == m.group(2),
                f"{page.name}: regime dot {m.group(1)!r} is paired with the word {m.group(2)!r}",
            )
        for regime in ("calm", "trend", "chop", "crisis"):
            if 'class="pill"' in html and f"bg-{regime}" in html.split("<body")[-1]:
                r.check(
                    f">{regime}</span>" in html,
                    f"{page.name}: regime {regime!r} appears as a word beside its colour",
                )


def check_motion_budget(r: Result) -> None:
    """The design system allows the ambient orb, the live dot, and (phase 44) a <=150 ms card fade.
    A third ambient animation is not a small addition; it is the end of the budget."""
    css = (PUBLIC / "index.html").read_text()
    keyframes = set(re.findall(r"@keyframes\s+([\w-]+)", css))
    r.check(
        len(keyframes) <= 2,
        f"{len(keyframes)} keyframe animations on the static surface: {sorted(keyframes)} (2 allowed)",
    )
    for m in re.finditer(r"animation:[^;}]*?([\d.]+)s", css):
        secs = float(m.group(1))
        if "rise" in m.group(0):
            r.check(secs <= 0.15, f"card entry fade is {secs}s (budget 0.15s)")


def check_pwa(r: Result) -> None:
    man = PUBLIC / "manifest.webmanifest"
    r.check(man.exists(), "a web app manifest is published")
    if man.exists():
        m = json.loads(man.read_text())
        r.check(m.get("display") == "standalone", "manifest requests standalone display")
        r.check(bool(m.get("theme_color")), "manifest sets a theme colour")
        for icon in m.get("icons", []):
            r.check(
                (PUBLIC / icon["src"]).exists(),
                f"manifest icon {icon['src']} exists ({icon.get('sizes')})",
            )
        r.check(
            any("maskable" in (i.get("purpose") or "") for i in m.get("icons", [])),
            "a maskable icon is provided for Android",
        )
    sw = PUBLIC / "sw.js"
    r.check(sw.exists(), "a service worker is published")
    if sw.exists():
        body = sw.read_text()
        r.check("state.json" in body, "the service worker caches the last state")
        r.check("caches.delete" in body, "the service worker evicts superseded versions")


def check_disclaimer(r: Result) -> None:
    """Golden rule 7, on every user-facing surface, checked rather than remembered."""
    for page in PUBLIC.glob("*.html"):
        if page.name == "avatar.html":
            continue
        r.check(
            "Educational tool. Not investment advice." in page.read_text(),
            f"{page.name} carries the standing disclaimer",
        )


def main() -> int:
    if not (PUBLIC / "index.html").exists():
        print("public/ is not built — run `make static` first.")
        return 1
    r = Result()
    for fn in (
        check_payload,
        check_text_renders_without_script,
        check_no_layout_shift,
        check_touch_targets,
        check_accessibility_basics,
        check_motion_budget,
        check_pwa,
        check_disclaimer,
    ):
        fn(r)

    for line in r.notes:
        print(line)
    if r.failures:
        print()
        for line in r.failures:
            print(line)
        print(f"\nbudgets: {len(r.failures)} FAILED, {len(r.notes)} passed")
        return 1
    print(f"\nbudgets: all {len(r.notes)} checks passed")
    print(
        "note: first contentful paint, time-to-interactive and Lighthouse need a real browser on a\n"
        "      throttled profile — see docs/PERFORMANCE.md. They are not estimated here."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
