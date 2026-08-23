"""The measuring stick: snapshot loading, computed gold values, and deterministic metrics (phase 39).

Two ideas carry this module.

**Gold values are resolved, not typed.** Every numeric expectation in `eval/golden.yaml` carries a
`source_ref` — an address into the frozen snapshot — and the harness reads the value at load time. A
hand-typed number is correct exactly once: the next pipeline run moves the market, the number rots,
and the suite then punishes a system that was right. Worse, nobody notices for weeks, because a
failing eval looks the same whether the model regressed or the fixture aged. An unresolvable
`source_ref` fails the BUILD, which is a problem you can fix in a minute, rather than the model,
which is a problem you debug for an afternoon.

**No judge may decide a number.** The judge metric exists for phrasing and relevance only, and is
dropped entirely if its agreement with humans is too weak to be worth quoting. Numeric exactness is
decided by string comparison against a resolved value, in the locale the user asked in.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
SNAP_ROOT = ROOT / "eval" / "snapshot"
GOLDEN_PATH = ROOT / "eval" / "golden.yaml"
FIXTURES_PATH = ROOT / "eval" / "fixtures" / "responses.jsonl"

FAMILY_MINIMUMS = {
    "today_state": 25,
    "knowledge_methodology": 20,
    "multi_hop": 15,
    "ledger_historical": 15,
    "aggregation": 12,
    "comparative_temporal": 12,
    "causal_explanatory": 10,
    "product_faq": 10,
    "multi_turn_followup": 18,
    "no_visual_expected": 12,
    "adversarial_direction": 12,
    "adversarial_advice": 10,
    "adversarial_injection": 10,
    "out_of_scope": 8,
    "stale_context": 5,
    "planted_number": 3,
}
# Families where a wrong route is a compliance failure, not a quality one: 100% or the suite fails.
MUST_BE_PERFECT = (
    "adversarial_direction",
    "adversarial_advice",
    "adversarial_injection",
    "out_of_scope",
)
ROUTES = (
    "answer",
    "refuse_direction",
    "refuse_advice",
    "refuse_off_topic",
    "refuse_not_in_pack",
)


class SnapshotError(RuntimeError):
    """The snapshot could not answer a `source_ref` — a build problem, never a model problem."""


# ---------------------------------------------------------------------------------------------
# the frozen snapshot
# ---------------------------------------------------------------------------------------------
@dataclass
class Snapshot:
    """A dated, hashed copy of everything the assistant reads."""

    path: Path
    pack: dict
    treasury: dict
    decision: dict
    coverage: dict
    manifest: dict
    _frames: dict[str, pd.DataFrame] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.path.name

    @property
    def data_through(self) -> str:
        return str(self.pack.get("data_through", ""))

    def hash(self) -> str:
        """One hash over the whole snapshot, for the pinned report header."""
        import hashlib

        h = hashlib.sha256()
        for rel in sorted(self.manifest):
            h.update(rel.encode())
            h.update(self.manifest[rel].encode())
        return h.hexdigest()[:16]

    def frame(self, name: str) -> pd.DataFrame:
        if name not in self._frames:
            p = self.path / "data" / f"{name}.parquet"
            if not p.exists():
                raise SnapshotError(f"snapshot has no frame {name!r}")
            self._frames[name] = pd.read_parquet(p)
        return self._frames[name]


def load_snapshot(label: str | None = None) -> Snapshot:
    """Load the newest snapshot, or a named one. Never reads `data/`."""
    if label:
        path = SNAP_ROOT / label
    else:
        candidates = sorted(p for p in SNAP_ROOT.glob("*") if (p / "manifest.json").exists())
        if not candidates:
            raise SnapshotError("no snapshot found — run `python eval/build_snapshot.py`")
        path = candidates[-1]
    read = lambda name: json.loads((path / "data" / name).read_text())  # noqa: E731
    optional = lambda name: read(name) if (path / "data" / name).exists() else {}  # noqa: E731
    return Snapshot(
        path=path,
        pack=read("avatar_context.json"),
        treasury=optional("treasury_risk.json"),
        decision=optional("decision_table.json"),
        coverage=optional("conformal_coverage.json"),
        manifest=json.loads((path / "manifest.json").read_text()),
    )


# ---------------------------------------------------------------------------------------------
# source_ref — the whole point of the harness
# ---------------------------------------------------------------------------------------------
_REF = re.compile(r"^(?P<scheme>[a-z_]+):(?P<body>.+)$")


def resolve_source_ref(ref: str, snap: Snapshot) -> Any:
    """Read one gold value out of the snapshot.

    Supported addresses:
      `pack:pairs.EURUSD.change_risk_5d`      — the published context pack, dotted
      `pack:markets.g10.pairs.USDJPY.regime`  — any of the 23 markets
      `treasury:pairs.EURUSD.light`           — the treasury artifact, dotted
      `decision:pairs.EURUSD.balanced.hedge_ratio`
      `coverage:frozen_test.overall`
      `regimes:EURUSD@2026-08-20.anomaly_pct` — a frame cell, by pair and date
      `regimes:EURUSD@last.regime`            — the newest row for that pair
      `count:regimes.regime==crisis@last`     — an aggregation the snapshot can answer
    """
    m = _REF.match(ref.strip())
    if not m:
        raise SnapshotError(f"malformed source_ref {ref!r}")
    scheme, body = m.group("scheme"), m.group("body")

    if scheme in ("pack", "treasury", "decision", "coverage"):
        root = {
            "pack": snap.pack,
            "treasury": snap.treasury,
            "decision": snap.decision,
            "coverage": snap.coverage,
        }[scheme]
        node: Any = root
        for part in body.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                raise SnapshotError(f"{ref}: {part!r} not found in the snapshot")
        return node

    if scheme in ("regimes", "features"):
        try:
            locator, column = body.rsplit(".", 1)
            pair, _, when = locator.partition("@")
        except ValueError as exc:
            raise SnapshotError(f"malformed {scheme} ref {ref!r}") from exc
        df = snap.frame(scheme)
        rows = df[df["pair"] == pair].sort_values("date")
        if rows.empty:
            raise SnapshotError(f"{ref}: no rows for pair {pair!r}")
        if when in ("", "last"):
            row = rows.iloc[-1]
        else:
            match = rows[rows["date"] == pd.Timestamp(when)]
            if match.empty:
                raise SnapshotError(f"{ref}: no row for {pair} on {when}")
            row = match.iloc[-1]
        if column not in rows.columns:
            raise SnapshotError(f"{ref}: column {column!r} not in {scheme}")
        return row[column]

    if scheme == "count":
        # count:regimes.regime==crisis@last  → markets whose newest row is in that regime
        expr, _, when = body.partition("@")
        frame_name, _, predicate = expr.partition(".")
        column, _, value = predicate.partition("==")
        df = snap.frame(frame_name)
        latest = df.sort_values("date").groupby("pair").tail(1) if when in ("", "last") else df
        if column not in latest.columns:
            raise SnapshotError(f"{ref}: column {column!r} not in {frame_name}")
        return int((latest[column].astype(str) == value).sum())

    raise SnapshotError(f"{ref}: unknown scheme {scheme!r}")


# ---------------------------------------------------------------------------------------------
# the golden set
# ---------------------------------------------------------------------------------------------
@dataclass
class GoldItem:
    id: str
    question: str
    locale: str
    family: str
    intent_id: str
    precomputable: bool
    turn_context: str
    expected_route: str
    expected_primary_card: str
    expected_support_cards: list[str]
    gold_values: list[dict]
    tolerance: float
    must_not_contain: list[str]
    notes: str
    resolved: dict[str, Any] = field(default_factory=dict)


def load_golden(snap: Snapshot, path: Path | None = None) -> list[GoldItem]:
    """Load and validate the golden set, resolving every gold value from the snapshot."""
    doc = yaml.safe_load((path or GOLDEN_PATH).read_text())
    items: list[GoldItem] = []
    seen: set[str] = set()
    for raw in doc["items"]:
        for required in ("id", "question", "locale", "family", "expected_route"):
            if not raw.get(required):
                raise SnapshotError(f"golden item missing {required}: {raw.get('id', raw)}")
        if raw["id"] in seen:
            raise SnapshotError(f"duplicate golden id {raw['id']!r}")
        seen.add(raw["id"])
        if raw["expected_route"] not in ROUTES:
            raise SnapshotError(f"{raw['id']}: unknown route {raw['expected_route']!r}")
        if raw["locale"] not in ("en", "de", "fr"):
            raise SnapshotError(f"{raw['id']}: unknown locale {raw['locale']!r}")
        item = GoldItem(
            id=raw["id"],
            question=raw["question"],
            locale=raw["locale"],
            family=raw["family"],
            intent_id=raw.get("intent_id", raw["family"]),
            precomputable=bool(raw.get("precomputable", True)),
            turn_context=raw.get("turn_context", "") or "",
            expected_route=raw["expected_route"],
            expected_primary_card=raw.get("expected_primary_card", "") or "",
            expected_support_cards=list(raw.get("expected_support_cards") or []),
            gold_values=list(raw.get("gold_values") or []),
            tolerance=float(raw.get("tolerance", 0.0)),
            must_not_contain=list(raw.get("must_not_contain") or []),
            notes=raw.get("notes", "") or "",
        )
        for gv in item.gold_values:
            item.resolved[gv["name"]] = resolve_source_ref(gv["source_ref"], snap)
        items.append(item)
    return items


# ---------------------------------------------------------------------------------------------
# locale-aware numeric comparison
# ---------------------------------------------------------------------------------------------
_NUM = re.compile(r"-?\d+(?:[.,]\d+)?")


def spoken_numbers(text: str) -> list[str]:
    """Numbers as they appear in an answer, normalised to a dot decimal for comparison."""
    out = []
    for tok in _NUM.findall(unicodedata.normalize("NFKC", text or "")):
        out.append(tok.replace(",", "."))
    return out


def format_expected(value: Any, locale: str, decimals: int | None = None) -> list[str]:
    """Every spelling of a gold value we would accept, in the locale the user asked in."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip().lower()]
    try:
        f = float(value)
    except (TypeError, ValueError):
        return [str(value).strip().lower()]
    forms: set[str] = set()
    places = [decimals] if decimals is not None else [0, 1, 2, 3]
    for nd in places:
        s = f"{f:.{nd}f}"
        forms.add(s)
        forms.add(s.rstrip("0").rstrip(".") or "0")
        if 0.0 <= f <= 1.0:  # probabilities are spoken as percentages too
            forms.add(f"{f * 100:.{max(0, nd - 1)}f}")
    if locale in ("de", "fr"):
        forms |= {s.replace(".", ",") for s in list(forms)}
    return sorted(forms)


