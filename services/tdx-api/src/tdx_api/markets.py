"""服务市场枚举与能力矩阵。

`market` 参数使用服务自有稳定标识（字符串 id），每个市场对应显式数值码
（``service_code``，见 ``/markets`` 响应）。能力矩阵约束全部业务端点的
公开承诺：矩阵中为 false 的组合返回 422 ``unsupported_capability``。

协议市场码映射（移植自参考实现并交叉验证）：
- cn_sh/cn_sz：标准协议市场码（沪=1/深=0）与 MAC 族数据命令同码。
- 其余市场：MAC EX 扩展市场码（ExMarket）。
- cffex 的目录列举在扩展市场全局目录中缺失（参考实现已验证），目录能力为 false，
  行情/K线/逐笔（0x122F）仍可用。

单位与时区说明（诚实标注原则）：
- timezone：协议返回当地墙钟时间且无时区字段。CN/港/境内外期货/SGE 的
  交易墙钟与 Asia/Shanghai 一致（港市无夏令时、UTC+8）；美股墙钟所属时区
  缺少可复核证据，显式标 null（未知）。
- volume_unit：仅标注参考实现已验证的单位（CN K线=股、CN 报价=手×100、
  HK K线=手、US K线=股）；其余标 null（未知），不做未核验的倍数换算。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .tdx.enums import ExMarket, StdMarket


class ApiMarket(str, Enum):
    """服务对外市场标识（/markets 返回完整清单）。"""

    CN_SH = "cn_sh"
    CN_SZ = "cn_sz"
    HK = "hk"
    HK_GEM = "hk_gem"
    US = "us"
    INTL_INDEX = "intl_index"
    HK_INDEX = "hk_index"
    SHFE = "shfe"
    DCE = "dce"
    CZCE = "czce"
    CFFEX = "cffex"
    GFEX = "gfex"
    COMEX = "comex"
    NYMEX = "nymex"
    CBOT = "cbot"
    SGE = "sge"


#: K 线/会话协议类别。
PROTOCOL_STANDARD = "standard"  # 标准 TDX（A 股目录/财务/XDXR/分时/逐笔）
PROTOCOL_MAC = "mac"  # MAC（A 股行情）
PROTOCOL_MAC_EX = "mac_ex"  # MAC EX（港美股/指数/期货）


@dataclass(frozen=True)
class MarketSpec:
    """单市场能力规格。"""

    market: ApiMarket
    service_code: int
    label: str
    #: 行情/K线/搜索/信息等业务命令所属会话。
    protocol: str
    #: 标准协议市场码（仅 CN 市场使用）。
    std_market: StdMarket | None
    #: MAC EX 扩展市场码（仅 EX 市场使用）。
    ex_market: ExMarket | None
    #: 港股股票类市场（逐笔走 EX 协议 0x23fc/0x2406）。
    hk_stock_market: bool = False
    timezone: str | None = None
    currency: str = ""
    #: K 线成交量单位；None=未验证。
    kline_volume_unit: str | None = None
    #: 报价成交量单位；None=未验证。
    quote_volume_unit: str | None = None
    #: 报价手数（lot size），仅已知时给出。
    lot_size: int | None = None
    quotes: bool = True
    klines: bool = True
    intraday: bool = False
    transactions: bool = False
    instruments: bool = False
    instrument_search: bool = False
    instrument_info: bool = True
    finance: bool = False
    xdxr: bool = False
    #: 支持的复权方式。
    adjust: tuple[str, ...] = ("none",)


#: 周期能力（当前三类会话同构；显式列出以便未来按市场收窄）。
SUPPORTED_INTERVALS: tuple[str, ...] = ("1m", "5m", "15m", "30m", "60m", "1d", "1w", "1M")

_CN_ADJUST: tuple[str, ...] = ("none", "qfq")
_STOCK_ADJUST: tuple[str, ...] = ("none", "qfq")

_MARKETS: tuple[MarketSpec, ...] = (
    MarketSpec(
        market=ApiMarket.CN_SH,
        service_code=0,
        label="上海证券交易所",
        protocol=PROTOCOL_MAC,
        std_market=StdMarket.SH,
        ex_market=None,
        timezone="Asia/Shanghai",
        currency="CNY",
        kline_volume_unit="share",
        quote_volume_unit="lot",
        lot_size=100,
        intraday=True,
        transactions=True,
        instruments=True,
        instrument_search=True,
        finance=True,
        xdxr=True,
        adjust=_CN_ADJUST,
    ),
    MarketSpec(
        market=ApiMarket.CN_SZ,
        service_code=1,
        label="深圳证券交易所",
        protocol=PROTOCOL_MAC,
        std_market=StdMarket.SZ,
        ex_market=None,
        timezone="Asia/Shanghai",
        currency="CNY",
        kline_volume_unit="share",
        quote_volume_unit="lot",
        lot_size=100,
        intraday=True,
        transactions=True,
        instruments=True,
        instrument_search=True,
        finance=True,
        xdxr=True,
        adjust=_CN_ADJUST,
    ),
    MarketSpec(
        market=ApiMarket.HK,
        service_code=2,
        label="香港联合交易所主板",
        protocol=PROTOCOL_MAC_EX,
        std_market=None,
        ex_market=ExMarket.HK_MAIN_BOARD,
        hk_stock_market=True,
        timezone="Asia/Shanghai",
        currency="HKD",
        kline_volume_unit="lot",
        quote_volume_unit=None,
        intraday=True,
        transactions=True,
        instruments=True,
        instrument_search=True,
        adjust=_STOCK_ADJUST,
    ),
    MarketSpec(
        market=ApiMarket.HK_GEM,
        service_code=3,
        label="香港联合交易所创业板",
        protocol=PROTOCOL_MAC_EX,
        std_market=None,
        ex_market=ExMarket.HK_GEM,
        hk_stock_market=True,
        timezone="Asia/Shanghai",
        currency="HKD",
        kline_volume_unit="lot",
        quote_volume_unit=None,
        intraday=True,
        transactions=True,
        instruments=True,
        instrument_search=True,
        adjust=_STOCK_ADJUST,
    ),
    MarketSpec(
        market=ApiMarket.US,
        service_code=4,
        label="美国股票（NASDAQ/NYSE 等）",
        protocol=PROTOCOL_MAC_EX,
        std_market=None,
        ex_market=ExMarket.US_STOCK,
        timezone=None,  # 墙钟时区缺少可复核证据，显式未知
        currency="USD",
        kline_volume_unit="share",
        quote_volume_unit=None,
        intraday=True,
        transactions=True,
        instruments=True,
        instrument_search=True,
        adjust=_STOCK_ADJUST,
    ),
    MarketSpec(
        market=ApiMarket.INTL_INDEX,
        service_code=5,
        label="国际指数（SPX/DJI/IXIC/NDX）",
        protocol=PROTOCOL_MAC_EX,
        std_market=None,
        ex_market=ExMarket.INTL_INDEX,
        timezone=None,
        currency="USD",
        kline_volume_unit=None,
        quote_volume_unit=None,
        instruments=True,
        instrument_search=True,
    ),
    MarketSpec(
        market=ApiMarket.HK_INDEX,
        service_code=6,
        label="香港指数（恒生/国企/恒生科技）",
        protocol=PROTOCOL_MAC_EX,
        std_market=None,
        ex_market=ExMarket.HK_INDEX,
        hk_stock_market=True,
        timezone="Asia/Shanghai",
        currency="HKD",
        kline_volume_unit=None,
        quote_volume_unit=None,
        intraday=True,
        transactions=True,
        instruments=True,
        instrument_search=True,
    ),
    MarketSpec(
        market=ApiMarket.SHFE,
        service_code=7,
        label="上海期货交易所",
        protocol=PROTOCOL_MAC_EX,
        std_market=None,
        ex_market=ExMarket.SHFE_FUTURES,
        timezone="Asia/Shanghai",
        currency="CNY",
        kline_volume_unit=None,
        quote_volume_unit=None,
        intraday=True,
        transactions=True,
        instruments=True,
        instrument_search=True,
    ),
    MarketSpec(
        market=ApiMarket.DCE,
        service_code=8,
        label="大连商品交易所",
        protocol=PROTOCOL_MAC_EX,
        std_market=None,
        ex_market=ExMarket.DCE_FUTURES,
        timezone="Asia/Shanghai",
        currency="CNY",
        kline_volume_unit=None,
        quote_volume_unit=None,
        intraday=True,
        transactions=True,
        instruments=True,
        instrument_search=True,
    ),
    MarketSpec(
        market=ApiMarket.CZCE,
        service_code=9,
        label="郑州商品交易所",
        protocol=PROTOCOL_MAC_EX,
        std_market=None,
        ex_market=ExMarket.CZCE_FUTURES,
        timezone="Asia/Shanghai",
        currency="CNY",
        kline_volume_unit=None,
        quote_volume_unit=None,
        intraday=True,
        transactions=True,
        instruments=True,
        instrument_search=True,
    ),
    MarketSpec(
        market=ApiMarket.CFFEX,
        service_code=10,
        label="中国金融期货交易所",
        protocol=PROTOCOL_MAC_EX,
        std_market=None,
        ex_market=ExMarket.CFFEX_FUTURES,
        timezone="Asia/Shanghai",
        currency="CNY",
        kline_volume_unit=None,
        quote_volume_unit=None,
        intraday=True,
        transactions=True,
        instruments=False,  # 目录缺失（参考实现已验证），行情/K线/逐笔可用
        instrument_info=False,
    ),
    MarketSpec(
        market=ApiMarket.GFEX,
        service_code=11,
        label="广州期货交易所",
        protocol=PROTOCOL_MAC_EX,
        std_market=None,
        ex_market=ExMarket.GFEX_FUTURES,
        timezone="Asia/Shanghai",
        currency="CNY",
        kline_volume_unit=None,
        quote_volume_unit=None,
        intraday=True,
        transactions=True,
        instruments=True,
        instrument_search=True,
    ),
    MarketSpec(
        market=ApiMarket.COMEX,
        service_code=12,
        label="纽约 COMEX 期货",
        protocol=PROTOCOL_MAC_EX,
        std_market=None,
        ex_market=ExMarket.COMEX_FUTURES,
        timezone=None,  # 夜盘跨自然日，墙钟时区未验证
        currency="USD",
        kline_volume_unit=None,
        quote_volume_unit=None,
        intraday=True,
        transactions=True,
        instruments=True,
        instrument_search=True,
    ),
    MarketSpec(
        market=ApiMarket.NYMEX,
        service_code=13,
        label="纽约 NYMEX 期货",
        protocol=PROTOCOL_MAC_EX,
        std_market=None,
        ex_market=ExMarket.NYMEX_FUTURES,
        timezone=None,
        currency="USD",
        kline_volume_unit=None,
        quote_volume_unit=None,
        intraday=True,
        transactions=True,
        instruments=True,
        instrument_search=True,
    ),
    MarketSpec(
        market=ApiMarket.CBOT,
        service_code=14,
        label="芝加哥 CBOT 期货",
        protocol=PROTOCOL_MAC_EX,
        std_market=None,
        ex_market=ExMarket.CBOT_FUTURES,
        timezone=None,
        currency="USD",
        kline_volume_unit=None,
        quote_volume_unit=None,
        intraday=True,
        transactions=True,
        instruments=True,
        instrument_search=True,
    ),
    MarketSpec(
        market=ApiMarket.SGE,
        service_code=15,
        label="上海黄金交易所（现货递延）",
        protocol=PROTOCOL_MAC_EX,
        std_market=None,
        ex_market=ExMarket.SH_GOLD,
        timezone="Asia/Shanghai",
        currency="CNY",
        kline_volume_unit=None,
        quote_volume_unit=None,
        instruments=True,
        instrument_search=True,
    ),
)

#: market id → 规格。
MARKETS: dict[str, MarketSpec] = {spec.market.value: spec for spec in _MARKETS}

#: 原生代码 → (市场, 规格) 反查表（/markets 响应与指数代码映射用）。
INTL_INDEX_CODES: dict[str, str] = {
    "SPX": "A_SPX",
    "DJI": "A_DJI",
    "IXIC": "A_IXIC",
    "NDX": "A_NDX",
}
HK_INDEX_CODES: dict[str, str] = {
    "HSI": "HSI",
    "HSCEI": "HZ5014",
    "HSTECH": "HZ5017",
}


def get_spec(market: str) -> MarketSpec | None:
    """按服务市场 id 取规格。"""
    return MARKETS.get(market)


def require_spec(market: str) -> MarketSpec:
    """按服务市场 id 取规格；未知市场抛 ``KeyError``（HTTP 层转 422）。"""
    spec = MARKETS.get(market)
    if spec is None:
        raise KeyError(market)
    return spec


def markets_payload() -> list[dict]:
    """/markets 响应 data：市场清单与能力矩阵。"""
    items: list[dict] = []
    for spec in _MARKETS:
        items.append(
            {
                "market": spec.market.value,
                "service_code": spec.service_code,
                "label": spec.label,
                "protocol": spec.protocol,
                "timezone": spec.timezone,
                "currency": spec.currency,
                "intervals": list(SUPPORTED_INTERVALS),
                "adjust": list(spec.adjust),
                "capabilities": {
                    "quotes": spec.quotes,
                    "klines": spec.klines,
                    "intraday": spec.intraday,
                    "transactions": spec.transactions,
                    "instruments": spec.instruments,
                    "instrument_search": spec.instrument_search,
                    "instrument_info": spec.instrument_info,
                    "finance": spec.finance,
                    "xdxr": spec.xdxr,
                },
                "units": {
                    "kline_volume": spec.kline_volume_unit,
                    "quote_volume": spec.quote_volume_unit,
                    "quote_lot_size": spec.lot_size,
                    "amount_currency": spec.currency,
                },
                "protocol_market_code": spec.ex_market if spec.ex_market is not None else spec.std_market,
            }
        )
    return items
