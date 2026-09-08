"""标准协议财务与除权除息命令。

移植自 niyoh120/easy_tdx（固定提交 e374a0da2834119ac695c1083805d1b0a60967c2）
的 ``commands/finance_info.py``、``commands/xdxr_info.py``。

审阅要点（与参考实现对齐）：
- finance_info：字段 struct ``<fHHII`` + 30f；金额/股本按万元/万股口径 ×10000。
- xdxr_info：参考 Bug #1 修复保留（逐条从当前偏移读 market/code）；
  category==1 的分红送配原值为「每 10 股」口径，解码层归一化为「每股」；
  股本变动类（5/6/7 等）的 4 个 uint32 使用通达信自定义浮点，解码为万股。
"""

from __future__ import annotations

import struct
from datetime import date as _date

from ...codec.primitives import (
    _decode_volume,
    decode_ascii,
    get_datetime,
    slice_bytes,
    unpack_from,
)
from ...enums import StdMarket
from ...errors import TdxDecodeError
from ...models import FinanceInfo, XdxrRecord
from ..base import Command

_FIN_FMT = "<fHHII" + "f" * 30
_FIN_SIZE = struct.calcsize(_FIN_FMT)

#: 财务数据单位：万元/万股（协议原值 × 10000）。
_FIN_SCALE = 10000.0

#: XDXR category 含义（移植自参考实现 models/finance.py）。
XDXR_CATEGORY_NAMES: dict[int, str] = {
    1: "除权除息",
    2: "送配股上市",
    3: "非流通股上市",
    4: "未知股本变动",
    5: "股本变化",
    6: "增发新股",
    7: "股份回购",
    8: "增发新股上市",
    9: "转配股上市",
    10: "可转债上市",
    11: "扩缩股",
    12: "非流通股缩股",
    13: "送认购权证",
    14: "送认沽权证",
}


class GetFinanceInfoCmd(Command[FinanceInfo]):
    """最新财务数据快照（0x1000 模板）。"""

    def __init__(self, market: StdMarket, code: str) -> None:
        self.market = market
        self.code = code

    def render(self, head_flag: int) -> bytes:
        del head_flag
        header = bytes.fromhex("0c1f187600010b000b0010000100")
        return header + struct.pack("<B6s", int(self.market), self.code.encode("utf-8"))

    def parse(self, body: bytes) -> FinanceInfo:
        pos = 2  # 跳过前 2 字节（记录数）
        market_b, code_b = unpack_from("<B6s", body, pos, "finance_info header")
        pos += 7

        fields = struct.unpack(_FIN_FMT, slice_bytes(body, pos, _FIN_SIZE, "finance_info body"))
        (
            liutong_guben,
            province,
            industry,
            updated_date,
            ipo_date,
            zong_guben,
            guojia_gu,
            faqiren_faren_gu,
            faren_gu,
            b_gu,
            h_gu,
            zhigong_gu,
            zong_zichan,
            liudong_zichan,
            guding_zichan,
            wuxing_zichan,
            gudong_renshu,
            liudong_fuzhai,
            changqi_fuzhai,
            ziben_gongjijin,
            jing_zichan,
            zhuying_shouru,
            zhuying_lirun,
            yingshou_zhangkuan,
            yingye_lirun,
            touzi_shouyu,
            jingying_xianjinliu,
            zong_xianjinliu,
            cunhuo,
            lirun_zonghe,
            shuihou_lirun,
            jing_lirun,
            weifen_lirun,
            meigujing_zichan,
            reserve2,
        ) = fields

        del (
            guojia_gu,
            faqiren_faren_gu,
            faren_gu,
            b_gu,
            h_gu,
            zhigong_gu,
        )

        try:
            market = StdMarket(market_b)
        except ValueError as e:
            raise TdxDecodeError(f"finance_info 非法 market 值: {market_b}") from e

        s = _FIN_SCALE
        return FinanceInfo(
            market=int(market),
            code=decode_ascii(code_b),
            liutong_guben=liutong_guben * s,
            zong_guben=zong_guben * s,
            province=province,
            industry=industry,
            updated_date=updated_date,
            ipo_date=ipo_date,
            gudong_renshu=gudong_renshu,
            zong_zichan=zong_zichan * s,
            liudong_zichan=liudong_zichan * s,
            guding_zichan=guding_zichan * s,
            wuxing_zichan=wuxing_zichan * s,
            liudong_fuzhai=liudong_fuzhai * s,
            changqi_fuzhai=changqi_fuzhai * s,
            ziben_gongjijin=ziben_gongjijin * s,
            jing_zichan=jing_zichan * s,
            zhuying_shouru=zhuying_shouru * s,
            zhuying_lirun=zhuying_lirun * s,
            yingshou_zhangkuan=yingshou_zhangkuan * s,
            yingye_lirun=yingye_lirun * s,
            touzi_shouyu=touzi_shouyu * s,
            jingying_xianjinliu=jingying_xianjinliu * s,
            zong_xianjinliu=zong_xianjinliu * s,
            cunhuo=cunhuo * s,
            lirun_zonghe=lirun_zonghe * s,
            shuihou_lirun=shuihou_lirun * s,
            jing_lirun=jing_lirun * s,
            weifen_lirun=weifen_lirun * s,
            meigujing_zichan=meigujing_zichan,
            reserve2=reserve2,
        )


