"""Aggregated page renderers.

`main.py` imports these callables and registers them with `st.Page`. Each
page module owns its own rendering logic; this package __init__ provides a
single import surface.
"""

from __future__ import annotations

from .market import render_chain_strategy

__all__ = ["render_chain_strategy"]
