"""Keepalive rotation semantics — the core regression for schwabdev's 7-day expiry bug."""

from __future__ import annotations

import asyncio
import datetime

import pytest
from conftest import make_config, make_row
from schwab_api import keepalive as keepalive_module
from schwab_api.auth import SchwabTokenError
from schwab_api.keepalive import KeepaliveError, RuntimeState, run_loop, run_once

REFRESH_RESPONSE = {
    "access_token": "at-new",
    "refresh_token": "rt-new",
    "id_token": "id-new",
    "expires_in": 1800,
    "token_type": "Bearer",
    "scope": "api",
}


class FakeTransport:
    """Stands in for the Schwab token endpoint; records the refresh token used."""

    def __init__(self, ok: bool = True):
        self.ok = ok
        self.calls: list[str] = []

    def __call__(self, config, refresh_token: str) -> dict:
        self.calls.append(refresh_token)
        if not self.ok:
            raise SchwabTokenError(401, '{"error":"invalid_grant"}')
        return dict(REFRESH_RESPONSE)


@pytest.fixture()
def transport(monkeypatch):
    fake = FakeTransport()
    monkeypatch.setattr(keepalive_module, "request_tokens_by_refresh_token", fake)
    return fake


def hours_ago(hours: float) -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)


# ---- rotation success --------------------------------------------------------


def test_rotation_updates_tokens_and_resets_both_timestamps(store, transport):
    """Core regression: after rotation, refresh_token_issued == now.

    schwabdev keeps refresh_token_issued at the original auth time; if this test
    ever fails, the 7-day forced re-auth is back.
    """
    config = make_config()
    original = make_row(issued=hours_ago(13))
    store.write(original)
    runtime = RuntimeState()

    rotated = run_once(store, config, runtime)

    assert rotated is True
    assert transport.calls == ["refresh-456"]  # rotated the DB-latest refresh token

    row = store.read()
    now = datetime.datetime.now(datetime.timezone.utc)
    assert row.refresh_token == "rt-new"
    assert row.access_token == "at-new"
    assert abs((now - row.refresh_token_issued).total_seconds()) < 30
    assert abs((now - row.access_token_issued).total_seconds()) < 30

    assert runtime.last_attempt is not None
    assert runtime.last_error is None


def test_rotation_skips_when_refreshed_within_interval(store, transport):
    config = make_config(keepalive_interval_hours=12.0)
    original = make_row(issued=hours_ago(1))
    store.write(original)

    assert run_once(store, config, RuntimeState()) is False
    assert transport.calls == []
    assert store.read().refresh_token == original.refresh_token


def test_rotation_skips_when_no_tokens_stored(store, transport):
    assert run_once(store, make_config(), RuntimeState()) is False
    assert transport.calls == []


def test_rotation_uses_configurable_interval(store, transport):
    config = make_config(keepalive_interval_hours=1.0)
    store.write(make_row(issued=hours_ago(2)))
    assert run_once(store, config, RuntimeState()) is True


# ---- rotation failure --------------------------------------------------------


def test_failure_keeps_old_tokens_and_records_error(store, monkeypatch):
    """A failed endpoint call must roll back: the previous row stays intact."""
    config = make_config()
    original = make_row(issued=hours_ago(13))
    store.write(original)
    runtime = RuntimeState()

    monkeypatch.setattr(keepalive_module, "request_tokens_by_refresh_token", FakeTransport(ok=False))
    with pytest.raises(KeepaliveError, match="rotation failed"):
        run_once(store, config, runtime)

    row = store.read()
    assert row == original  # old refresh token preserved (rollback)
    assert runtime.last_error is not None
    assert "invalid_grant" in runtime.last_error
    assert runtime.last_refresh is None


def test_network_failure_keeps_old_tokens(store, monkeypatch):
    import requests as requests_lib

    original = make_row(issued=hours_ago(13))
    store.write(original)

    def timeout(config, refresh_token):
        raise requests_lib.ConnectionError("boom")

    monkeypatch.setattr(keepalive_module, "request_tokens_by_refresh_token", timeout)
    with pytest.raises(KeepaliveError, match="rotation failed"):
        run_once(store, make_config(), RuntimeState())
    assert store.read() == original


# ---- asyncio loop wiring -----------------------------------------------------


def test_loop_rotates_then_stops_cleanly(store, transport):
    """The lifespan task: rotates once when due, records success, exits on stop."""
    config = make_config(keepalive_interval_hours=0.001)  # ~3.6s cadence for the smoke test
    store.write(make_row(issued=hours_ago(1)))
    runtime = RuntimeState()

    async def scenario():
        stop = asyncio.Event()
        task = asyncio.create_task(run_loop(store, config, runtime, stop))
        for _ in range(100):
            if runtime.last_refresh is not None:
                break
            await asyncio.sleep(0.02)
        stop.set()
        await asyncio.wait_for(task, timeout=5)

    asyncio.run(scenario())

    assert runtime.last_refresh is not None
    assert runtime.last_error is None
    row = store.read()
    assert row.refresh_token == "rt-new"
    assert transport.calls == ["refresh-456"]


def test_loop_backs_off_on_failure_without_losing_tokens(store, monkeypatch):
    config = make_config(keepalive_interval_hours=0.001)
    original = make_row(issued=hours_ago(1))
    store.write(original)
    runtime = RuntimeState()

    monkeypatch.setattr(keepalive_module, "request_tokens_by_refresh_token", FakeTransport(ok=False))

    async def scenario():
        stop = asyncio.Event()
        task = asyncio.create_task(run_loop(store, config, runtime, stop))
        for _ in range(100):
            if runtime.last_error is not None:
                break
            await asyncio.sleep(0.02)
        stop.set()
        await asyncio.wait_for(task, timeout=5)

    asyncio.run(scenario())

    assert runtime.last_error is not None
    assert runtime.last_refresh is None
    assert store.read() == original
