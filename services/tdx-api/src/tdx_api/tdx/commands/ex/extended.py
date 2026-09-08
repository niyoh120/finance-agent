"""MAC EX 扩展行情命令：登录、商品目录、分时、逐笔。

移植自 niyoh120/easy_tdx（固定提交 e374a0da2834119ac695c1083805d1b0a60967c2）
的 ``ex/commands/login.py``、``ex/commands/get_instrument_count.py``、
``ex/commands/get_instrument_info.py``、``ex/commands/get_minute_time.py``、
``ex/commands/get_transaction.py``。

审阅要点（与参考实现对齐）：
- EX 服务器（端口 7727）要求数据查询前先 Login（0x2454，帧标识 0x01），
  登录 body 为固定 80 字节（参考实现自 opentdx 验证）。
- GetInstrumentInfo（0x23f5）返回全局商品目录的 64 字节定长记录，
  按市场有序；服务层据此做市场内分页与按市场过滤。
- 逐笔成交：当日 0x23fc / 历史 0x2406，16 字节记录
  ``<HIIiH``，价格整数为 0.001 计价货币（港股已验证 1000→港元）；
  nature（方向）编码在 direction 字段高位（×10000），秒在低位。
"""

from __future__ import annotations

import struct

from ...codec.primitives import decode_gbk
from ...commands.base import Command
from ...models import ExInstrumentInfo, MinuteBar, Transaction

_LOGIN_MSG_ID = 0x2454
_INSTRUMENT_COUNT_MSG_ID = 0x23F0
_INSTRUMENT_INFO_MSG_ID = 0x23F5
_MINUTE_TIME_MSG_ID = 0x240B
_HISTORY_MINUTE_TIME_MSG_ID = 0x240C
_TRANSACTION_MSG_ID = 0x23FC
_HISTORY_TRANSACTION_MSG_ID = 0x2406

_HEAD_FLAG = 0x01

#: 逐笔方向字段中 nature 的放大系数：direction = nature * 10000 + second。
_DIRECTION_NATURE_SCALE = 10000

#: EX 协议逐笔/分时单页上限。
EX_TRANSACTION_PAGE_SIZE = 1800
EX_INSTRUMENT_PAGE_SIZE = 1000


def _ex_frame(msg_id: int, body: bytes) -> bytes:
    """EX 协议请求帧（head_flag 固定 0x01）。"""
    inner = struct.pack("<H", msg_id) + body
    header = struct.pack("<BIBHH", _HEAD_FLAG, 0, 1, len(inner), len(inner))
    return header + inner


class MacExLoginCmd(Command[bool]):
    """MAC EX 登录命令（0x2454）。"""

    def render(self, head_flag: int) -> bytes:
        del head_flag  # EX 命令帧标识固定 0x01
        return _ex_frame(
            _LOGIN_MSG_ID,
            bytes.fromhex(
                "e5bb1c2fafe52594"
                "1f32c6e5d53dfb41"
                "5b734cc9cdbf0ac9"
                "2021bfdd1eb06d22"
                "d008884c1611cb13"
                "78f6abd824d899d2"
                "1f32c6e5d53dfb41"
                "1f32c6e5d53dfb41"
                "a9325ac935dc0837"
                "335a16e4ce17c1bb"
            ),
        )

    def parse(self, body: bytes) -> bool:
        # 参考实现：响应 body 非空（≥2 字节）即视为成功；空响应由会话层
        # 按主机级故障处理。
        return len(body) >= 2


class GetExInstrumentCountCmd(Command[int]):
    """EX 全局商品总数（0x23f0）。"""

    def render(self, head_flag: int) -> bytes:
        del head_flag
        return bytes.fromhex("010348660001020002 00f023".replace(" ", ""))

    def parse(self, body: bytes) -> int:
        if len(body) < 23:
            return 0
        (count,) = struct.unpack_from("<I", body, 19)
        return int(count)


class GetExInstrumentInfoCmd(Command[list[ExInstrumentInfo]]):
    """EX 商品目录页（0x23f5，全局序，64 字节定长记录）。"""

    MAX_COUNT = EX_INSTRUMENT_PAGE_SIZE

    def __init__(self, start: int, count: int = 100) -> None:
        self.start = start
        self.count = min(count, self.MAX_COUNT)

    def render(self, head_flag: int) -> bytes:
        del head_flag
        header = bytes.fromhex("0104486700010800 0800f523".replace(" ", ""))
        return header + struct.pack("<IH", self.start, self.count)

    def parse(self, body: bytes) -> list[ExInstrumentInfo]:
        if len(body) < 6:
            return []
        _start, count = struct.unpack_from("<IH", body, 0)
        pos = 6
        results: list[ExInstrumentInfo] = []
        for _ in range(count):
            if pos + 64 > len(body):
                break
            raw = body[pos : pos + 64]
            pos += 64
            category, market, _unused, raw_code, raw_name, raw_desc = struct.unpack(
                "<BB3s9s17s9s",
                raw[:40],
            )
            results.append(
                ExInstrumentInfo(
                    category=category,
                    market=market,
                    code=decode_gbk(raw_code),
                    name=decode_gbk(raw_name),
                    desc=decode_gbk(raw_desc),
                )
            )
        return results


