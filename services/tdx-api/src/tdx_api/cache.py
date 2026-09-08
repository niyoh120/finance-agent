"""有界 TTL 内存缓存（可注入时钟，线程安全）。

用于主机选择结果、扩展市场目录与 XDXR 记录。条目数有硬上限，
超上限时拒绝写入（保持有界状态，由调用方标记完整性）。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Generic, TypeVar

V = TypeVar("V")


class TTLCache(Generic[V]):
    """小容量 TTL 缓存。

    Args:
        max_entries: 条目硬上限；超限时 ``set`` 返回 False（不驱逐旧条目，
            保持缓存有界且可预测）。
        ttl_seconds: 条目存活秒数。
        clock: 单调时钟（测试可注入）。
    """

    def __init__(self, max_entries: int, ttl_seconds: float, clock: Callable[[], float]) -> None:
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._clock = clock
        self._data: dict[str, tuple[float, V]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> V | None:
        """取条目；缺失或过期返回 None（过期条目顺带清除）。"""
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            stored_at, value = entry
            if self._clock() - stored_at > self._ttl:
                del self._data[key]
                return None
            return value

    def set(self, key: str, value: V) -> bool:
        """写条目；超出容量上限时拒绝并返回 False。"""
        with self._lock:
            if key in self._data:
                self._data[key] = (self._clock(), value)
                return True
            if len(self._data) >= self._max_entries:
                return False
            self._data[key] = (self._clock(), value)
            return True

    def clear(self) -> None:
        """清空缓存（测试用）。"""
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
