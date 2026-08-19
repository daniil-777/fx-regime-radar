"""Stage 2 (phase 30, GATED): a frontier-model opinion on each NEW statement — with receipts.

Status: GATE CLOSED (`GATE_OPEN = False`, see docs/stage2-decision.md). The code is complete and
inert: it costs nothing to have ready, and `gate_status` is re-checked on every run. The CLI has
no bypass flag on purpose.

What it would do when the gate opens:
* `score_live(doc)` — refuse pre-deploy documents (LiveOnlyError, same guard as FinBERT, BEFORE
  any SDK import), check the gate, check the cost cap, then send ONE message: the frozen system
  prompt `prompts/cb_hawkishness_v1.txt` + a JSON user message {bank, published_at, text}.
  Expected reply: {"hawkishness": -1..1, "uncertainty": 0..1, "rationale": "..."}.
* Every call writes a receipt to data/cb/llm_receipts.jsonl: prompt sha256 + version, model id,
  the response's model string, date, document sha256, raw response text, parsed numbers. Years
  later anyone can tell which prompt and which model produced which number.
* No key / API down -> graceful skip and one line in data/ops_log.jsonl (phase-09 pattern).
* The user-facing surfaces never show the rationale or any LLM text; at most the hawkishness
  number moves behind template sentences.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path

from fxradar import config
from fxradar.cb_finbert import LiveOnlyError, assert_live_only
from fxradar.cb_text import BANKS, CB_DIR, DEPLOY_DATE, doc_date, load_docs

log = logging.getLogger(__name__)

GATE_OPEN = False  # flipped only by a phase-30 decision record, never by a flag
# Two policy cycles per bank: ~16 statements for the 8-meeting banks, ~8 for the quarterly SNB.
GATE_MIN_DOCS: dict[str, int] = {"FOMC": 16, "ECB": 16, "BOE": 16, "SNB": 8}
MAX_DOCS_PER_YEAR = 60  # cost cap (~40 statements/year expected + headroom); hygiene, not budget
MODEL = "claude-haiku-4-5"
TEMPERATURE = 0.0
MAX_TOKENS = 300
RETRIES = 2
PROMPT_VERSION = "v1"
PROMPT_PATH = config.ROOT / "prompts" / f"cb_hawkishness_{PROMPT_VERSION}.txt"
RECEIPTS_PATH = CB_DIR / "llm_receipts.jsonl"
OPS_LOG_PATH = config.DATA_DIR / "ops_log.jsonl"


class GateClosedError(RuntimeError):
    """Raised when Stage 2 scoring is requested while the gate is closed."""


# --------------------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------------------
def live_counts(docs: list[dict] | None = None, deploy_date: date = DEPLOY_DATE) -> dict[str, int]:
    """Statements per bank published on/after the deploy date."""
    docs = load_docs() if docs is None else docs
    return {b: sum(1 for d in docs if d["bank"] == b and doc_date(d) >= deploy_date) for b in BANKS}


def gate_status(counts: dict[str, int], effect_ok: bool | None = None) -> dict:
    """Both conditions must hold: enough live statements per bank AND a credible live effect.

    `effect_ok` is the human-agreed event-study verdict (None = not yet assessed = fails).
    """
    shortfall = {b: max(0, GATE_MIN_DOCS[b] - int(counts.get(b, 0))) for b in BANKS}
    counts_ok = all(v == 0 for v in shortfall.values())
    open_ = bool(GATE_OPEN and counts_ok and effect_ok)
    reasons = []
    if not counts_ok:
        reasons.append("live statement counts below threshold: " + json.dumps(shortfall))
    if not effect_ok:
        reasons.append("no credible live event-study effect agreed yet")
    if not GATE_OPEN:
        reasons.append("GATE_OPEN is False (docs/stage2-decision.md)")
    return {
        "open": open_,
        "counts": {b: int(counts.get(b, 0)) for b in BANKS},
        "required": dict(GATE_MIN_DOCS),
        "shortfall": shortfall,
        "counts_ok": counts_ok,
        "effect_ok": bool(effect_ok),
        "reasons": reasons,
    }


# --------------------------------------------------------------------------------------
# prompt + receipts
# --------------------------------------------------------------------------------------
def load_prompt(path: Path = PROMPT_PATH) -> tuple[str, str]:
    """(system prompt text without the leading '#' header lines, sha256 of the whole file)."""
    raw = path.read_bytes()
    lines = [ln for ln in raw.decode("utf-8").splitlines() if not ln.startswith("#")]
    return "\n".join(lines).strip(), hashlib.sha256(raw).hexdigest()


def build_user_message(doc: dict) -> str:
    """Structured JSON in — only bank, publication time and the text. Nothing else."""
    return json.dumps(
        {"bank": doc["bank"], "published_at": doc["published_at"], "text": doc["text"]},
        ensure_ascii=False,
    )


def parse_response(text: str) -> dict:
    """Strict parse of the model's JSON; clamps the numbers; raises on anything else."""
    data = json.loads(text.strip().strip("`").removeprefix("json").strip())
    h = max(-1.0, min(1.0, float(data["hawkishness"])))
    u = max(0.0, min(1.0, float(data["uncertainty"])))
    return {"hawkishness": h, "uncertainty": u, "rationale": str(data.get("rationale", ""))[:400]}


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def ops_log(event: str, detail: str, path: Path = OPS_LOG_PATH) -> None:
    """One line per operational event (skipped call, API down) — never contains the key."""
    _append_jsonl(
        path,
        {
            "ts_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "module": "cb_llm",
            "event": event,
            "detail": detail,
        },
    )


