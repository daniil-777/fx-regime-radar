"""The avatar's MIND: one small context pack of everything the app currently believes.

Rebuilt by the daily pipeline into `data/avatar_context.json` (~2–4k tokens). The real-time
presenter (rust `/avatar/*`) answers ONLY from this pack plus the static knowledge pack
(`docs/avatar_knowledge.md`) — it has no other memory and no market opinions. Three properties are
enforced here, in Python, where they are testable:

* PARITY   — every number in the pack equals the source artifact exactly (tested);
* LINT     — every SPOKEN template (greeting, disclosure, refusals, FAQ answers) passes the
             rule-5 direction-word lint (`narrate.check_narration`);
* GROUNDING — the pack carries `allowed_numbers`, the closed set of numeric tokens the presenter
             may ever speak; the rust gate rejects any answer containing a number outside it.

The greeting is generated HERE, as a deterministic template over the day's real numbers, so the
first sentence of every session is app state, not model prose — and it always begins with the
disclosure clause (EU AI Act Art. 50: the user is told they are talking to an AI).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from fxradar import config, narrate, universes

log = logging.getLogger(__name__)

CONTEXT_PATH = config.DATA_DIR / "avatar_context.json"
KNOWLEDGE_PATH = config.DOCS_DIR / "avatar_knowledge.md"
SYSTEM_PROMPT_VERSION = "v1"

DISCLOSURE = (
    "A quick note before we start: I am the radar's AI presenter — a computer-generated voice "
    "and face, not a person. I only describe what the radar has published today."
)

# Spoken refusal templates (rule 5 / rule 7 relocated to the mouth): each names what we CAN say.
REFUSALS = {
    "direction": (
        "That asks which way the price will move, and this radar never models direction — "
        "in any market, mine included. What I can tell you is the current regime, how likely it "
        "is to change within five trading days, and how unusual today looks against calm history."
    ),
    "advice": (
        "I can't help with personal investment decisions — this is an educational tool, not "
        "investment advice. What I can give you is the published risk picture: the regime, the "
        "change risk with its band, the siren, and how well those numbers have held up on the "
        "public ledger."
    ),
    "off_topic": (
        "That's outside what I know — I only speak from the radar's published numbers and its "
        "methodology notes. Ask me about the current conditions, the models, the live record, "
        "or how to verify it yourself."
    ),
    "not_in_pack": (
        "I don't have that number in today's published state, and I'm not allowed to guess. "
        "The dashboard and the proof page carry everything the radar knows today."
    ),
}

NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


# --------------------------------------------------------------------------------------
# building the pack
# --------------------------------------------------------------------------------------
def _num(value, nd=2):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return round(float(value), nd)


def _pair_block(row: pd.Series, universe) -> dict:
    return {
        "label": universe.display(str(row["pair"])),
        "regime": str(row["regime"]),
        "regime_prob": _num(row["regime_prob"]),
        "days_in_regime": int(row["days_in_regime"]),
        "change_risk_5d": _num(row.get("change_risk_5d")),
        "risk_lo": _num(row.get("risk_lo")),
        "risk_hi": _num(row.get("risk_hi")),
        "anomaly_pct": _num(row.get("anomaly_pct"), 0),
        "agreement": int(row["agreement"]) if pd.notna(row.get("agreement")) else None,
        "consensus_text": (
            str(row.get("consensus_text")) if pd.notna(row.get("consensus_text")) else None
        ),
    }


def read_market_frames() -> dict[str, pd.DataFrame]:
    """I/O edge: the latest regimes frame for every universe with artifacts on disk."""
    frames: dict[str, pd.DataFrame] = {}
    for name, uni in universes.UNIVERSES.items():
        base = config.DATA_DIR / uni.subdir if uni.subdir else config.DATA_DIR
        path = base / "regimes.parquet"
        if path.exists():
            frames[name] = pd.read_parquet(path)
    return frames


def _markets_block(frames: dict[str, pd.DataFrame]) -> dict:
    """The presenter's whole map: per universe, the latest block for every pair it tracks.
    Same fields as the majors' blocks, so one grounding rule covers the lot."""
    out: dict = {}
    for name, df in frames.items():
        uni = universes.get(name)
        latest = df.sort_values("date").groupby("pair").tail(1)
        out[name] = {
            "label": uni.label,
            "data_through": f"{latest['date'].max():%Y-%m-%d}",
            "pairs": {str(r["pair"]): _pair_block(r, uni) for _, r in latest.iterrows()},
        }
    return out


def _events_block(events: pd.DataFrame, as_of: pd.Timestamp) -> list[dict]:
    if events is None or events.empty:
        return []
    nxt = events[events["date"] > as_of].sort_values("date").groupby("type").head(1)
    return [
        {
            "type": str(r["type"]),
            "date": f"{r['date']:%Y-%m-%d}",
            "days": int((r["date"] - as_of).days),
        }
        for _, r in nxt.sort_values("date").iterrows()
    ]


