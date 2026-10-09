"""Keepalive rotation semantics — the core regression for schwabdev's 7-day expiry bug."""

from __future__ import annotations

import asyncio
import datetime

import pytest
from schwab_api import keepalive as keepalive_module
from schwab_api.auth import SchwabTokenError
from schwab_api.keepalive import ChainDeadError, KeepaliveError, RuntimeState, run_loop, run_once
from schwab_fakes import make_config, make_row

REFRESH_RESPONSE = {
    "access_token": "at-new",
    "refresh_token": "rt-new",
    "id_token": "id-new",
    "expires_in": 1800,
    "token_type": "Bearer",
    "scope": "api",
}

#: 用户生产环境抓到的真实报错形态：外层 unsupported_token_type 内嵌 invalid_grant。
INVALID_GRANT_BODY = (
    '{"error":"unsupported_token_type","error_description":'
    '"400 Bad Request: ""{"error_description":"Refresh token is invalid, expired or revoked",'
    '"error":"invalid_grant"}"""}'
)


class FakeTransport:
    """Stands in for the Schwab token endpoint; records the refresh token used."""

    def __init__(self, ok: bool = True, status_code: int = 401, body: str = '{"error":"invalid_grant"}'):
        self.ok = ok
        self.status_code = status_code
        self.body = body
        self.calls: list[str] = []

    def __call__(self, config, refresh_token: str) -> dict:
        self.calls.append(refresh_token)
        if not self.ok:
            raise SchwabTokenError(self.status_code, self.body)
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


def test_invalid_grant_marks_chain_dead_and_keeps_tokens(store, monkeypatch):
    """实测回归：空闲超窗后 Schwab 以 invalid_grant 拒绝（链已死）。

    必须快速失败：置 chain_dead、抛 ChainDeadError，旧 token 回滚保留，等重授权。
    """
    config = make_config()
    original = make_row(issued=hours_ago(13))
    store.write(original)
    runtime = RuntimeState()

    fake = FakeTransport(ok=False, status_code=400, body=INVALID_GRANT_BODY)
    monkeypatch.setattr(keepalive_module, "request_tokens_by_refresh_token", fake)
    with pytest.raises(ChainDeadError):
        run_once(store, config, runtime)

    assert runtime.chain_dead is True
    assert "chain dead" in runtime.last_error
    assert "invalid_grant" in runtime.last_error
    assert store.read() == original  # old refresh token preserved (rollback)


def test_run_once_short_circuits_when_chain_dead(store, transport):
    """链死亡后循环空转：不发起任何 token 端点请求。"""
    store.write(make_row(issued=hours_ago(13)))
    runtime = RuntimeState()
    runtime.chain_dead = True

    assert run_once(store, make_config(), runtime) is False
    assert transport.calls == []


def test_server_error_is_transient_not_chain_dead(store, monkeypatch):
    config = make_config()
    original = make_row(issued=hours_ago(13))
    store.write(original)
    runtime = RuntimeState()

    fake = FakeTransport(ok=False, status_code=500, body='{"error":"server_error"}')
    monkeypatch.setattr(keepalive_module, "request_tokens_by_refresh_token", fake)
    with pytest.raises(KeepaliveError, match="rotation failed"):
        run_once(store, config, runtime)

    assert runtime.chain_dead is False  # 5xx 是可重试的瞬时错误
    assert store.read() == original
    assert runtime.last_error is not None
    assert runtime.last_refresh is None


def test_timeout_flags_possible_rotation(store, monkeypatch):
    """超时后服务端可能已完成轮换：KeepaliveError 必须携带 possible_rotation。

    循环据此拉满一个完整周期再试，避免立即复用可能已被轮换掉的 token。
    """
    import requests as requests_lib

    store.write(make_row(issued=hours_ago(13)))
    runtime = RuntimeState()

    def timeout(config, refresh_token):
        raise requests_lib.Timeout("token endpoint timed out")

    monkeypatch.setattr(keepalive_module, "request_tokens_by_refresh_token", timeout)
    with pytest.raises(KeepaliveError) as excinfo:
        run_once(store, make_config(), runtime)
    assert excinfo.value.possible_rotation is True

    def connection_error(config, refresh_token):
        raise requests_lib.ConnectionError("boom")

    monkeypatch.setattr(keepalive_module, "request_tokens_by_refresh_token", connection_error)
    with pytest.raises(KeepaliveError) as excinfo:
        run_once(store, make_config(), RuntimeState())
    assert excinfo.value.possible_rotation is False


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


def test_loop_chain_death_stops_retrying_until_reauth(store, monkeypatch):
    """链死亡后循环停止重试：只打一次端点，等待重授权复位 chain_dead。"""
    config = make_config(keepalive_interval_hours=0.001)
    original = make_row(issued=hours_ago(1))
    store.write(original)
    runtime = RuntimeState()

    fake = FakeTransport(ok=False, status_code=400, body=INVALID_GRANT_BODY)
    monkeypatch.setattr(keepalive_module, "request_tokens_by_refresh_token", fake)

    async def scenario():
        stop = asyncio.Event()
        task = asyncio.create_task(run_loop(store, config, runtime, stop))
        for _ in range(100):
            if runtime.chain_dead:
                break
            await asyncio.sleep(0.02)
        assert runtime.chain_dead is True
        await asyncio.sleep(0.2)  # 给循环多个空转 tick 的机会
        stop.set()
        await asyncio.wait_for(task, timeout=5)

    asyncio.run(scenario())

    assert fake.calls == ["refresh-456"]  # 只尝试一次，无退避连打
    assert runtime.last_error is not None
    assert runtime.last_refresh is None
    assert store.read() == original

    # 模拟 UI 重授权成功：chain_dead 复位后 run_once 恢复正常工作
    runtime.chain_dead = False
    runtime.last_error = None
    fake_ok = FakeTransport(ok=True)
    monkeypatch.setattr(keepalive_module, "request_tokens_by_refresh_token", fake_ok)
    store.write(make_row(issued=hours_ago(1)))
    assert run_once(store, config, runtime) is True
    assert runtime.chain_dead is False
