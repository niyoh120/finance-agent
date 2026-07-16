"""Thin Streamlit entrypoint.

``streamlit run app.py`` and Streamlit ``AppTest.from_file`` both execute this
file as a top-level script (no parent package), so it must use absolute imports
and delegate to :mod:`options_dashboard.main`.
"""

from __future__ import annotations

from options_dashboard.main import main

if __name__ == "__main__":
    main()
