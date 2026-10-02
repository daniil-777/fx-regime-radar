"""Render every dashboard page with Streamlit's AppTest INSIDE a built image; exit 1 on any failure.

The health endpoint never runs a page script, so an image missing a file that every page imports
(design/tokens.json, found 2026-10-02 on the first Fly deploy) still reports healthy. This does what
a visitor does — runs each page — and names the first exception per page.

    docker exec -i <container> python - < deploy/smoke_pages.py      # CI (docker.yml)
"""

import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

pages = sorted(Path("app/views").glob("*.py"))
failed = []
for page in pages:
    at = AppTest.from_file(str(page), default_timeout=120).run()
    if at.exception:
        failed.append(page.name)
        print(f"{page.name:24s} EXCEPTION {at.exception[0].message[:200]}", flush=True)
    else:
        print(f"{page.name:24s} ok", flush=True)
print(
    f"{len(pages) - len(failed)}/{len(pages)} pages render"
    + (f"; failed: {failed}" if failed else "")
)
sys.exit(1 if failed else 0)
