"""tdx-api 测试夹具。

三层测试基建：
1. ``make_config``：测试用 Config（可覆盖任意字段）。
2. ``FakeSession`` / ``fake_factory``：会话级替身（命令解析后的对象层），
   供查询层/HTTP 层端到端使用，不经过真实 IO。
3. ``FakeTdxServer``：可控本地 TCP 服务端，按脚本收发真实字节帧，
   驱动生产 transport（断包/压缩/截断/超时回放）。
"""

from __future__ import annotations

import socket
import struct
import threading
import zlib
from dataclasses import dataclass, field
from typing import Callable

import pytest
from tdx_api.config import Config
from tdx_api.main import create_app
from tdx_api.tdx.transport import Session

APP_KEY = None

MAGIC = 7654321


def make_config(**overrides) -> Config:
    """测试配置基线：快速预算，便于超时/504 用例。"""
    kwargs = dict(
        host="127.0.0.1",
        port=8011,
        api_key=None,
        connect_seconds=1.0,
        io_seconds=1.0,
        request_budget_seconds=10.0,
        max_host_switches=2,
        max_concurrency=8,
        queue_wait_seconds=0.2,
        quotes_batch_limit=80,
        max_page_limit=1000,
        cache_ttl_seconds=300.0,
        directory_max_entries=5000,
        hosts_standard=None,
        hosts_mac=None,
        hosts_mac_ex=None,
    )
    kwargs.update(overrides)
    return Config(**kwargs)


# --------------------------------------------------------------------- #
# 会话级替身
# --------------------------------------------------------------------- #


class FakeSession:
    """按命令类型分发到注册 handler 的替身会话（无 IO）。"""

    def __init__(self, handlers: dict[type, Callable]) -> None:
        self.handlers = handlers
        self.executed: list[object] = []
        self.closed = False

    def execute(self, cmd):
        self.executed.append(cmd)
        handler = self.handlers.get(type(cmd))
        if handler is None:
            raise AssertionError(f"FakeSession 未注册命令处理器: {type(cmd).__name__}")
        return handler(cmd)

    def close(self) -> None:
        self.closed = True


def fake_factory(handlers: dict[type, Callable], *, sessions: list[FakeSession] | None = None):
    """构建 SessionFactory 替身；记录创建的会话供断言。"""

    def factory(kind: str, host: str, budget) -> Session:
        session = FakeSession(handlers)
        session.kind = kind  # type: ignore[attr-defined]
        session.host = host  # type: ignore[attr-defined]
        if sessions is not None:
            sessions.append(session)
        return session  # type: ignore[return-value]

    return factory


def failing_factory(errors: list[Exception], *, sessions: list | None = None):
    """前 N 次建会话抛指定异常，之后抛 AssertionError（用于换主机用例）。"""
    calls = {"n": 0}

    def factory(kind: str, host: str, budget) -> Session:
        index = calls["n"]
        calls["n"] += 1
        if index < len(errors):
            raise errors[index]
        if sessions is not None:
            sessions.append(FakeSession({}))
        return FakeSession({})  # type: ignore[return-value]

    return factory


# --------------------------------------------------------------------- #
# 应用/客户端夹具
# --------------------------------------------------------------------- #


def make_app(config: Config, service_factory: Callable):
    """用注入的 service 工厂构建 FastAPI 应用。"""
    return create_app(config, service=service_factory(config))


@pytest.fixture()
def config():
    return make_config()


# --------------------------------------------------------------------- #
# TCP 层替身（协议回放）
# --------------------------------------------------------------------- #


def build_frame(body: bytes, method: int, *, compress: bool = False, seq: int = 0x010203) -> bytes:
    """构建 16 字节头响应帧。"""
    if compress:
        raw = zlib.compress(body)
        zipsize, unzipsize = len(raw), len(body)
    else:
        raw = body
        zipsize = unzipsize = len(body)
    return struct.pack("<IIIHH", MAGIC, seq, method, zipsize, unzipsize) + raw


@dataclass
class Exchange:
    """一次请求-响应脚本：读取 request_len 字节后发送 response（可拆包）。"""

    request_len: int
    response: bytes = b""
    split_at: int | None = None  # 拆包位置（模拟断包）
    delay: float = 0.0
    hold_seconds: float = 0.0  # 发送后保持连接不关闭（模拟服务器无响应超时）


@dataclass
class FakeTdxServer:
    """可控本地 TCP 服务端。

    每条连接按脚本顺序执行 exchange；脚本耗尽后直接关闭连接。
    """

    exchanges: list[Exchange] = field(default_factory=list)
    host: str = "127.0.0.1"

    def __post_init__(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, 0))
        self._sock.listen(4)
        self.port = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self.requests: list[bytes] = []
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(timeout=2)

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _addr = self._sock.accept()
            except OSError:
                return
            try:
                self._handle(conn)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def _handle(self, conn: socket.socket) -> None:
        conn.settimeout(5)
        for exchange in self.exchanges:
            buf = b""
            while len(buf) < exchange.request_len:
                chunk = conn.recv(exchange.request_len - len(buf))
                if not chunk:
                    return
                buf += chunk
            self.requests.append(buf)
            if exchange.delay:
                threading.Event().wait(exchange.delay)
            if exchange.split_at is not None and exchange.response:
                conn.sendall(exchange.response[: exchange.split_at])
                threading.Event().wait(0.02)
                conn.sendall(exchange.response[exchange.split_at :])
            elif exchange.response:
                conn.sendall(exchange.response)
            if exchange.hold_seconds:
                # 保持连接打开（不触发 EOF），用于客户端超时用例。
                threading.Event().wait(exchange.hold_seconds)
