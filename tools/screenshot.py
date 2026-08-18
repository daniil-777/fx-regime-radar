"""Full-page screenshot of the running Streamlit app via Chrome DevTools Protocol (dev tool only).

Usage: .venv/bin/python tools/screenshot.py http://localhost:8501/ docs/screenshots/dashboard_v1.png [wait_s]
Needs Google Chrome installed; uses the `websockets` package that Streamlit already depends on.
"""

from __future__ import annotations

import asyncio
import base64
import json
import subprocess
import sys
import time
import urllib.request

import websockets

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


async def shoot(url: str, out: str, wait_s: float, width: int = 1440, height: int = 1600) -> None:
    proc = subprocess.Popen(
        [
            CHROME,
            "--headless=new",
            "--disable-gpu",
            "--remote-debugging-port=9333",
            f"--window-size={width},{height}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json"))
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

            await call("Page.navigate", url=url)
            await asyncio.sleep(wait_s)  # let the Streamlit websocket render everything
            shot = await call("Page.captureScreenshot", format="png", captureBeyondViewport=True)
            with open(out, "wb") as f:
                f.write(base64.b64decode(shot["data"]))
            print(f"saved {out} ({width}x{height})")
    finally:
        proc.terminate()


if __name__ == "__main__":
    url, out = sys.argv[1], sys.argv[2]
    wait = float(sys.argv[3]) if len(sys.argv) > 3 else 8.0
    asyncio.run(shoot(url, out, wait))
