"""MAC 协议字段位图编解码（0x122B 报价命令）。

移植自 niyoh120/easy_tdx（固定提交 e374a0da2834119ac695c1083805d1b0a60967c2）
的 ``codec/bitmap.py``，仅保留本服务报价所需字段的子集：

位图布局：20 字节请求位图 = 前 16 字节字段位（bit i ↔ FieldBit i）+ 4 字节控制区。
响应前 20 字节为位图回显，随后 total(4B)、行数(2B)、每行
固定 68 字节（market 2 + code 22 + name 44）+ 每激活字段 4 字节。

本服务固定请求 COMMON 字段集（OHLC + 昨收 + 量额 + 买卖一档），
避免把参考 SDK 全量 160+ 字段带入公开契约。
"""

from __future__ import annotations

import struct
from enum import IntEnum

#: 请求/响应位图字节数。
BITMAP_SIZE = 20


class FieldBit(IntEnum):
    """字段位定义（值 = 位序号，fmt = 4 字节小端解码格式）。"""

    PRE_CLOSE = 0x00, "<f"
    OPEN = 0x01, "<f"
    HIGH = 0x02, "<f"
    LOW = 0x03, "<f"
    CLOSE = 0x04, "<f"
    VOL = 0x05, "<I"
    VOL_RATIO = 0x06, "<f"
    AMOUNT = 0x07, "<f"
    INSIDE_VOLUME = 0x08, "<I"
    OUTSIDE_VOLUME = 0x09, "<I"
    BID_PRICE = 0x11, "<f"
    ASK_PRICE = 0x12, "<f"
    SERVER_UPDATE_DATE = 0x13, "<I"
    SERVER_UPDATE_TIME = 0x14, "<I"
    BID_VOLUME = 0x18, "<I"
    ASK_VOLUME = 0x19, "<I"
    LAST_VOLUME = 0x1A, "<I"

    def __new__(cls, value: int, fmt: str = "<f") -> "FieldBit":
        obj = int.__new__(cls, value)
        obj._value_ = value
        obj.fmt = fmt
        return obj


#: 服务对外报价固定字段集（顺序即响应解码顺序依赖，由位图回显决定）。
QUOTE_FIELDS: tuple[FieldBit, ...] = (
    FieldBit.PRE_CLOSE,
    FieldBit.OPEN,
    FieldBit.HIGH,
    FieldBit.LOW,
    FieldBit.CLOSE,
    FieldBit.VOL,
    FieldBit.AMOUNT,
    FieldBit.BID_PRICE,
    FieldBit.ASK_PRICE,
    FieldBit.BID_VOLUME,
    FieldBit.ASK_VOLUME,
    FieldBit.LAST_VOLUME,
    FieldBit.VOL_RATIO,
    FieldBit.INSIDE_VOLUME,
    FieldBit.OUTSIDE_VOLUME,
    FieldBit.SERVER_UPDATE_DATE,
    FieldBit.SERVER_UPDATE_TIME,
)


def build_bitmap(fields: tuple[FieldBit, ...] = QUOTE_FIELDS) -> bytes:
    """构建 20 字节请求位图（控制区为 0，标准模式）。"""
    bitmap = bytearray(BITMAP_SIZE)
    for bit in fields:
        bitmap[bit // 8] |= 1 << (bit % 8)
    return bytes(bitmap)


def get_active_fields(bitmap16: bytes) -> list[FieldBit]:
    """解析响应位图前 16 字节中的激活字段（按位序返回）。"""
    active: list[FieldBit] = []
    for bit in FieldBit:
        if bit < len(bitmap16) * 8 and bitmap16[bit // 8] & (1 << (bit % 8)):
            active.append(bit)
    return active


def decode_field_value(bit: FieldBit, raw: bytes) -> int | float:
    """按字段格式解码 4 字节值。"""
    (value,) = struct.unpack(bit.fmt, raw)
    return value