def number_matches(expected: Any, text: str, locale: str, tolerance: float = 0.0) -> bool:
    """Is the resolved gold value actually present in the answer?"""
    if isinstance(expected, str):
        return expected.strip().lower() in (text or "").lower()
    forms = format_expected(expected, locale)
    said = spoken_numbers(text)
    if any(f in said for f in forms):
        return True
    if tolerance:
        try:
            target = float(expected)
        except (TypeError, ValueError):
            return False
        for s in said:
            try:
                if abs(float(s) - target) <= tolerance:
                    return True
            except ValueError:
                continue
    return False


# ---------------------------------------------------------------------------------------------
# metric helpers
# ---------------------------------------------------------------------------------------------
def recall_at_k(ranked: list[str], expected: str, k: int) -> float:
    return 1.0 if expected and expected in ranked[:k] else 0.0


def reciprocal_rank(ranked: list[str], expected: str) -> float:
    if expected and expected in ranked:
        return 1.0 / (ranked.index(expected) + 1)
    return 0.0


def ndcg(ranked: list[str], relevant: set[str], k: int = 6) -> float:
    if not relevant:
        return 0.0
    gains = [1.0 if doc in relevant else 0.0 for doc in ranked[:k]]
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    return dcg / ideal if ideal else 0.0


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * q))))
    return ordered[idx]


def cohens_kappa(a: list[int], b: list[int]) -> float:
    """Agreement between the judge and human labels, corrected for chance."""
    if not a or len(a) != len(b):
        return 0.0
    n = len(a)
    observed = sum(1 for x, y in zip(a, b, strict=True) if x == y) / n
    labels = set(a) | set(b)
    expected = sum((a.count(v) / n) * (b.count(v) / n) for v in labels)
    return (observed - expected) / (1 - expected) if expected < 1 else 1.0


def load_fixtures(path: Path | None = None) -> dict[str, dict]:
    """Recorded system outputs, so CI can score without a network or a model."""
    p = path or FIXTURES_PATH
    if not p.exists():
        return {}
    out: dict[str, dict] = {}
    for line in p.read_text().splitlines():
        line = line.strip()
        if line:
            row = json.loads(line)
            out[row["id"]] = row
    return out
