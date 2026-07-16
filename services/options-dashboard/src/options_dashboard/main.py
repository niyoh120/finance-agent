"""Streamlit entrypoint.

Run with: ``streamlit run src/options_dashboard/main.py``

Sets up ``st.navigation`` over the pages and initializes the shared Session
State. Pages are registered as callables (not file paths) so the whole
dashboard lives in one importable package; this also makes ``AppTest``-based
render tests straightforward.
"""

from __future__ import annotations

import streamlit as st

from .pages import render_chain_strategy
from .state import init_state


def main() -> None:
    # set_page_config must be the FIRST Streamlit command in the script.
    st.set_page_config(
        page_title="期权交易辅助面板",
        page_icon="📈",
        layout="wide",
    )

    init_state()

    pg = st.navigation(
        [
            st.Page(render_chain_strategy, title="期权策略", url_path="strategy", default=True),
        ]
    )
    pg.run()


if __name__ == "__main__":
    main()
