"""命令基类：请求帧构建 + 响应解析，不含任何 IO。

移植自 niyoh120/easy_tdx（固定提交 e374a0da2834119ac695c1083805d1b0a60967c2）
的 ``commands/base.py``。传输层负责发送、收帧、解压后调用 ``parse()``。

``render(head_flag)`` 的 head_flag 仅对 MAC 族命令有意义：
标准协议命令忽略该参数；MAC 命令标准会话用 0x1C，MAC EX 会话用 0x01。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from ..codec.frame import request_method_echo

T = TypeVar("T")


class Command(ABC, Generic[T]):
    """一条协议命令。"""

    def frame(self) -> bytes:
        """构建完整请求帧（默认 MAC 标准帧标识）。"""
        return self.render(0x1C)

    @abstractmethod
    def render(self, head_flag: int) -> bytes:
        """构建完整请求帧。"""

    @abstractmethod
    def parse(self, body: bytes) -> T:
        """解析解压后的响应 body。"""

    def method_echo(self) -> bytes:
        """请求 bytes[10:12]，用于响应回显校验。"""
        return request_method_echo(self.frame())
