"""One JSON line per ask — the document scope's stand-in for the ledger until phase 20 extends it.

Never the raw question (a hash instead), keys sorted, no PII.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from ask import config as askcfg


def append(question: str, record: dict) -> None:
    line = {
        "ts_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "question_sha256": hashlib.sha256(question.strip().lower().encode()).hexdigest(),
        **record,
    }
    askcfg.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with askcfg.LOG_PATH.open("a") as f:
        f.write(json.dumps(line, sort_keys=True) + "\n")