class GetXdxrInfoCmd(Command[list[XdxrRecord]]):
    """除权除息历史记录（0x0f00 模板）。"""

    def __init__(self, market: StdMarket, code: str) -> None:
        self.market = market
        self.code = code

    def render(self, head_flag: int) -> bytes:
        del head_flag
        header = bytes.fromhex("0c1f187600010b000b000f000100")
        return header + struct.pack("<B6s", int(self.market), self.code.encode("utf-8"))

    def parse(self, body: bytes) -> list[XdxrRecord]:
        if len(body) < 11:
            raise TdxDecodeError("xdxr_info body 过短")

        pos = 9  # 跳过 9 字节（market+code+未知）
        (num,) = unpack_from("<H", body, pos, "xdxr_info header")
        pos += 2

        records: list[XdxrRecord] = []
        for _ in range(num):
            market_b, code_b = unpack_from("<B6s", body, pos, "xdxr_info record header")
            pos += 7
            slice_bytes(body, pos, 1, "xdxr_info record padding")
            pos += 1

            year, month, day, _hour, _min, pos = get_datetime(9, body, pos)
            (category,) = unpack_from("<B", body, pos, "xdxr_info category")
            pos += 1

            chunk = slice_bytes(body, pos, 16, "xdxr_info record body")
            pos += 16
            try:
                StdMarket(market_b)
            except ValueError as e:
                raise TdxDecodeError(f"xdxr_info 非法 market 值: {market_b}") from e

            rec = XdxrRecord(
                market=market_b,
                code=decode_ascii(code_b),
                date=_date(year, month, day),
                category=category,
            )

            if category == 1:
                fenhong, peigujia, songzhuangu, peigu = struct.unpack("<ffff", chunk)
                # 每 10 股口径 → 每股口径（参考实现 _normalize_per_10_shares）。
                rec = XdxrRecord(
                    market=rec.market,
                    code=rec.code,
                    date=rec.date,
                    category=category,
                    fenhong=_per_10(fenhong),
                    peigujia=peigujia,
                    songzhuangu=_per_10(songzhuangu),
                    peigu=_per_10(peigu),
                )
            elif category in (11, 12):
                _, _, suogu, _ = struct.unpack("<IIfI", chunk)
                rec = XdxrRecord(
                    market=rec.market,
                    code=rec.code,
                    date=rec.date,
                    category=category,
                    suogu=suogu,
                )
            elif category in (13, 14):
                xingquanjia, _, fenshu, _ = struct.unpack("<fIfI", chunk)
                rec = XdxrRecord(
                    market=rec.market,
                    code=rec.code,
                    date=rec.date,
                    category=category,
                    xingquanjia=xingquanjia,
                    fenshu=fenshu,
                )
            else:
                ql_raw, qz_raw, hl_raw, hz_raw = struct.unpack("<IIII", chunk)
                rec = XdxrRecord(
                    market=rec.market,
                    code=rec.code,
                    date=rec.date,
                    category=category,
                    panqian_liutong=_decode_volume(ql_raw),
                    qian_zongguben=_decode_volume(qz_raw),
                    panhou_liutong=_decode_volume(hl_raw),
                    hou_zongguben=_decode_volume(hz_raw),
                )

            records.append(rec)

        return records


def _per_10(value: float) -> float:
    """每 10 股口径 → 每股口径。"""
    return value / 10.0