def calls_last_365d(path: Path = RECEIPTS_PATH, now: datetime | None = None) -> int:
    if not path.exists():
        return 0
    now = now or datetime.now(UTC)
    n = 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        ts = datetime.fromisoformat(json.loads(line)["called_at_utc"].replace("Z", "+00:00"))
        if (now - ts).days < 365:
            n += 1
    return n


# --------------------------------------------------------------------------------------
# scoring (inert while the gate is closed)
# --------------------------------------------------------------------------------------
def score_live(
    doc: dict,
    client=None,
    deploy_date: date = DEPLOY_DATE,
    gate: dict | None = None,
    api_key: str | None = None,
    receipts_path: Path = RECEIPTS_PATH,
    ops_path: Path = OPS_LOG_PATH,
) -> dict | None:
    """Score ONE post-deploy statement. Order of checks is the contract:
    1. live-only guard (raises LiveOnlyError — before any SDK import),
    2. gate (raises GateClosedError unless `gate["open"]`),
    3. cost cap (skips with an ops-log line),
    4. key (skips with an ops-log line), then the call with retries; any API error -> skip + log.
    Returns the parsed dict, or None when skipped. `client` is injectable for tests.
    """
    assert_live_only([doc], deploy_date)
    gate = gate if gate is not None else gate_status(live_counts(deploy_date=deploy_date))
    if not gate.get("open"):
        raise GateClosedError("Stage 2 gate is closed: " + "; ".join(gate.get("reasons", [])))
    if calls_last_365d(receipts_path) >= MAX_DOCS_PER_YEAR:
        ops_log("skip_cost_cap", f"{MAX_DOCS_PER_YEAR} calls in the last 365 days", ops_path)
        return None
    system, prompt_sha = load_prompt()
    if client is None:
        from fxradar.narrate import get_api_key  # phase-09 key handling, never logged

        key = api_key or get_api_key()
        if not key:
            ops_log("skip_no_key", "ANTHROPIC_API_KEY absent", ops_path)
            return None
        import anthropic

        client = anthropic.Anthropic(api_key=key, max_retries=RETRIES, timeout=30.0)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            system=system,
            messages=[{"role": "user", "content": build_user_message(doc)}],
        )
        raw = " ".join(b.text for b in response.content if getattr(b, "type", "") == "text")
        parsed = parse_response(raw)
    except Exception as exc:  # API down, bad JSON, rate limit after retries
        ops_log("skip_api_error", type(exc).__name__, ops_path)
        log.info("cb_llm skipped %s %s: %s", doc["bank"], doc_date(doc), type(exc).__name__)
        return None
    receipt = {
        "called_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bank": doc["bank"],
        "date": doc_date(doc).isoformat(),
        "doc_sha256": doc.get("sha256"),
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": prompt_sha,
        "model": MODEL,
        "model_response_version": getattr(response, "model", MODEL),
        "raw_response": raw,
        **parsed,
    }
    _append_jsonl(receipts_path, receipt)
    return parsed


def main() -> None:
    """Print the gate with the real counts; score post-deploy statements only if it is open."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Stage 2 LLM hawkishness (gated, live-only)")
    ap.add_argument("--effect-ok", action="store_true", help="the agreed event-study verdict")
    args = ap.parse_args()  # deliberately no --force: the gate cannot be bypassed from the CLI
    counts = live_counts()
    gate = gate_status(counts, effect_ok=args.effect_ok)
    print(json.dumps(gate, indent=1))
    if not gate["open"]:
        print("gate CLOSED — nothing scored (see docs/stage2-decision.md)")
        return
    docs = [d for d in load_docs() if doc_date(d) >= DEPLOY_DATE]
    for doc in docs:
        try:
            res = score_live(doc, gate=gate)
        except LiveOnlyError as exc:  # cannot happen after the filter above; belt and braces
            print(exc)
            continue
        print(doc["bank"], doc_date(doc), res)


if __name__ == "__main__":
    main()