class _ExMinuteBase(Command[list[MinuteBar]]):
    def __init__(self, market: int, code: str, date: int | None = None) -> None:
        self.market = market
        self.code = code
        self.date = date

    def render(self, head_flag: int) -> bytes:
        del head_flag
        if self.date is None:
            header = bytes.fromhex("0107080001 010c000c0 00b24".replace(" ", ""))
            return header + struct.pack("<B9s", self.market, self.code.encode("utf-8"))
        header = bytes.fromhex("010130000101100010000c24")
        return header + struct.pack("<IB9s", self.date, self.market, self.code.encode("utf-8"))

    def parse(self, body: bytes) -> list[MinuteBar]:
        if self.date is None:
            if len(body) < 12:
                return []
            _market, _code, num = struct.unpack_from("<B9sH", body, 0)
            pos = 12
        else:
            if len(body) < 20:
                return []
            _market, _code, _unk, num = struct.unpack_from("<B9s8sH", body, 0)
            pos = 20
        bars: list[MinuteBar] = []
        for _ in range(num):
            if pos + 18 > len(body):
                break
            raw_time, price, avg_price, volume, amount = struct.unpack_from("<HffII", body, pos)
            pos += 18
            bars.append(
                MinuteBar(
                    price=price,
                    vol=float(volume),
                    time=(raw_time // 60, raw_time % 60),
                    avg_price=avg_price,
                    amount=float(amount),
                )
            )
        return bars


class GetExMinuteTimeDataCmd(_ExMinuteBase):
    """EX 当日分时（0x240b）。"""

    def __init__(self, market: int, code: str) -> None:
        super().__init__(market, code, date=None)


class GetExHistoryMinuteTimeDataCmd(_ExMinuteBase):
    """EX 历史分时（0x240c，date=YYYYMMDD）。"""

    def __init__(self, market: int, code: str, date: int) -> None:
        super().__init__(market, code, date=date)


def _parse_ex_transactions(body: bytes, header_len: int) -> list[Transaction]:
    if len(body) < header_len:
        return []
    _market, _code, _unk, num = struct.unpack_from("<B9s4sH", body, 0)
    pos = header_len
    records: list[Transaction] = []
    for _ in range(num):
        if pos + 16 > len(body):
            break
        raw_time, price, volume, zengcang, direction = struct.unpack_from("<HIIiH", body, pos)
        pos += 16
        hour = raw_time // 60
        minute = raw_time % 60
        second = direction % _DIRECTION_NATURE_SCALE
        if second > 59:
            second = 0
        nature = direction // _DIRECTION_NATURE_SCALE
        records.append(
            Transaction(
                time=(hour, minute, second),
                price=price / 1000.0,  # 0.001 计价货币（港股已验证；其他市场随行情币种）
                volume=float(volume),
                direction=nature,
                open_interest=zengcang,
            )
        )
    return records


class GetExTransactionDataCmd(Command[list[Transaction]]):
    """EX 当日逐笔成交（0x23fc）。"""

    MAX_COUNT = EX_TRANSACTION_PAGE_SIZE

    def __init__(self, market: int, code: str, start: int = 0, count: int = EX_TRANSACTION_PAGE_SIZE) -> None:
        self.market = market
        self.code = code
        self.start = start
        self.count = min(count, self.MAX_COUNT)

    def render(self, head_flag: int) -> bytes:
        del head_flag
        header = bytes.fromhex("010108000301120012 00fc23".replace(" ", ""))
        return header + struct.pack("<B9siH", self.market, self.code.encode("utf-8"), self.start, self.count)

    def parse(self, body: bytes) -> list[Transaction]:
        return _parse_ex_transactions(body, header_len=16)


class GetExHistoryTransactionDataCmd(Command[list[Transaction]]):
    """EX 历史逐笔成交（0x2406，date=YYYYMMDD）。"""

    MAX_COUNT = EX_TRANSACTION_PAGE_SIZE

    def __init__(
        self,
        market: int,
        code: str,
        date: int,
        start: int = 0,
        count: int = EX_TRANSACTION_PAGE_SIZE,
    ) -> None:
        self.market = market
        self.code = code
        self.date = date
        self.start = start
        self.count = min(count, self.MAX_COUNT)

    def render(self, head_flag: int) -> bytes:
        del head_flag
        header = bytes.fromhex("010130000201160016 000624".replace(" ", ""))
        return header + struct.pack(
            "<IB9siH", self.date, self.market, self.code.encode("utf-8"), self.start, self.count
        )

    def parse(self, body: bytes) -> list[Transaction]:
        return _parse_ex_transactions(body, header_len=16)
