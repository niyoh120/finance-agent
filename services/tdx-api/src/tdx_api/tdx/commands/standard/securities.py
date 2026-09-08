"""标准协议证券目录命令（计数 + 列表）。

按最小依赖闭包移植自 niyoh120/easy_tdx（固定提交
e374a0da2834119ac695c1083805d1b0a60967c2）的 ``commands/security_count.py``、
``commands/security_list.py``。A 股行情走 MAC 会话（批准计划的会话分工），
标准协议的 bars/quotes 命令不在本服务闭包内。

审阅要点（与参考实现对齐）：
- 请求帧为「固定字节模板 + 载荷」，模板与参考实现逐字节一致。
- 列表每条定长 29 字节：code(6s) + volunit(H) + name(8s GBK) + 未知(4s)
  + decimal_point(B) + pre_close(自定义浮点 I) + 未知(4s)。
- GBK 解码 errors='replace'（参考 Bug #2 修复）；昨收用通达信自定义浮点
  （参考 Bug #3 修复，价格字段禁用成交量解码的告警在此不适用：
  pre_close 确实使用该浮点编码）。
"""

from __future__ import annotations

import struct

from ...codec.primitives import decode_ascii, decode_gbk, slice_bytes, unpack_from
from ...enums import StdMarket
from ...models import SecurityListEntry
from ..base import Command


class GetSecurityCountCmd(Command[int]):
    """市场证券总数（模板 0x046c；亦可作握手保活命令）。"""

    def __init__(self, market: StdMarket) -> None:
        self.market = market

    def render(self, head_flag: int) -> bytes:
        del head_flag  # 标准协议帧，忽略 MAC 帧标识
        header = bytes.fromhex("0c0c186c0001080008004e04")
        return header + struct.pack("<H", int(self.market)) + b"\x75\xc7\x33\x01"

    def parse(self, body: bytes) -> int:
        (count,) = unpack_from("<H", body, 0, "security_count")
        return int(count)


class GetSecurityListCmd(Command[list[SecurityListEntry]]):
    """证券列表（模板 0x0450），每页最多 1000 条定长 29 字节记录。"""

    #: 单页记录数上限（命令帧上限；查询层按此拆页）。
    PAGE_SIZE = 1000
    _RECORD_SIZE = 29

    def __init__(self, market: StdMarket, start: int) -> None:
        self.market = market
        self.start = start

    def render(self, head_flag: int) -> bytes:
        del head_flag
        header = bytes.fromhex("0c0118640101060006005004")
        return header + struct.pack("<HHH", int(self.market), self.start, 0)

    def parse(self, body: bytes) -> list[SecurityListEntry]:
        (num,) = unpack_from("<H", body, 0, "security_list header")
        pos = 2
        results: list[SecurityListEntry] = []
        for _ in range(num):
            raw = slice_bytes(body, pos, self._RECORD_SIZE, "security_list record")
            pos += self._RECORD_SIZE
            (
                code_bytes,
                volunit,
                name_bytes,
                _unknown1,
                decimal_point,
                pre_close_raw,
                _unknown2,
            ) = struct.unpack("<6sH8s4sB4s4s", raw)
            results.append(
                SecurityListEntry(
                    market=int(self.market),
                    code=decode_ascii(code_bytes),
                    name=decode_gbk(name_bytes),
                    volunit=volunit,
                    decimal_point=decimal_point,
                    pre_close=_decode_custom_float(pre_close_raw),
                )
            )
        return results


def _decode_custom_float(raw: bytes) -> float:
    """昨收价使用通达信自定义 4 字节浮点（参考 Bug #3 修复）。"""
    from ...codec.primitives import _decode_volume

    (ivol,) = struct.unpack("<I", raw)
    return _decode_volume(ivol)