def _ledger_block(live: dict, coverage: dict) -> dict:
    m = live.get("metrics") or {}
    fz = live.get("frozen_test") or {}
    cov_live = (coverage.get("live") or {}).get("coverage")
    cov_frozen = (coverage.get("frozen_test") or {}).get("overall")
    head = str(live.get("head_hash", ""))
    return {
        "days_live": int(live.get("days_recorded", 0) or 0),
        "n_forecasts": int(live.get("n_forecasts", 0) or 0),
        "n_resolved": int(live.get("n_resolved", 0) or 0),
        "since": live.get("since"),
        "live_brier": _num(m.get("brier"), 3),
        "frozen_brier": _num(fz.get("brier"), 3),
        "frozen_pr_auc": _num(fz.get("pr_auc"), 3),
        "coverage_live": _num(cov_live, 3),
        "coverage_frozen": _num(cov_frozen, 3),
        "chain_head_short": head[:8] if head else None,
        "chain_ok": bool(live.get("chain_ok", False)),
    }


def parse_faq(md_text: str) -> list[dict]:
    """`### Q: ...` blocks of the knowledge pack → [{q, keywords, answer}] for the keyless
    fallback matcher. Answers are the SPOKEN texts, so they are lint-checked here."""
    out = []
    for m in re.finditer(
        r"^### Q: (?P<q>.+?)\n(?P<a>.*?)(?=^### Q: |^## |\Z)", md_text, re.M | re.S
    ):
        q = m.group("q").strip()
        answer = " ".join(m.group("a").split())
        words = [w.lower().strip("?,.") for w in re.findall(r"[A-Za-z][A-Za-z-]+", q)]
        stop = {
            "what",
            "how",
            "does",
            "the",
            "is",
            "a",
            "an",
            "do",
            "you",
            "can",
            "i",
            "why",
            "are",
            "my",
            "it",
            "this",
        }
        out.append({"q": q, "keywords": [w for w in words if w not in stop], "answer": answer})
    return out


def build_greeting(
    pairs: dict, ledger: dict, data_through: str, universe, n_markets: int = 0
) -> str:
    """Deterministic, gated first words of every session — today's real numbers, then the offer."""
    markets_txt = (
        f" I also track the G10, emerging and crypto boards — {n_markets} markets in all."
        if n_markets > len(pairs)
        else ""
    )
    lead_key = next(iter(pairs))
    p = pairs[lead_key]
    band = (
        f"band {p['risk_lo']:.2f} to {p['risk_hi']:.2f}, "
        if p.get("risk_lo") is not None and p.get("risk_hi") is not None
        else ""
    )
    others = [f"{q['label']} {q['regime']}" for k, q in pairs.items() if k != lead_key]
    others_txt = f" Elsewhere: {', '.join(others)}." if others else ""
    record = (
        f" The forward test is on day {ledger['days_live']}, every forecast hash-chained before its outcome."
        if ledger.get("days_live")
        else ""
    )
    return (
        f"{DISCLOSURE} As of the {data_through} close, {p['label']} is {p['regime']} — "
        f"change risk {p['change_risk_5d']:.2f}, {band}siren {p['anomaly_pct']:.0f} of 100."
        f"{others_txt}{record}{markets_txt} Ask me anything about the radar."
    )


def canon(value: float | str) -> str:
    """Canonical spoken-number form shared with the rust gate: float, ≤4 dp, trailing zeros
    trimmed ('0.01', '73', '91.6'). The gate canonicalises every number it extracts the same way."""
    f = float(value)
    s = f"{f:.4f}".rstrip("0").rstrip(".")
    return s or "0"


def allowed_numbers(pack: dict, knowledge_text: str) -> list[str]:
    """The closed set of numeric tokens the presenter may speak: every number in the context pack
    (in raw, percent and 0–2 dp spoken forms) plus every number written in the knowledge pack."""
    tokens: set[str] = set()

    def add(value):
        if value is None or isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            f = float(value)
            forms = {f, round(f, 2), round(f, 1), round(f, 0)}
            if 0 <= f <= 1:  # probabilities are often spoken as percentages
                forms |= {round(f * 100, 1), round(f * 100, 0)}
            tokens.update(canon(v) for v in forms)
        elif isinstance(value, str):
            tokens.update(canon(t) for t in NUMBER_RE.findall(value))
        elif isinstance(value, dict):
            for v in value.values():
                add(v)
        elif isinstance(value, list):
            for v in value:
                add(v)

    add({k: v for k, v in pack.items() if k != "allowed_numbers"})
    tokens.update(canon(t) for t in NUMBER_RE.findall(knowledge_text))
    tokens.update({"0", "1", "2", "3", "4", "5"})  # voters 0–3, five-day horizon, sentence counts
    return sorted(tokens)


