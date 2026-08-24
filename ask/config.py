"""Ask configuration: pinned model, prompt version, endpoints, keys, paths.

Keys are env-only (Streamlit secrets on Community Cloud), reusing the narrator's pattern —
never committed, never logged.
"""

from __future__ import annotations

import os

from fxradar import config as fxconfig

# Pinned from the Token Factory documentation examples (small instruct model, OpenAI-compatible
# chat completions). The live eval records the id it actually ran with; if the catalogue rotates,
# `make ask-eval` fails fast with the server's message rather than guessing a replacement.
ASK_MODEL = "meta-llama/Meta-Llama-3.1-8B-Instruct-fast"
# The optional Anthropic lane (the narrator's SDK is already a dependency): used only when no
# NEBIUS_API_KEY exists but an ANTHROPIC_API_KEY does. Haiku is the classification tier.
ASK_MODEL_ANTHROPIC = "claude-haiku-4-5"
PROMPT_VERSION = "ask-route-v1"

NEBIUS_URL = "https://api.tokenfactory.nebius.com/v1/chat/completions"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"

MODEL_TIMEOUT_S = 4
SEARCH_TIMEOUT_S = 6
EXTRACT_TIMEOUT_S = 6

CACHE_DIR = fxconfig.DATA_DIR / "ask_cache"
LOG_PATH = fxconfig.DATA_DIR / "ask_log.jsonl"


def _key(name: str) -> str | None:
    """Env first, Streamlit secrets second (the narrator's pattern). None if absent."""
    value = os.environ.get(name)
    if value:
        return value
    try:  # pragma: no cover - st.secrets only exists under Streamlit
        import streamlit as st

        return st.secrets.get(name)  # type: ignore[no-any-return]
    except Exception:
        return None


def nebius_key() -> str | None:
    return _key("NEBIUS_API_KEY")


def tavily_key() -> str | None:
    return _key("TAVILY_API_KEY")


def anthropic_key() -> str | None:
    return _key("ANTHROPIC_API_KEY")
