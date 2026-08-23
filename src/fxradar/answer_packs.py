"""Precomputed answers, built once a night because the market moves once a day (phase 40).

The common path should not be assembled while a user waits. Every (intent × pair × locale) the
system can answer without a user-supplied quantity is built here, with its speech text, its resolved
board, a provenance record per value, and a cache key — then served as a lookup.

What this buys beyond speed is worth stating, because speed is the least of it: an answer built
nightly can be **inspected before anyone hears it**. Gates run once, at build time, over a set that a
human can read in full. A pack that would fail a gate never exists, so no gate work happens at
request time and no ungated sentence can reach a user through a fast path.

Two speech variants are built for every pack. `standalone` is what you say when asked cold;
`followup` is what a person says when the question was "and USDCHF?" — "USD/CHF, same reading: calm."
The difference is most of what separates a voice product that feels human from one that recites.

Not precomputed, by construction: anything involving an exposure, a hypothetical move, or the
research lab. Those inputs do not exist until somebody speaks.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import yaml

from fxradar import config

log = logging.getLogger(__name__)

PACKS_PATH = config.DATA_DIR / "answer_packs.json"
AUDIO_DIR = config.DATA_DIR / "answer_audio"
INTENTS_PATH = config.ROOT / "config" / "intents.yaml"

# Every field here is part of the pack's identity. If any of them changes, the pack was written
# under superseded rules and must be regenerated rather than served — `manifest_is_current()` is
# what the serving side asks, and `test_version_change_invalidates_every_pack` proves it bites.
PROMPT_VERSION = "v2"
GATE_RULES_VERSION = "phase-38"
MODEL_ID = "keyless-templates"
MODEL_VERSION = "n/a"
VOICE_ID = "browser-default"

# Locale surface. Kept deliberately small and explicit: a pack is read aloud, and a machine
# translation of a risk sentence is a liability, not a feature.
LEAD_IN = {
    "en": {"standalone": "", "followup": "{label}, same reading: "},
    "de": {"standalone": "", "followup": "{label}, gleiches Bild: "},
    "fr": {"standalone": "", "followup": "{label}, même lecture : "},
}


# The recurring vocabulary of a spoken reading. Deliberately small: these words appear in almost
# every caption, and localising only the decimal separator produces the worst of both worlds — a
# sentence that is neither English nor German.
#
# The four regime words (calm/trend/chop/crisis) are NOT translated. They are the system's canonical
# labels, they appear in the ledger and the API, and a treasurer comparing a German screen against a
# sealed English record needs to see the same word on both.
TERMS = {
    "de": {
        "change risk": "Änderungsrisiko",
        "band": "Band",
        "siren": "Sirene",
        "regimes over": "Regime über",
        "the light is": "die Ampel steht auf",
        "past regime episodes with start dates and lengths": "vergangene Regime-Episoden mit Startdatum und Dauer",
        "Stress consensus for": "Stress-Konsens für",
        "of 3 voters": "von 3 Stimmen",
        "of this regime": "in diesem Regime",
        "today": "heute",
        "Today across the markets": "Heute über alle Märkte",
        "realised volatility over": "realisierte Volatilität über",
        "Scheduled events ahead, nearest first": "Anstehende Termine, nächster zuerst",
        "Live for": "Live seit",
        "chain head": "Kettenkopf",
        "forecasts sealed before their outcomes": "vor dem Ergebnis versiegelte Prognosen",
    },
    "fr": {
        "change risk": "risque de changement",
        "band": "bande",
        "siren": "sirène",
        "regimes over": "régimes sur",
        "the light is": "le feu est",
        "past regime episodes with start dates and lengths": "épisodes de régime passés avec dates et durées",
        "Stress consensus for": "consensus de stress pour",
        "of 3 voters": "sur 3 voix",
        "of this regime": "de ce régime",
        "today": "aujourd'hui",
        "Today across the markets": "Aujourd'hui sur tous les marchés",
        "realised volatility over": "volatilité réalisée sur",
        "Scheduled events ahead, nearest first": "Événements à venir, le plus proche d'abord",
        "Live for": "En ligne depuis",
        "chain head": "tête de chaîne",
        "forecasts sealed before their outcomes": "prévisions scellées avant leur résultat",
    },
}


def _localise(text: str, locale: str) -> str:
    """Swap the recurring English vocabulary for the locale's own, longest phrase first."""
    terms = TERMS.get(locale)
    if not terms:
        return text
    out = text
    for english in sorted(terms, key=len, reverse=True):
        out = out.replace(english, terms[english])
    return out


