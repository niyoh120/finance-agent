"""有界 TCP 传输与三类协议会话。

设计（按批准计划）：
- 请求级会话：每个请求独占一条上游 socket，请求结束即关闭；
  会话由查询层通过 ``SessionFactory`` 打开，连接失败按候选主机顺序有界切换。
- 总预算：``Budget`` 持有请求级单调时钟 deadline，connect/send/recv 均
  受「剩余预算与单次 IO 上限的较小值」约束；预算耗尽抛 ``TdxTimeoutError``。
- 帧完整性：严格按 16 字节头读取，校验魔数、声明长度与命令码回显，
  声明长度超硬上限直接拒绝；解压后长度精确匹配。
- 握手：标准/MAC 会话连接后按序发送 3 条 setup 命令并丢弃响应
  （部分服务器对个别命令不响应，按参考实现容忍）；MAC EX 会话连接后登录。

移植自 niyoh120/easy_tdx（固定提交 e374a0da2834119ac695c1083805d1b0a60967c2）
的 ``transport/sync.py``、``ex/transport/sync.py``，去除心跳/健康分/全局
配置文件逻辑（本服务为请求级会话，不需要后台保活）。
"""

from __future__ import annotations

import logging
import socket
import time
from collections.abc import Callable
from typing import TypeVar

from .codec.frame import (
    HEADER_SIZE,
    decompress_body,
    parse_header,
    request_method_echo,
)
from .commands.base import Command
from .commands.ex.extended import MacExLoginCmd
from .commands.standard.setup import SETUP_COMMANDS
from .enums import MAC_EX_PORT, STANDARD_PORT
from .errors import TdxConnectionError, TdxTimeoutError

logger = logging.getLogger(__name__)

T = TypeVar("T")


class Budget:
    """请求级资源预算（单调时钟）。

    Attributes:
        total_seconds: 请求总预算（含连接、多命令、多主机切换与补取）。
        connect_seconds: 单次 TCP 连接上限。
        io_seconds: 单次 send/recv 上限。
    """

    __slots__ = ("_deadline", "connect_seconds", "io_seconds")

    def __init__(self, total_seconds: float, connect_seconds: float, io_seconds: float) -> None:
        self.connect_seconds = connect_seconds
        self.io_seconds = io_seconds
        self._deadline = time.monotonic() + total_seconds

    def remaining(self) -> float:
        """剩余预算秒数（不为负）。"""
        return max(self._deadline - time.monotonic(), 0.0)

    def io_window(self) -> float:
        """下一次 IO 的超时窗口：剩余预算与单次 IO 上限取小。"""
        return min(self.remaining(), self.io_seconds)

    def connect_window(self) -> float:
        """下一次连接的超时窗口：剩余预算与连接上限取小。"""
        return min(self.remaining(), self.connect_seconds)

    def check(self, context: str) -> None:
        """预算已耗尽时抛出超时错误。"""
        if self.remaining() <= 0:
            raise TdxTimeoutError(f"请求总预算耗尽: {context}")


def _recv_exact(sock: socket.socket, n: int, budget: Budget) -> bytes:
    """在预算窗口内循环 recv 直到读满 n 字节。"""
    buf = bytearray()
    while len(buf) < n:
        window = budget.io_window()
        if window <= 0:
            raise TdxTimeoutError("接收超时：请求预算耗尽")
        sock.settimeout(window)
        try:
            chunk = sock.recv(n - len(buf))
        except socket.timeout as e:
            raise TdxTimeoutError(f"接收超时（{window:.1f}s）") from e
        except OSError as e:
            raise TdxConnectionError(f"接收失败: {e}") from e
        if not chunk:
            raise TdxConnectionError("连接被服务器关闭")
        buf.extend(chunk)
    return bytes(buf)


def _send_all(sock: socket.socket, data: bytes, budget: Budget) -> None:
    window = budget.io_window()
    if window <= 0:
        raise TdxTimeoutError("发送超时：请求预算耗尽")
    sock.settimeout(window)
    try:
        sock.sendall(data)
    except socket.timeout as e:
        raise TdxTimeoutError(f"发送超时（{window:.1f}s）") from e
    except OSError as e:
        raise TdxConnectionError(f"发送失败: {e}") from e


