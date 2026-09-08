"""服务配置（``FA_TDX_*`` 环境变量）。

模式沿用 services/schwab-api：frozen dataclass、启动时一次性构建、
非法值直接抛 ``ValueError``。默认监听 127.0.0.1:8011（Compose 内绑 0.0.0.0）。

资源预算默认值（批准计划推荐值，均可覆盖）：
- 连接 3 秒、单次读写 5 秒、请求总预算 30 秒
- 最多切换 2 个候选主机
- 并发上限 8、排队等待上限 1 秒
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

ENV_PREFIX = "FA_TDX_"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8011

DEFAULT_CONNECT_SECONDS = 3.0
DEFAULT_IO_SECONDS = 5.0
DEFAULT_REQUEST_BUDGET_SECONDS = 30.0
DEFAULT_MAX_HOST_SWITCHES = 2
DEFAULT_MAX_CONCURRENCY = 8
DEFAULT_QUEUE_WAIT_SECONDS = 1.0

#: 单批报价上限（协议 0x122B/0x053e 单次 80 只）。
DEFAULT_QUOTES_BATCH_LIMIT = 80
#: 单次列表/序列返回上限。
DEFAULT_MAX_PAGE_LIMIT = 1000
#: 目录/XDXR TTL 缓存秒数。
DEFAULT_CACHE_TTL_SECONDS = 300.0
#: 目录缓存单市场条目上限（超出标记不完整）。SH/SZ 全目录约 2.4~2.8 万条。
DEFAULT_DIRECTORY_MAX_ENTRIES = 30000


def _parse_float(env: Mapping[str, str], name: str, default: float, minimum: float) -> float:
    raw = env.get(f"{ENV_PREFIX}{name}")
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as e:
        raise ValueError(f"{ENV_PREFIX}{name} 必须为数字") from e
    if value <= minimum:
        raise ValueError(f"{ENV_PREFIX}{name} 必须大于 {minimum}")
    return value


def _parse_int(env: Mapping[str, str], name: str, default: int, minimum: int, maximum: int) -> int:
    raw = env.get(f"{ENV_PREFIX}{name}")
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as e:
        raise ValueError(f"{ENV_PREFIX}{name} 必须为整数") from e
    if value < minimum or value > maximum:
        raise ValueError(f"{ENV_PREFIX}{name} 必须在 [{minimum}, {maximum}] 内")
    return value


def _parse_hosts(env: Mapping[str, str], name: str) -> tuple[str, ...] | None:
    raw = env.get(f"{ENV_PREFIX}{name}")
    if not raw:
        return None
    hosts = tuple(h.strip() for h in raw.split(",") if h.strip())
    for host in hosts:
        if "/" in host or "://" in host or not host:
            raise ValueError(f"{ENV_PREFIX}{name} 含非法主机项: {host!r}")
    return hosts or None


@dataclass(frozen=True)
class Config:
    """不可变服务配置。"""

    host: str
    port: int
    api_key: str | None

    connect_seconds: float
    io_seconds: float
    request_budget_seconds: float
    max_host_switches: int
    max_concurrency: int
    queue_wait_seconds: float

    quotes_batch_limit: int
    max_page_limit: int
    cache_ttl_seconds: float
    directory_max_entries: int

    hosts_standard: tuple[str, ...] | None
    hosts_mac: tuple[str, ...] | None
    hosts_mac_ex: tuple[str, ...] | None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        """从环境构建配置；非法值抛 ``ValueError``。"""
        env = os.environ if env is None else env

        def get(name: str) -> str | None:
            return env.get(f"{ENV_PREFIX}{name}") or None

        port_raw = get("PORT")
        port = int(port_raw) if port_raw else DEFAULT_PORT
        if not 1 <= port <= 65535:
            raise ValueError(f"{ENV_PREFIX}PORT 必须在 [1, 65535] 内")

        host = get("HOST") or DEFAULT_HOST

        return cls(
            host=host,
            port=port,
            api_key=get("API_KEY"),
            connect_seconds=_parse_float(env, "CONNECT_SECONDS", DEFAULT_CONNECT_SECONDS, 0.0),
            io_seconds=_parse_float(env, "IO_SECONDS", DEFAULT_IO_SECONDS, 0.0),
            request_budget_seconds=_parse_float(env, "REQUEST_BUDGET_SECONDS", DEFAULT_REQUEST_BUDGET_SECONDS, 0.0),
            max_host_switches=_parse_int(env, "MAX_HOST_SWITCHES", DEFAULT_MAX_HOST_SWITCHES, 0, 8),
            max_concurrency=_parse_int(env, "MAX_CONCURRENCY", DEFAULT_MAX_CONCURRENCY, 1, 64),
            queue_wait_seconds=_parse_float(env, "QUEUE_WAIT_SECONDS", DEFAULT_QUEUE_WAIT_SECONDS, 0.0),
            quotes_batch_limit=min(
                _parse_int(env, "QUOTES_BATCH_LIMIT", DEFAULT_QUOTES_BATCH_LIMIT, 1, 80),
                80,
            ),
            max_page_limit=min(
                _parse_int(env, "MAX_PAGE_LIMIT", DEFAULT_MAX_PAGE_LIMIT, 1, 1000),
                1000,
            ),
            cache_ttl_seconds=_parse_float(env, "CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS, 0.0),
            directory_max_entries=_parse_int(env, "DIRECTORY_MAX_ENTRIES", DEFAULT_DIRECTORY_MAX_ENTRIES, 100, 60000),
            hosts_standard=_parse_hosts(env, "HOSTS_STANDARD"),
            hosts_mac=_parse_hosts(env, "HOSTS_MAC"),
            hosts_mac_ex=_parse_hosts(env, "HOSTS_MAC_EX"),
        )
