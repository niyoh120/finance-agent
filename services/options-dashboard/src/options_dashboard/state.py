"""Dashboard-wide Session State helpers.

Centralizes initialization of the state keys used across all pages so the
entrypoint can call :func:`init_state` once per session. Keeps keys in one place
to avoid scattered string literals and to make the state contract explicit.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

# Session State keys. Values are intentionally simple: this dashboard has no
# database, so state lives only for the browser session.
SYMBOL_KEY = "od_symbol"
STRATEGY_LEGS_KEY = "od_strategy_legs"


def init_state() -> None:
    """Initialize dashboard Session State with defaults (idempotent)."""
    # No default symbol: pages only fetch after the user explicitly submits one.
    st.session_state.setdefault(SYMBOL_KEY, "")
    st.session_state.setdefault(STRATEGY_LEGS_KEY, [])


def get_strategy_legs() -> list[dict[str, Any]]:
    raw: Any = st.session_state.get(STRATEGY_LEGS_KEY, [])
    return list(raw)
