"""MAC 协议命令：K 线、批量报价、个股信息、逐笔成交。

移植自 niyoh120/easy_tdx（固定提交 e374a0da2834119ac695c1083805d1b0a60967c2）
的 ``mac/commands/symbol_bar.py``、``mac/commands/symbol_quotes.py``、
``mac/commands/symbol_info.py``、``mac/commands/symbol_transaction.py``。

审阅要点（与参考实现对齐）：
- 帧标识由会话注入：MAC 行情服务器 0x1C，MAC EX 服务器 0x01。
- symbol_bar 响应：33 字节头（market/code/category/flag/count/start）+
  每条 36 字节 ``<II7f``；参考实现对 ymd 越界记录跳过、对越界尾部截断。
- symbol_quotes：请求位图 20 字节 + 股票列表；响应按位图回显解码字段，
  行长 68 + 4×字段数；越界尾部按参考实现截断丢弃。
- symbol_transaction：响应 39 字节头后每条 18 字节 ``<IfIIH``；
  bs_flag 语义 0=买入 1=卖出 2=中性 5=盘后；协议原生倒序（最新在前）。
"""

from __future__ import annotations

import struct
from datetime import datetime

from ...codec.frame import build_mac_request
from ...codec.primitives import decode_gbk, unpack_from
from ...enums import Adjust, MacPeriod
from ...errors import TdxDecodeError
from ...models import MacQuote, MacSymbolInfo, Transaction
from ..base import Command
from .bitmap import (
    BITMAP_SIZE,
    FieldBit,
    build_bitmap,
    decode_field_value,
    get_active_fields,
)

_SYMBOL_BAR_MSG_ID = 0x122E
_SYMBOL_QUOTES_MSG_ID = 0x122B
_SYMBOL_INFO_MSG_ID = 0x122A
_SYMBOL_TRANSACTION_MSG_ID = 0x122F
_SYMBOL_TICK_CHART_MSG_ID = 0x122D

#: 0x122E 单页上限（参考实现分页页宽）。
MAC_KLINE_PAGE_SIZE = 700
#: 0x122B 单次报价上限（与参考实现一致）。
MAC_QUOTES_MAX_BATCH = 80
#: 0x122D 单日分时图 tick 记录长度。
_TICK_RECORD_SIZE = 18
_TICK_HEADER_SIZE = 35