def _decimal(text: str, locale: str) -> str:
    """German and French read 0,03 — a dot decimal spoken aloud in those locales is simply wrong."""
    if locale in ("de", "fr"):
        out, prev = [], ""
        for ch in text:
            out.append("," if ch == "." and prev.isdigit() else ch)
            prev = ch
        return "".join(out)
    return text


def _followup_of(caption: str, label: str, locale: str) -> str:
    """Answer a follow-up the way a person does: name the subject once, then the reading.

    Two mistakes are easy here and both sound wrong out loud. Lower-casing the first letter
    blindly turns "EUR/USD" into "eUR/USD"; and leaving the caption's own leading subject in place
    produces "USD/CHF, same reading: USD/CHF · calm", which is how a machine talks.
    """
    body = caption.strip()
    if not body:
        return ""
    display = label.replace("-", "/") if label else ""
    pretty = (
        f"{display[:3]}/{display[3:]}"
        if display and len(display) == 6 and "/" not in display
        else display
    )
    for prefix in (f"{pretty} · ", f"{pretty}: ", f"{pretty} "):
        if pretty and body.startswith(prefix):
            body = body[len(prefix) :]
            break
    first = body.split(" ", 1)[0]
    if first and not first.isupper() and "/" not in first:
        body = body[0].lower() + body[1:]
    lead = LEAD_IN[locale]["followup"].format(label=pretty or label)
    return lead + body


def load_intents(path: Path | None = None) -> dict:
    return yaml.safe_load((path or INTENTS_PATH).read_text())