def build_pack(
    regimes: pd.DataFrame,
    events: pd.DataFrame | None,
    treasury: dict | None,
    live: dict,
    coverage: dict,
    status: dict,
    knowledge_text: str,
    universe=None,
    now_utc: str | None = None,
    market_frames: dict[str, pd.DataFrame] | None = None,
) -> dict:
    universe = universe or config.UNIVERSE
    latest = regimes.sort_values("date").groupby("pair").tail(1)
    as_of = latest["date"].max()
    pairs = {str(r["pair"]): _pair_block(r, universe) for _, r in latest.iterrows()}
    ledger = _ledger_block(live or {}, coverage or {})
    tre = {
        p: {"light": t.get("light"), "reason": t.get("light_reason")}
        for p, t in ((treasury or {}).get("pairs") or {}).items()
    }
    pack = {
        "generated_at_utc": now_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "universe": universe.name,
        "data_through": f"{as_of:%Y-%m-%d}",
        "system_prompt_version": SYSTEM_PROMPT_VERSION,
        "disclosure": DISCLOSURE,
        "pairs": pairs,
        "events": _events_block(events, as_of),
        "treasury": tre,
        "ledger": ledger,
        "drift": {"model_stale": bool((status or {}).get("model_stale", False))},
        "refusals": REFUSALS,
        "faq": parse_faq(knowledge_text),
        "knowledge_pack": str(KNOWLEDGE_PATH.relative_to(config.ROOT)),
    }
    markets = _markets_block(market_frames or {})
    if markets:
        pack["markets"] = markets
    n_markets = sum(len(u["pairs"]) for u in markets.values())
    pack["greeting"] = build_greeting(pairs, ledger, pack["data_through"], universe, n_markets)
    # gate every spoken template at build time — the pack refuses to exist with direction words
    for text in [
        pack["greeting"],
        DISCLOSURE,
        *REFUSALS.values(),
        *(f["answer"] for f in pack["faq"]),
    ]:
        narrate.check_narration(text)
    pack["allowed_numbers"] = allowed_numbers(pack, knowledge_text)
    return pack


# --------------------------------------------------------------------------------------
# pipeline stage + CLI
# --------------------------------------------------------------------------------------
def _read_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _read_events() -> pd.DataFrame | None:
    path = config.DATA_DIR / "events.csv"
    if not path.exists():
        path = config.ROOT / "data" / "events.csv"  # macro calendar is shared across FX universes
    if not path.exists():
        return None
    ev = pd.read_csv(path)
    ev["date"] = pd.to_datetime(ev["date"])
    return ev


def stage(ctx: dict) -> None:
    """run_daily stage: rebuild the pack from the freshly scored state (writers run in `write`)."""
    knowledge = KNOWLEDGE_PATH.read_text() if KNOWLEDGE_PATH.exists() else ""
    pack = build_pack(
        ctx["regimes"],
        _read_events(),
        _read_json(config.DATA_DIR / "treasury_risk.json"),
        ctx.get("live_record") or _read_json(config.DATA_DIR / "live_record.json"),
        _read_json(config.DATA_DIR / "conformal_coverage.json"),
        ctx.get("status") or _read_json(config.DATA_DIR / "status.json"),
        knowledge,
        market_frames=read_market_frames() if config.UNIVERSE.name == "fx" else None,
    )
    ctx["avatar_context"] = pack
    ctx.setdefault("extra_writers", {})["avatar_context.json"] = lambda c: CONTEXT_PATH.write_text(
        json.dumps(c["avatar_context"], indent=1, ensure_ascii=False)
    )
    log.info(
        "avatar mind: %d pairs, %d events, %d faq entries, %d allowed numbers",
        len(pack["pairs"]),
        len(pack["events"]),
        len(pack["faq"]),
        len(pack["allowed_numbers"]),
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    regimes = pd.read_parquet(config.REGIMES_PATH)
    knowledge = KNOWLEDGE_PATH.read_text() if KNOWLEDGE_PATH.exists() else ""
    pack = build_pack(
        regimes,
        _read_events(),
        _read_json(config.DATA_DIR / "treasury_risk.json"),
        _read_json(config.DATA_DIR / "live_record.json"),
        _read_json(config.DATA_DIR / "conformal_coverage.json"),
        _read_json(config.DATA_DIR / "status.json"),
        knowledge,
        market_frames=read_market_frames() if config.UNIVERSE.name == "fx" else None,
    )
    CONTEXT_PATH.write_text(json.dumps(pack, indent=1, ensure_ascii=False))
    print(f"wrote {CONTEXT_PATH}")
    print("greeting:", pack["greeting"])


if __name__ == "__main__":
    main()
