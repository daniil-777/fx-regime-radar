#!/usr/bin/env python3
"""Don't trust us — verify. Recomputes the SHA-256 hash chain of data/ledger.jsonl on a fresh clone.
Standard library only. Usage: python scripts/verify_ledger.py [path/to/ledger.jsonl]"""

import hashlib
import json
import sys
from pathlib import Path

V1 = ["date", "pair", "regime", "change_risk_5d", "anomaly_pct", "model_version", "recorded_at_utc"]
V2 = [
    "date",
    "pair",
    "regime",
    "p_calm",
    "p_trend",
    "p_chop",
    "p_crisis",
    "change_risk_5d",
    "risk_lo",
    "risk_hi",
    "conformal_q",
    "anomaly_pct",
    "bocpd_run_length",
    "bocpd_p_change_5d",
    "vote_hmm",
    "vote_bocpd",
    "vote_vol",
    "agreement",
    "model_version",
    "git_sha",
    "schema",
    "correction_of",
    "recorded_at_utc",
]
GENESIS = "0" * 64


def verify(path: Path) -> tuple[bool, str, int]:
    prev, n = GENESIS, 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        fields = V1 if row.get("schema") in (None, 1) else V2
        payload = json.dumps({c: row.get(c) for c in fields}, sort_keys=True)
        expect = hashlib.sha256(f"{prev}|{payload}".encode()).hexdigest()
        if row.get("prev_hash", prev) != prev or row["row_hash"] != expect:
            return False, prev, n
        prev, n = row["row_hash"], n + 1
    return True, prev, n


if __name__ == "__main__":
    p = Path(sys.argv[1] if len(sys.argv) > 1 else "data/ledger.jsonl")
    ok, head, n = verify(p)
    print(f"{'VALID' if ok else 'BROKEN'} rows={n} head={head}")
    sys.exit(0 if ok else 1)
