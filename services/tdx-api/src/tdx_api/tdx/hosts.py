"""候选行情服务器与主机选择。

候选表来源：niyoh120/easy_tdx（固定提交 e374a0da2834119ac695c1083805d1b0a60967c2）
``config.py`` 内嵌默认候选池（其自身持续对真实服务器测速维护）。
本服务仅允许管理员通过环境变量覆盖候选表与内置表；查询参数不携带主机地址。

主机选择策略（按批准计划）：
- 有界 TTL 内存缓存记住各会话类型的最近可用主机，热路径直接复用，避免每次全池测速。
- 缓存过期或连接失败时，对候选池做并发探测（连接 + 握手），选最快可用者并回写缓存。
- 全部候选不可用时抛 ``TdxConnectionError``，由 HTTP 层映射为 503。
"""

from __future__ import annotations

import concurrent.futures
import logging
import time
from collections.abc import Callable

from .enums import MAC_EX_PORT, STANDARD_PORT
from .errors import TdxConnectionError
from .transport import SessionKind, probe_host

logger = logging.getLogger(__name__)

#: 主机选择缓存 TTL（秒）：避免每次请求全池测速。
HOST_CACHE_TTL_SECONDS = 300.0
#: 并发探测的超时上限（秒）。
PROBE_TIMEOUT_SECONDS = 4.0
#: 并发探测线程上限。
PROBE_MAX_WORKERS = 8

_STANDARD_HOSTS: tuple[str, ...] = (
    "111.229.247.189",
    "150.158.160.2",
    "180.153.18.170",
    "124.71.187.122",
    "180.153.18.171",
    "119.147.212.81",
    "115.238.56.198",
    "115.238.90.165",
    "119.97.185.59",
    "124.70.199.56",
    "110.41.147.114",
    "101.33.225.16",
)

_MAC_HOSTS: tuple[str, ...] = (
    "121.36.248.138",
    "123.60.47.136",
    "121.37.207.165",
)

_MAC_EX_HOSTS: tuple[str, ...] = (
    "116.205.135.205",
    "121.37.232.167",
    "112.74.214.43",
    "120.25.218.6",
    "43.139.173.246",
    "159.75.90.107",
    "124.71.223.19",
)

#: 会话类型 → (候选主机, 端口)。
BUILTIN_CANDIDATES: dict[str, tuple[tuple[str, ...], int]] = {
    "standard": (_STANDARD_HOSTS, STANDARD_PORT),
    "mac": (_MAC_HOSTS, STANDARD_PORT),
    "mac_ex": (_MAC_EX_HOSTS, MAC_EX_PORT),
}


class HostSelector:
    """各会话类型的候选主机与最近可用主机缓存（线程安全）。"""

    def __init__(
        self,
        candidates: dict[str, tuple[tuple[str, ...], int]] | None = None,
        *,
        ttl: float = HOST_CACHE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._candidates = candidates or BUILTIN_CANDIDATES
        self._ttl = ttl
        self._clock = clock
        # kind -> (host, cached_at)
        self._preferred: dict[str, tuple[str, float]] = {}

    def candidates_for(self, kind: SessionKind) -> tuple[list[str], int]:
        """返回会话类型的候选主机列表（优先缓存主机）与端口。

        管理员配置优先于内置表；缓存主机排在最前，其余保持池内顺序。
        """
        hosts, port = self._candidates.get(kind, ((), STANDARD_PORT))
        ordered = list(hosts)
        preferred = self._fresh_preferred(kind)
        if preferred and preferred in ordered:
            ordered.remove(preferred)
            ordered.insert(0, preferred)
        elif preferred:
            ordered.insert(0, preferred)
        return ordered, port

    def _fresh_preferred(self, kind: SessionKind) -> str | None:
        entry = self._preferred.get(kind)
        if entry is None:
            return None
        host, cached_at = entry
        if self._clock() - cached_at > self._ttl:
            return None
        return host

    def has_fresh(self, kind: SessionKind) -> bool:
        """该会话类型是否存在未过期的可用主机缓存。"""
        return self._fresh_preferred(kind) is not None

    def mark_good(self, kind: SessionKind, host: str) -> None:
        """记录一次成功连接（回写缓存）。"""
        self._preferred[kind] = (host, self._clock())

    def mark_bad(self, kind: SessionKind, host: str) -> None:
        """连接失败时使缓存失效。"""
        entry = self._preferred.get(kind)
        if entry and entry[0] == host:
            self._preferred.pop(kind, None)

    def select(
        self,
        kind: SessionKind,
        *,
        timeout: float = PROBE_TIMEOUT_SECONDS,
    ) -> tuple[str, int]:
        """为会话类型选出一台可用主机（并发探测，按耗时排序）。

        Returns:
            (host, port)

        Raises:
            TdxConnectionError: 全部候选不可用。
        """
        hosts, port = self.candidates_for(kind)
        if not hosts:
            raise TdxConnectionError(f"会话类型 {kind} 无候选主机")
        results: list[tuple[str, float]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=PROBE_MAX_WORKERS) as pool:
            futures = {pool.submit(probe_host, kind, h, port, timeout): h for h in hosts}
            for future in concurrent.futures.as_completed(futures):
                host = futures[future]
                try:
                    latency = future.result()
                except Exception:  # 防御：单台探测异常不拖垮选择
                    continue
                if latency is not None:
                    results.append((host, latency))
        if not results:
            raise TdxConnectionError(f"会话类型 {kind} 的 {len(hosts)} 台候选主机均不可用")
        results.sort(key=lambda item: item[1])
        best = results[0][0]
        self.mark_good(kind, best)
        logger.info("主机选择 kind=%s -> %s（%d/%d 可用）", kind, best, len(results), len(hosts))
        return best, port