class MacSymbolBarCmd(Command[list]):
    """MAC 族 K 线命令（0x122E，标准市场与扩展市场共用）。"""

    def __init__(
        self,
        market: int,
        code: str,
        period: MacPeriod = MacPeriod.DAILY,
        times: int = 1,
        start: int = 0,
        count: int = MAC_KLINE_PAGE_SIZE,
        fq: Adjust = Adjust.NONE,
    ) -> None:
        self.market = market
        self.code = code
        self.period = period
        self.times = times
        self.start = start
        self.count = count
        self.fq = fq

    def render(self, head_flag: int) -> bytes:
        body = struct.pack(
            "<H22sHHIHHbbbbH4s",
            self.market,
            self.code.encode("gbk"),
            int(self.period),
            self.times,
            self.start,
            self.count,
            int(self.fq),
            1,
            1,
            0,
            1,
            0,
            b"",
        )
        return build_mac_request(_SYMBOL_BAR_MSG_ID, body, head_flag=head_flag)

    def parse(self, body: bytes) -> list:
        # 头部: market(2) + code(22) + category(1) + flag(1) + count(2) + start(4) = 32 字节后…
        # 参考实现从偏移 24 读 <HBHI>：category_flag(1) + flag(1) + count(2) + start(4)。
        _category_flag, _flag, count, _start = unpack_from("<HBHI", body, 24, "symbol_bar header")

        # 防越界：count 以 body 实际可容纳记录数为准（参考实现同款保护）。
        count = min(count, max((len(body) - 33) // 36, 0))
        is_intraday = int(self.period) < int(MacPeriod.DAILY)

        bars: list = []
        for i in range(count):
            offset = 33 + i * 36
            if offset + 36 > len(body):
                break
            ymd, time_num, open_, high, low, close, amount, vol, _float_shares = unpack_from(
                "<II7f", body, offset, f"symbol_bar bar[{i}]"
            )
            if ymd < 19900101 or ymd > 20991231:
                continue
            year = ymd // 10000
            month = (ymd % 10000) // 100
            day = ymd % 100
            if is_intraday and time_num:
                hour = time_num // 3600
                minute = (time_num % 3600) // 60
            else:
                hour, minute = 0, 0
            bars.append(
                {
                    "datetime": datetime(year, month, day, hour, minute),
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "vol": vol,
                    "amount": amount,
                }
            )
        return bars


class MacSymbolQuotesCmd(Command[list[MacQuote]]):
    """MAC 族批量报价（0x122B，字段位图模式）。"""

    def __init__(
        self,
        stocks: list[tuple[int, str]],
        fields: tuple[FieldBit, ...] | None = None,
    ) -> None:
        if not stocks:
            raise ValueError("stocks 不能为空")
        if len(stocks) > MAC_QUOTES_MAX_BATCH:
            raise ValueError(f"单次最多查询 {MAC_QUOTES_MAX_BATCH} 只")
        self.stocks = stocks
        self.fields = fields or ()
        self._bitmap = build_bitmap(self.fields)

    def render(self, head_flag: int) -> bytes:
        body = bytearray(self._bitmap)
        body += struct.pack("<H", len(self.stocks))
        for market, code in self.stocks:
            body += struct.pack("<H22s", market, code.encode("gbk"))
        return build_mac_request(_SYMBOL_QUOTES_MSG_ID, bytes(body), head_flag=head_flag)

    def parse(self, body: bytes) -> list[MacQuote]:
        pos = 0
        field_bitmap = body[pos : pos + BITMAP_SIZE]
        pos += BITMAP_SIZE

        _total_stocks, row_count = unpack_from("<IH", body, pos, "symbol_quotes header")
        pos += 6

        active = get_active_fields(field_bitmap[:16])
        field_count = len(active)
        row_len = 68 + 4 * field_count

        results: list[MacQuote] = []
        for _ in range(row_count):
            row_end = pos + row_len
            if row_end > len(body):
                break
            row_data = body[pos:row_end]
            pos = row_end

            market, code_raw, name_raw = unpack_from("<H22s44s", row_data, 0, "symbol_quotes row")
            fields: dict[str, float | int] = {}
            for idx, bit in enumerate(active):
                raw = row_data[68 + idx * 4 : 68 + (idx + 1) * 4]
                if len(raw) < 4:
                    break
                fields[bit.name.lower()] = decode_field_value(bit, raw)

            results.append(
                MacQuote(
                    market=market,
                    code=code_raw.decode("gbk", errors="ignore").replace("\x00", ""),
                    name=decode_gbk(name_raw),
                    fields=fields,
                )
            )
        return results


class MacSymbolInfoCmd(Command[MacSymbolInfo]):
    """MAC 族个股简要特征（0x122A）。"""

    def __init__(self, market: int, code: str) -> None:
        self.market = market
        self.code = code

    def render(self, head_flag: int) -> bytes:
        body = struct.pack("<H22sI12x", self.market, self.code.encode("gbk"), 1)
        return build_mac_request(_SYMBOL_INFO_MSG_ID, body, head_flag=head_flag)

    def parse(self, body: bytes) -> MacSymbolInfo:
        (market, code_raw, name_raw) = unpack_from("<H22s44s", body, 8, "symbol_info identity")
        (
            date_raw,
            time_raw,
            _activity,
            pre_close,
            open_,
            high,
            low,
            close,
            _momentum,
            vol,
            amount,
            _inside_volume,
            _outside_volume,
        ) = unpack_from("<III5ffIfII", body, 96, "symbol_info core")

        dt: datetime | None = None
        if date_raw:
            dt = datetime(
                date_raw // 10000,
                (date_raw % 10000) // 100,
                date_raw % 100,
                time_raw // 10000,
                (time_raw % 10000) // 100,
                time_raw % 100,
            )

        return MacSymbolInfo(
            market=market,
            code=code_raw.decode("gbk", errors="ignore").replace("\x00", ""),
            name=decode_gbk(name_raw),
            time=dt,
            pre_close=pre_close,
            open=open_,
            high=high,
            low=low,
            close=close,
            vol=vol,
            amount=amount,
        )


class MacSymbolTickChartCmd(Command[dict]):
    """MAC 族单日分时图（0x122D）。

    移植自参考实现 ``mac/commands/symbol_tick_chart.py``，实况验证
    （CN 市场，含历史日期）。响应含显式分钟时间、均价、名称与日级摘要。
    tick 时间为区间起点（与 0x122E 分钟线同口径，实测与 K 线量对齐）。
    """

    def __init__(self, market: int, code: str, query_date: int | None = None) -> None:
        self.market = market
        self.code = code
        self.ymd = query_date or 0

    def render(self, head_flag: int) -> bytes:
        body = struct.pack(
            "<H22sI5H",
            self.market,
            self.code.encode("gbk"),
            self.ymd,
            1,
            0,
            0,
            0,
            0,
        )
        return build_mac_request(_SYMBOL_TICK_CHART_MSG_ID, body, head_flag=head_flag)

    def parse(self, body: bytes) -> dict:
        _market, code_raw, _query_date, _reserved, _ref_price, count = unpack_from(
            "<H22sIBfH", body, 0, "tick_chart header"
        )
        ticks: list[dict] = []
        for i in range(count):
            offset = _TICK_HEADER_SIZE + i * _TICK_RECORD_SIZE
            if offset + _TICK_RECORD_SIZE > len(body):
                break
            minutes, price, avg, vol, _momentum = unpack_from("<HffIf", body, offset, f"tick_chart tick[{i}]")
            ticks.append(
                {
                    "time": (minutes // 60 % 24, minutes % 60),
                    "price": price,
                    "avg_price": avg,
                    "vol": vol,
                }
            )

        tail_offset = _TICK_HEADER_SIZE + count * _TICK_RECORD_SIZE
        summary: dict = {}
        try:
            (
                name_raw,
                _decimal,
                _category,
                _vol_unit,
                _date_raw,
                _time_raw,
                pre_close,
                open_,
                high,
                low,
                close,
                _momentum_tail,
                vol,
                amount,
                _pad,
                _turnover,
                _avg_tail,
                _industry,
            ) = unpack_from("<44sBHf5x2I5ffIf12s2fI", body, tail_offset, "tick_chart tail")
            summary = {
                "name": decode_gbk(name_raw),
                "code": code_raw.decode("gbk", errors="ignore").replace("\x00", ""),
                "pre_close": pre_close,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "vol": vol,
                "amount": amount,
            }
        except TdxDecodeError:
            # 尾部摘要缺失时仍返回 tick 序列。
            pass
        return {"ticks": ticks, "summary": summary}


class MacSymbolTransactionCmd(Command[list[Transaction]]):
    """MAC 族逐笔成交（0x122F）。

    实测对 CN 市场同样有效（标准协议逐笔 0x0fc5 在部分服务器已无数据）；
    港股股票类市场在 0x122F 数据源未接入（参考 issue #14），查询层路由到
    EX 协议命令。query_date 为 None 时查当日，否则为 YYYYMMDD 整数。
    """

    def __init__(
        self,
        market: int,
        code: str,
        query_date: int | None = None,
        start: int = 0,
        count: int = 1000,
    ) -> None:
        self.market = market
        self.code = code
        self.ymd = query_date or 0
        self.start = start
        self.count = count

    def render(self, head_flag: int) -> bytes:
        body = struct.pack(
            "<H22sIIH10x",
            self.market,
            self.code.encode("gbk"),
            self.ymd,
            self.start,
            self.count,
        )
        return build_mac_request(_SYMBOL_TRANSACTION_MSG_ID, body, head_flag=head_flag)

    def parse(self, body: bytes) -> list[Transaction]:
        (count,) = unpack_from("<H", body, 29, "transaction count")
        records: list[Transaction] = []
        for i in range(count):
            offset = 39 + i * 18
            if offset + 18 > len(body):
                break
            time_sec, price, volume, trade_count, bs_flag = unpack_from(
                "<IfIIH", body, offset, f"transaction item[{i}]"
            )
            records.append(
                Transaction(
                    time=(time_sec // 3600, time_sec % 3600 // 60, time_sec % 60),
                    price=price,
                    volume=float(volume),
                    direction=bs_flag,
                    trade_count=trade_count,
                )
            )
        return records
