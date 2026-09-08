"""二进制原语编解码。

移植自 niyoh120/easy_tdx（固定提交 e374a0da2834119ac695c1083805d1b0a60967c2）
的 ``_binary.py``、``codec/price.py``、``codec/volume.py``、``codec/datetime_.py``，
纯标准库实现（原实现同样仅依赖 struct）。逐函数审阅，行为与参考实现一致，
仅将异常类型改为本服务的 ``TdxDecodeError`` 并补充边界说明。
"""

from __future__ import annotations

import struct

from ..errors import TdxDecodeError


def require_bytes(data: bytes | bytearray, pos: int, size: int, context: str) -> None:
    """确保从 pos 起至少还能读取 size 字节，否则抛出截断错误。"""
    if pos < 0:
        raise TdxDecodeError(f"{context}: 非法偏移 {pos}")
    end = pos + size
    if end > len(data):
        remaining = max(len(data) - pos, 0)
        raise TdxDecodeError(f"{context}: 数据不足，需要 {size} 字节，偏移 {pos}，实际剩余 {remaining} 字节")


def unpack_from(fmt: str, data: bytes | bytearray, pos: int, context: str) -> tuple:
    """带边界检查的 struct.unpack_from。"""
    require_bytes(data, pos, struct.calcsize(fmt), context)
    try:
        return struct.unpack_from(fmt, data, pos)
    except struct.error as e:  # pragma: no cover - require_bytes 已覆盖
        raise TdxDecodeError(f"{context}: 解析失败: {e}") from e


def slice_bytes(data: bytes | bytearray, pos: int, size: int, context: str) -> bytes:
    """带边界检查的切片读取。"""
    require_bytes(data, pos, size, context)
    return bytes(data[pos : pos + size])


def get_price(data: bytes | bytearray, pos: int) -> tuple[int, int]:
    """解码通达信变长有符号整数（价格差分等）。

    编码规则：首字节 bit7=继续标记，bit6=符号，bit5~0=低 6 位；
    后续字节 bit7=继续标记，bit6~0=7 位数据；低位在前。

    Returns:
        (value, new_pos)
    """
    bit_shift = 6
    start = pos
    try:
        b = data[pos]
        value = b & 0x3F
        negative = bool(b & 0x40)
        if b & 0x80:
            while True:
                pos += 1
                b = data[pos]
                value |= (b & 0x7F) << bit_shift
                bit_shift += 7
                if not (b & 0x80):
                    break
    except IndexError as e:
        raise TdxDecodeError(f"price varint 截断: offset={start}") from e
    pos += 1
    return (-value if negative else value), pos


def put_price(value: int) -> bytes:
    """编码通达信变长有符号整数（测试与请求构造用）。"""
    negative = value < 0
    value = abs(value)
    first = value & 0x3F
    value >>= 6
    if negative:
        first |= 0x40
    if value:
        first |= 0x80
    result = bytearray([first])
    while value:
        b = value & 0x7F
        value >>= 7
        if value:
            b |= 0x80
        result.append(b)
    return bytes(result)


def get_volume(data: bytes | bytearray, pos: int) -> tuple[float, int]:
    """解码通达信 4 字节自定义浮点（成交量/金额/股本专用）。

    警告：仅用于成交量类字段，价格字段使用 varint（参考实现标注的 pytdx Bug #3）。
    """
    (ivol,) = unpack_from("<I", data, pos, "volume")
    return _decode_volume(ivol), pos + 4


def _decode_volume(ivol: int) -> float:
    if ivol == 0:
        return 0.0
    logpoint = (ivol >> 24) & 0xFF
    hleax = (ivol >> 16) & 0xFF
    lheax = (ivol >> 8) & 0xFF
    lleax = ivol & 0xFF

    exp = logpoint * 2 - 0x7F
    base = _pow2(exp)

    exp_h = logpoint * 2 - 0x86
    if hleax > 0x80:
        hi = _pow2(exp_h) * 128 + (hleax & 0x7F) * _pow2(exp_h + 1)
    else:
        hi = _pow2(exp_h) * hleax

    mid = _pow2(logpoint * 2 - 0x8E) * lheax
    lo = _pow2(logpoint * 2 - 0x96) * lleax

    if hleax & 0x80:
        mid *= 2.0
        lo *= 2.0

    return base + hi + mid + lo


def _pow2(exp: int) -> float:
    if exp >= 0:
        return float(1 << exp) if exp < 63 else 2.0**exp
    return 1.0 / (1 << (-exp)) if -exp < 63 else 2.0**exp


def get_datetime_minute(data: bytes | bytearray, pos: int) -> tuple[int, int, int, int, int, int]:
    """解析分钟级 4 字节时间戳（2 字节压缩日期 + 2 字节分钟数）。

    Returns:
        (year, month, day, hour, minute, new_pos)
    """
    zipday, tminutes = unpack_from("<HH", data, pos, "minute datetime")
    year = (zipday >> 11) + 2004
    month = (zipday % 2048) // 100
    day = (zipday % 2048) % 100
    hour = tminutes // 60
    minute = tminutes % 60
    return year, month, day, hour, minute, pos + 4


def get_datetime_day(data: bytes | bytearray, pos: int) -> tuple[int, int, int, int]:
    """解析日线及以上周期的 4 字节 YYYYMMDD 日期。

    Returns:
        (year, month, day, new_pos)
    """
    (zipday,) = unpack_from("<I", data, pos, "day datetime")
    year = zipday // 10000
    month = (zipday % 10000) // 100
    day = zipday % 100
    return year, month, day, pos + 4


def get_datetime(category: int, data: bytes | bytearray, pos: int) -> tuple[int, int, int, int, int, int]:
    """按 K 线周期选择时间格式。

    category < 4 或 category in (7, 8) 为分钟级；其余为日级（hour=15, minute=0，
    与参考实现/pytdx 保持一致的收盘时间占位）。

    Returns:
        (year, month, day, hour, minute, new_pos)
    """
    if category < 4 or category in (7, 8):
        return get_datetime_minute(data, pos)
    year, month, day, new_pos = get_datetime_day(data, pos)
    return year, month, day, 15, 0, new_pos


def get_time(data: bytes | bytearray, pos: int) -> tuple[int, int, int]:
    """解析 2 字节时间（分钟数）。

    Returns:
        (hour, minute, new_pos)
    """
    (tminutes,) = unpack_from("<H", data, pos, "trade time")
    return tminutes // 60, tminutes % 60, pos + 2


def decode_gbk(raw: bytes) -> str:
    """GBK 解码并以 NUL 截断；多字节序列截断用 replacement char（参考 Bug #2 修复）。"""
    return raw.decode("gbk", errors="replace").rstrip("\x00")


def decode_ascii(raw: bytes) -> str:
    """UTF-8/ASCII 解码并以 NUL 截断（代码字段）。"""
    return raw.decode("utf-8", errors="replace").rstrip("\x00")
