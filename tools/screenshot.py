"""Full-page screenshot of the running Streamlit app via Chrome DevTools Protocol (dev tool only).

Usage:
  .venv/bin/python tools/screenshot.py URL OUT.png [--wait 8] [--width 1440] [--height 1600]
                                       [--mobile] [--eval "JS expression"]
--mobile emulates a touch device (mobile viewport, 2x pixel ratio) so Streamlit's responsive
layout behaves as it does on a phone. --eval prints the value of a JS expression (page introspection).
Needs Google Chrome installed; uses the `websockets` package that Streamlit already depends on.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import subprocess
import tempfile
import time
import urllib.request

import websockets

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9333


async def shoot(
    url: str,
    out: str,
    wait_s: float,
    width: int,
    height: int,
    mobile: bool = False,
    js: str | None = None,
) -> None:
    proc = subprocess.Popen(
        [
            CHROME,
            "--headless=new",
            "--use-angle=swiftshader",  # software WebGL so the orb renders like a real browser
            "--enable-unsafe-swiftshader",
            f"--remote-debugging-port={PORT}",
            f"--window-size={width},{height}",
            f"--user-data-dir={tempfile.mkdtemp(prefix='fxradar-shot-')}",  # clean profile: no remembered sidebar state
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                break
            except Exception:
                time.sleep(0.2)
        ws_url = next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page")
        async with websockets.connect(ws_url, max_size=50_000_000) as ws:
            mid = 0

            async def call(method: str, **params):
                nonlocal mid
                mid += 1
                await ws.send(json.dumps({"id": mid, "method": method, "params": params}))
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("id") == mid:
                        return msg.get("result", {})

            if mobile:
                await call(
                    "Emulation.setDeviceMetricsOverride",
                    width=width,
                    height=height,
                    deviceScaleFactor=2,
                    mobile=True,
                )
                await call("Emulation.setTouchEmulationEnabled", enabled=True)
            await call("Page.navigate", url=url)
            await asyncio.sleep(wait_s)  # let the Streamlit websocket render everything
            if width >= 769 and not mobile:
                # Full-page capture does not paint the sidebar's transitioned layer in headless
                # Chrome even when it is open (aria-expanded=true): pin it so shots match a browser.
                await call(
                    "Runtime.evaluate",
                    expression=(
                        "(()=>{const s=document.querySelector('[data-testid=stSidebar]');"
                        "if(s&&s.getAttribute('aria-expanded')!=='false'){s.style.transition='none';"
                        "s.style.transform='none';s.style.display='block';}return !!s})()"
                    ),
                    returnByValue=True,
                )
                await asyncio.sleep(0.5)
            if js:
                res = await call(
                    "Runtime.evaluate", expression=js, returnByValue=True, awaitPromise=True
                )
                print(res.get("result", {}).get("value"))
            shot = await call("Page.captureScreenshot", format="png", captureBeyondViewport=True)
            with open(out, "wb") as f:
                f.write(base64.b64decode(shot["data"]))
            print(f"saved {out} ({width}x{height}{' mobile' if mobile else ''})")
    finally:
        proc.terminate()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("out")
    ap.add_argument("--wait", type=float, default=8.0)
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=1600)
    ap.add_argument("--mobile", action="store_true")
    ap.add_argument("--eval", dest="js", default=None)
    a = ap.parse_args()
    asyncio.run(shoot(a.url, a.out, a.wait, a.width, a.height, a.mobile, a.js))
