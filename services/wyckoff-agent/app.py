"""Chainlit entrypoint.

Run:
  chainlit run app.py -w

This file exists to avoid relative-import issues when Chainlit loads a file as a module.
"""

from wyckoff_agent.app import *  # noqa: F403
