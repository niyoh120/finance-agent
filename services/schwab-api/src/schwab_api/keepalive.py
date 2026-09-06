"""Rotation-aware keepalive: refresh tokens on a schedule and reset their 7-day clock.

schwabdev 4.x rotates the refresh token on every refresh but keeps
``refresh_token_issued`` at the original authorization time, so the stored token
hard-expires 7 days after first login no matter how often it was refreshed. The
keepalive loop refreshes via the ``refresh_token`` grant on its own schedule and
writes the rotated token back with *both* issue timestamps set to now.

Concurrency: the token-endpoint HTTP call happens inside the store's EXCLUSIVE
transaction — the same pattern schwabdev uses — so refreshes are serialized
across every process sharing the tokens database, and the always-latest refresh
token is the one that gets rotated.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import logging
import sqlite3

import requests

from .auth import SchwabTokenError, request_tokens_by_refresh_token
from .config import Config
from .store import TokenRow, TokenStore, now_utc

logger = logging.getLogger(__name__)

INITIAL_BACKOFF_SECONDS = 60.0
MAX_BACKOFF_SECONDS = 3600.0


class RuntimeState:
    """Mutable operational state surfaced by ``GET /api/v1/status``."""

    def __init__(self) -> None:
        self.last_refresh: datetime.datetime | None = None
        self.last_attempt: datetime.datetime | None = None
        self.last_error: str | None = None


class KeepaliveError(Exception):
    """A rotation attempt failed; the previous tokens remain stored."""


def due_for_refresh(row: TokenRow | None, interval_hours: float, now: datetime.datetime) -> bool:
    """A rotation is due when tokens exist and our last rotation is older than the interval."""
    if row is None:
        return False
    return (now - row.refresh_token_issued).total_seconds() >= interval_hours * 3600


def run_once(store: TokenStore, config: Config, runtime: RuntimeState) -> bool:
    """Attempt a single rotation. Returns True when tokens were rotated.

    The EXCLUSIVE transaction covers read -> HTTP -> write; any failure rolls
    back and leaves the previous row intact.
    """
    runtime.last_attempt = now_utc()
    with store.exclusive() as conn:
        row = store.read_conn(conn)
        if not due_for_refresh(row, config.keepalive_interval_hours, runtime.last_attempt):
            return False
        try:
            tokens = request_tokens_by_refresh_token(config, row.refresh_token)
        except (SchwabTokenError, requests.RequestException, ValueError) as e:
            runtime.last_error = f"refresh-token rotation failed: {e}"
            raise KeepaliveError(runtime.last_error) from e
        # Both issue timestamps reset: this is the fix for schwabdev keeping
        # refresh_token_issued at the original authorization time.
        store.write_conn(conn, TokenRow.from_token_response(tokens, previous=row, issued=now_utc()))
    return True


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)


async def run_loop(store: TokenStore, config: Config, runtime: RuntimeState, stop: asyncio.Event) -> None:
    """Keepalive loop: rotate when due, back off on failures, exit on ``stop``."""
    interval_seconds = config.keepalive_interval_hours * 3600
    backoff = min(INITIAL_BACKOFF_SECONDS, interval_seconds)
    while not stop.is_set():
        try:
            if await asyncio.to_thread(run_once, store, config, runtime):
                runtime.last_refresh = runtime.last_attempt
                runtime.last_error = None
                logger.info("keepalive: refresh token rotated, 7-day clock reset")
            backoff = min(INITIAL_BACKOFF_SECONDS, interval_seconds)
        except (KeepaliveError, sqlite3.OperationalError) as e:
            runtime.last_error = str(e)
            logger.error("keepalive: %s; retrying in %.0fs", e, backoff)
            await _sleep_or_stop(stop, backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS, interval_seconds)
            continue
        await _sleep_or_stop(stop, interval_seconds)