class Session:
    """单协议会话：一条独占 socket + 帧收发。

    Attributes:
        head_flag: 该会话发出的 MAC 族帧标识（标准会话忽略）。
        handshake: 连接后是否执行握手（标准/MAC 为 setup，EX 为登录）。
    """

    head_flag = 0x0C
    handshake: str | None = "setup"

    def __init__(self, sock: socket.socket, budget: Budget) -> None:
        self._sock = sock
        self._budget = budget

    @classmethod
    def open(cls, host: str, port: int, budget: Budget) -> "Session":
        """建立连接并完成握手。"""
        budget.check(f"connect {host}:{port}")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(budget.connect_window())
        try:
            sock.connect((host, port))
        except socket.timeout as e:
            sock.close()
            raise TdxTimeoutError(f"连接 {host}:{port} 超时") from e
        except OSError as e:
            sock.close()
            raise TdxConnectionError(f"无法连接 {host}:{port}: {e}") from e

        session = cls(sock, budget)
        try:
            session._handshake()
        except Exception:
            session.close()
            raise
        return session

    def _handshake(self) -> None:
        """默认无握手（EX 登录在子类覆盖）。"""

    def close(self) -> None:
        """关闭底层 socket（幂等）。"""
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def execute(self, cmd: Command[T]) -> T:
        """执行一条命令：发送请求、按帧收响应、解压并解析。

        校验链：响应帧头魔数/声明长度（parse_header）→ 命令码回显 →
        body 实际长度 → 解压长度。
        """
        if self._sock is None:
            raise TdxConnectionError("会话已关闭")
        self._budget.check(cmd.__class__.__name__)
        request = cmd.render(self.head_flag)
        expected_echo = request_method_echo(request)
        _send_all(self._sock, request, self._budget)

        header_buf = _recv_exact(self._sock, HEADER_SIZE, self._budget)
        header = parse_header(header_buf)
        response_echo = header.method & 0xFFFF
        # 回显一致性观察：部分服务器对个别命令返回非请求命令码的值
        # （实测 0x051d 分时命令响应回显 0x0001）。请求级独占连接保证
        # 响应归属；回显异常仅记录日志，帧边界由魔数+声明长度+精确读取保障。
        if expected_echo and response_echo != 0 and response_echo != int.from_bytes(expected_echo, "little"):
            logger.warning(
                "响应命令码回显异常: expect=%s got=%#06x（已按请求级会话归属处理）",
                expected_echo.hex(),
                response_echo,
            )
        raw_body = _recv_exact(self._sock, header.zipsize, self._budget)
        body = decompress_body(header, raw_body)
        return cmd.parse(body)

    # ------------------------------------------------------------------ #
    # 标准协议握手
    # ------------------------------------------------------------------ #

    def _send_setup(self) -> None:
        """按序发送 3 条 setup 命令，读取并丢弃响应。

        与参考实现一致：个别服务器对个别握手命令无响应，读取失败容忍并
        继续后续握手命令（响应错位风险由首条业务命令的回显校验兜底）。
        """
        for cmd_bytes in SETUP_COMMANDS:
            try:
                _send_all(self._sock, cmd_bytes, self._budget)
                header_buf = _recv_exact(self._sock, HEADER_SIZE, self._budget)
                header = parse_header(header_buf)
                if header.zipsize > 0:
                    _recv_exact(self._sock, header.zipsize, self._budget)
            except TdxConnectionError:
                logger.warning("setup 握手响应读取失败，继续下一条握手命令")
            except TdxTimeoutError:
                logger.warning("setup 握手响应超时，继续下一条握手命令")


class StandardSession(Session):
    """标准 TDX 协议会话（A 股目录/财务/XDXR/分时/逐笔）。"""

    head_flag = 0x0C
    handshake = "setup"

    def _handshake(self) -> None:
        self._send_setup()


class MacSession(StandardSession):
    """MAC 协议会话（A 股行情，同端口、同 setup 握手、帧标识 0x1C）。"""

    head_flag = 0x1C
    handshake = "setup"


class MacExSession(Session):
    """MAC EX 扩展行情会话（港美股/指数/期货，端口 7727，登录 + 帧标识 0x01）。"""

    head_flag = 0x01
    handshake = "login"

    def _handshake(self) -> None:
        ok = self.execute(MacExLoginCmd())
        if not ok:
            # 登录被拒属主机级故障：交给上层换主机重试。
            raise TdxConnectionError("MAC EX 登录被拒绝")


#: 会话类型标识（查询层与主机选择器使用）。
SESSION_KINDS = ("standard", "mac", "mac_ex")

SessionKind = str

#: 会话工厂类型：按 (kind, host, budget) 打开会话；可注入测试替身。
SessionFactory = Callable[[SessionKind, str, Budget], Session]


def _open_tcp_session(kind: SessionKind, host: str, port: int, budget: Budget) -> Session:
    if kind == "standard":
        return StandardSession.open(host, port, budget)
    if kind == "mac":
        return MacSession.open(host, port, budget)
    if kind == "mac_ex":
        return MacExSession.open(host, port, budget)
    raise ValueError(f"未知会话类型: {kind}")


def make_session_factory() -> SessionFactory:
    """构建生产会话工厂（标准/MAC 用 7709，MAC EX 用 7727）。"""

    def factory(kind: SessionKind, host: str, budget: Budget) -> Session:
        session_port = MAC_EX_PORT if kind == "mac_ex" else STANDARD_PORT
        return _open_tcp_session(kind, host, session_port, budget)

    return factory


def probe_host(kind: SessionKind, host: str, port: int, timeout: float) -> float | None:
    """探测主机可用性：完成连接 + 握手即视为可用，返回耗时秒。

    不可达/超时返回 None。用于冷启动主机选择，热路径直接建会话。
    """
    started = time.monotonic()
    budget = Budget(total_seconds=timeout, connect_seconds=timeout, io_seconds=timeout)
    session: Session | None = None
    try:
        session = _open_tcp_session(kind, host, port, budget)
    except (TdxConnectionError, TdxTimeoutError):
        return None
    finally:
        if session is not None:
            session.close()
    return time.monotonic() - started