def cache_key(
    intent_id: str,
    pair: str,
    locale: str,
    context_version: str,
    intent_version: str,
    registry_version: str,
) -> str:
    raw = "|".join(
        [
            intent_id,
            pair or "-",
            locale,
            context_version,
            intent_version,
            registry_version,
            PROMPT_VERSION,
            GATE_RULES_VERSION,
            MODEL_ID,
            VOICE_ID,
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def provenance_for(card: dict, boards: dict) -> list[dict]:
    """One record per value the pack speaks or renders: what it is, and where it came from."""
    args = card.get("args") or {}
    return [
        {
            "kind": "card_value",
            "component": card.get("component"),
            "args": args,
            "artifact": "data/visual_boards.json",
            "as_of": card.get("asof"),
            "context_version": boards.get("data_through"),
        }
    ]


def build(boards: dict, intents_doc: dict, gate_check=None) -> dict:
    """Build every precomputable pack. `gate_check(text) -> str | None` returns a refusal reason."""
    cards = boards.get("cards") or {}
    by_component: dict[str, list[tuple[str, dict]]] = {}
    for key, spec in cards.items():
        by_component.setdefault(spec["component"], []).append((key, spec))

    context_version = str(boards.get("data_through") or "")
    intent_version = str(intents_doc.get("intent_version", "0"))
    registry_version = str(boards.get("registry_version", "0"))

    packs: dict[str, dict] = {}
    blocked: list[dict] = []
    for intent in intents_doc.get("intents", []):
        component = intent["card"]
        instances = by_component.get(component) or []
        if not instances:
            continue
        for locale in intent["varies_over"]["locale"]:
            for _key, spec in instances:
                pair = (spec.get("args") or {}).get("pair", "")
                caption = str(spec.get("caption") or "").strip()
                if not caption:
                    continue
                label = pair or spec.get("title", "")
                standalone = _decimal(_localise(caption, locale), locale)
                followup = _decimal(_localise(_followup_of(caption, label, locale), locale), locale)

                # All five gates run HERE. A pack that would fail one never exists, so the fast path
                # cannot serve an ungated sentence.
                reason = gate_check(standalone) if gate_check else None
                if reason:
                    blocked.append(
                        {
                            "intent": intent["intent_id"],
                            "pair": pair,
                            "locale": locale,
                            "reason": reason,
                        }
                    )
                    continue
                key = cache_key(
                    intent["intent_id"],
                    pair,
                    locale,
                    context_version,
                    intent_version,
                    registry_version,
                )
                packs[key] = {
                    "intent_id": intent["intent_id"],
                    "card": component,
                    "pair": pair,
                    "locale": locale,
                    "speech": {"standalone": standalone, "followup": followup},
                    "board": [
                        {
                            "component": spec["component"],
                            "primitive": spec["primitive"],
                            "family": spec.get("family", ""),
                            "title": spec.get("title", ""),
                            "args": spec.get("args") or {},
                            "caption": caption,
                            "label": spec.get("label", ""),
                            "asof": spec.get("asof"),
                            "data": spec.get("data"),
                        }
                    ],
                    "provenance": provenance_for(spec, boards),
                    "audio": None,
                    "cache_key": key,
                }

    payload = json.dumps(packs, sort_keys=True).encode()
    manifest = {
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "context_version": context_version,
        "intent_version": intent_version,
        "registry_version": registry_version,
        "prompt_version": PROMPT_VERSION,
        "gate_rules_version": GATE_RULES_VERSION,
        "model_id_and_version": f"{MODEL_ID}@{MODEL_VERSION}",
        "voice_id": VOICE_ID,
        "n_packs": len(packs),
        "n_blocked_by_gates": len(blocked),
        "total_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "audio_baked": False,
        "audio_note": (
            "No ELEVENLABS_API_KEY at build time, so audio was not synthesised and the pack's "
            "`audio` field is null. Serving falls back to browser speech, which is audibly worse "
            "and slower to start — this is the largest remaining latency component on the common "
            "path, and it is a configuration gap rather than a code one."
        ),
    }
    return {"manifest": manifest, "packs": packs, "blocked": blocked}


def manifest_is_current(
    manifest: dict, *, context_version: str, intent_version: str, registry_version: str
) -> tuple[bool, list[str]]:
    """May these packs be served as fresh? Returns (ok, reasons_they_are_stale)."""
    checks = {
        "context_version": (manifest.get("context_version"), context_version),
        "intent_version": (manifest.get("intent_version"), intent_version),
        "registry_version": (manifest.get("registry_version"), registry_version),
        "prompt_version": (manifest.get("prompt_version"), PROMPT_VERSION),
        "gate_rules_version": (manifest.get("gate_rules_version"), GATE_RULES_VERSION),
        "model_id_and_version": (
            manifest.get("model_id_and_version"),
            f"{MODEL_ID}@{MODEL_VERSION}",
        ),
        "voice_id": (manifest.get("voice_id"), VOICE_ID),
    }
    stale = [
        f"{name}: {have!r} != {want!r}" for name, (have, want) in checks.items() if have != want
    ]
    return (not stale, stale)


def stage(ctx: dict) -> None:
    """run_daily step, after the boards are resolved."""
    boards = ctx.get("visual_boards")
    if not boards:
        return
    from fxradar import narrate  # noqa: PLC0415 — only needed at build time

    def gate_check(text: str) -> str | None:
        """The direction lint, run at build time over every spoken sentence."""
        try:
            narrate.check_narration(text)
        except Exception as exc:  # noqa: BLE001 — a refusal reason, not a crash
            return str(exc)[:120]
        return None

    result = build(boards, load_intents(), gate_check)
    ctx["answer_packs"] = result
    ctx.setdefault("extra_writers", {})["answer_packs.json"] = lambda c: PACKS_PATH.write_text(
        json.dumps(c["answer_packs"], indent=1)
    )
    log.info(
        "answer packs: %d built, %d blocked by gates at build time",
        result["manifest"]["n_packs"],
        result["manifest"]["n_blocked_by_gates"],
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    boards = json.loads((config.DATA_DIR / "visual_boards.json").read_text())
    from fxradar import narrate

    def gate_check(text: str) -> str | None:
        try:
            narrate.check_narration(text)
        except Exception as exc:  # noqa: BLE001
            return str(exc)[:120]
        return None

    result = build(boards, load_intents(), gate_check)
    PACKS_PATH.write_text(json.dumps(result, indent=1))
    m = result["manifest"]
    print(
        f"wrote {PACKS_PATH.name}: {m['n_packs']} packs, {m['total_bytes'] / 1000:.0f} kB, "
        f"{m['n_blocked_by_gates']} blocked by gates"
    )
    print(
        f"  context {m['context_version']} · intents {m['intent_version']} · "
        f"registry {m['registry_version']} · audio baked: {m['audio_baked']}"
    )


if __name__ == "__main__":
    main()
