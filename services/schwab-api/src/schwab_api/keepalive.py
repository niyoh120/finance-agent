"""Rotation-aware keepalive: present the refresh token inside Schwab's idle window.

实测（2026-09）：Schwab 的 refresh token 存在 ≈ access_token TTL（~30min）的空闲窗口
—— 距上次刷新超过窗口后再用，token 端点直接返回 400 ``invalid_grant``（整条链已死，
只能重新走 authorization_code 授权）；窗口内刷新则链持续保温。因此保活周期必须严格
短于窗口（默认/上限 0.4h，见 config.MAX_KEEPALIVE_INTERVAL_HOURS），这取代了早期
“12h 周期即可续 7 天命”的错误模型。7 天绝对死线是否存在仍待观察：若 0.4h 保温仍
跨不过授权后第 7 天，需叠加定期重授权。

schwabdev 4.x 仍有两个问题由本服务接手：其按需刷新只在 access token 过期后才发起
（必然落在窗口外），且 ``refresh_token_issued`` 记账停留在首次授权时刻。保活循环
周期性地用 ``refresh_token`` grant 刷新并把双 issued 时间戳重置为 now。

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
        #: Schwab 以 invalid_grant 拒绝 refresh token（链已死）后置位；
        #: 重新 authorization_code 授权成功后由 auth.exchange_and_store 复位。
        self.chain_dead: bool = False


class KeepaliveError(Exception):
    """A transient rotation failure; the previous tokens remain stored."""

    def __init__(self, message: str, *, possible_rotation: bool = False) -> None:
        super().__init__(message)
        #: True when the HTTP call timed out after the request may have reached
        #: Schwab — the server may already hold a newer token than the store,
        #: so the loop backs off a full interval instead of retrying immediately.
        self.possible_rotation = possible_rotation


class ChainDeadError(KeepaliveError):
    """Schwab rejected the refresh token with invalid_grant: the rotation chain
    is dead. Retrying is pointless — only re-authorization (UI auth flow) fixes
    it; ``exchange_and_store`` resets ``RuntimeState.chain_dead`` on success."""


def due_for_refresh(row: TokenRow | None, interval_hours: float, now: datetime.datetime) -> bool:
    """A rotation is due when tokens exist and our last rotation is older than the interval."""
    if row is None:
        return False
    return (now - row.refresh_token_issued).total_seconds() >= interval_hours * 3600


def run_once(store: TokenStore, config: Config, runtime: RuntimeState) -> bool:
    """Attempt a single rotation. Returns True when tokens were rotated.

    The EXCLUSIVE transaction covers read -> HTTP -> write; any failure rolls
    back and leaves the previous row intact.

    Raises:
        ChainDeadError: Schwab rejected the refresh token (invalid_grant) —
            the chain is dead and ``runtime.chain_dead`` is set; only
            re-authorization fixes it, so callers should stop retrying.
        KeepaliveError: transient failure (network/5xx/malformed response).
    """
    if runtime.chain_dead:
        # 链已死后循环保持空转（等重授权复位），避免持续敲已死 token 的墓碑。
        return False
    runtime.last_attempt = now_utc()
    with store.exclusive() as conn:
        row = store.read_conn(conn)
        if not due_for_refresh(row, config.keepalive_interval_hours, runtime.last_attempt):
            return False
        try:
            tokens = request_tokens_by_refresh_token(config, row.refresh_token)
        except (SchwabTokenError, requests.RequestException, ValueError) as e:
            if isinstance(e, SchwabTokenError) and e.invalid_grant:
                runtime.chain_dead = True
                runtime.last_error = f"refresh token rejected by Schwab (chain dead, re-authorization required): {e}"
                raise ChainDeadError(runtime.last_error) from e
            possible_rotation = isinstance(e, requests.Timeout)
            runtime.last_error = f"refresh-token rotation failed: {e}"
            raise KeepaliveError(runtime.last_error, possible_rotation=possible_rotation) from e
        # Both issue timestamps reset: this is the fix for schwabdev keeping
        # refresh_token_issued at the original authorization time.
        store.write_conn(conn, TokenRow.from_token_response(tokens, previous=row, issued=now_utc()))
    return True


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)


async def run_loop(store: TokenStore, config: Config, runtime: RuntimeState, stop: asyncio.Event) -> None:
    """Keepalive loop: rotate when due, back off on transient failures, idle when
    the chain is dead (re-authorization resets ``runtime.chain_dead``), exit on
    ``stop``."""
    interval_seconds = config.keepalive_interval_hours * 3600
    backoff = min(INITIAL_BACKOFF_SECONDS, interval_seconds)
    while not stop.is_set():
        try:
            if await asyncio.to_thread(run_once, store, config, runtime):
                runtime.last_refresh = runtime.last_attempt
                runtime.last_error = None
                logger.info("keepalive: refresh token rotated")
            backoff = min(INITIAL_BACKOFF_SECONDS, interval_seconds)
        except ChainDeadError as e:
            # 链已死：停止退避重试，空转等待 UI 重授权（exchange_and_store 复位 chain_dead）。
            logger.error("keepalive: %s; idling until re-authorization", e)
            backoff = min(INITIAL_BACKOFF_SECONDS, interval_seconds)
            await _sleep_or_stop(stop, interval_seconds)
            continue
        except (KeepaliveError, sqlite3.OperationalError) as e:
            runtime.last_error = str(e)
            # 超时意味着服务端可能已完成轮换而响应丢失：旧 token 复用有风险，
            # 拉满一个完整周期再试，而非 60s 指数退避快速连打。
            wait = backoff
            if isinstance(e, KeepaliveError) and e.possible_rotation:
                wait = max(backoff, interval_seconds)
            logger.error("keepalive: %s; retrying in %.0fs", e, wait)
            await _sleep_or_stop(stop, wait)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS, interval_seconds)
            continue
        await _sleep_or_stop(stop, interval_seconds)
