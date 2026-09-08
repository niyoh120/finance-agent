"""受限并发门（名额 + 排队上限）。

协议请求为同步 socket IO，FastAPI 在线程池中执行路由函数；
本信号量限制同时在途的上游请求数（默认 8），排队等待超限（默认 1 秒）
立即抛 ``ConcurrencySaturationError``（429），避免请求积压放大上游压力。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TypeVar

from .errors import ConcurrencySaturationError

T = TypeVar("T")


class BoundedGate:
    """有界并发门。"""

    def __init__(self, max_concurrency: int, queue_wait_seconds: float) -> None:
        self._semaphore = threading.BoundedSemaphore(max_concurrency)
        self._queue_wait = queue_wait_seconds

    def run(self, fn: Callable[[], T]) -> T:
        """在并发名额内执行 fn；排队超限抛 ``ConcurrencySaturationError``。"""
        acquired = self._semaphore.acquire(timeout=self._queue_wait)
        if not acquired:
            raise ConcurrencySaturationError(f"并发名额已占满，排队等待超过 {self._queue_wait:.1f}s")
        try:
            return fn()
        finally:
            self._semaphore.release()
