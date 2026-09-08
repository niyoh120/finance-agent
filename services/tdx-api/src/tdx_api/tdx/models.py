"""协议层结果模型（dataclass，服务私有）。

移植自 niyoh120/easy_tdx（固定提交 e374a0da2834119ac695c1083805d1b0a60967c2）
的 ``models/``、``mac/models.py``、``ex/models.py``，仅保留本服务对外
接口需要的字段；协议原始字节切片（_raw）与内部 unknown 字段一律丢弃，
避免把原始数据包内容泄入 HTTP 层。

约定：
- 价格字段保留解码精度（浮点），单位换算在查询层以元数据声明。
- 时间字段拆为 date/time 元组或 datetime，全部为交易所当地墙钟时间，
  时区归属由能力矩阵声明。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date
from datetime import datetime


@dataclass(frozen=True)
class SecurityListEntry:
    """标准协议证券列表条目（0x0450）。"""

    market: int
    code: str
    name: str
    volunit: int  # 每手股数
    decimal_point: int  # 价格小数位数
    pre_close: float


@dataclass(frozen=True)
class MacBar:
    """MAC 族 K 线（0x122E，标准与扩展市场共用）。"""

    datetime: datetime
    open: float
    high: float
    low: float
    close: float
    vol: float
    amount: float


@dataclass(frozen=True)
class MacQuote:
    """MAC 族批量报价行（0x122B）：身份字段 + 请求字段的键值。"""

    market: int
    code: str
    name: str
    fields: dict[str, float | int] = field(default_factory=dict)


@dataclass(frozen=True)
class MacSymbolInfo:
    """MAC 个股简要特征（0x122A）。"""

    market: int
    code: str
    name: str
    time: datetime | None
    pre_close: float
    open: float
    high: float
    low: float
    close: float
    vol: int
    amount: float


@dataclass(frozen=True)
class FinanceInfo:
    """标准协议最新财务快照（0x1000）。金额/股本单位：万元、万股。"""

    market: int
    code: str
    liutong_guben: float  # 流通股本（万股）
    zong_guben: float  # 总股本（万股）
    province: int
    industry: int
    updated_date: int  # YYYYMMDD
    ipo_date: int  # YYYYMMDD
    gudong_renshu: int  # 股东户数
    zong_zichan: float  # 总资产（万元）
    liudong_zichan: float
    guding_zichan: float
    wuxing_zichan: float
    liudong_fuzhai: float
    changqi_fuzhai: float
    ziben_gongjijin: float  # 资本公积金（万元）
    jing_zichan: float  # 净资产（万元）
    zhuying_shouru: float  # 主营收入（万元）
    zhuying_lirun: float
    yingshou_zhangkuan: float
    yingye_lirun: float
    touzi_shouyu: float
    jingying_xianjinliu: float
    zong_xianjinliu: float
    cunhuo: float
    lirun_zonghe: float
    shuihou_lirun: float
    jing_lirun: float  # 净利润（万元）
    weifen_lirun: float
    meigujing_zichan: float  # 每股净资产（元）
    reserve2: float


@dataclass(frozen=True)
class XdxrRecord:
    """标准协议除权除息记录（0x0f00）。

    category 含义（参考实现 XDXR_CATEGORY_NAMES）：
      1=除权除息 2=送配股上市 3=非流通股上市 4=未知股本变动 5=股本变化
      6=增发新股 7=股份回购 8=增发新股上市 9=转配股上市 10=可转债上市
      11=扩缩股 12=非流通股缩股 13=送认购权证 14=送认沽权证

    category==1 时分红送配字段有效，口径为「每股」：
      fenhong=每股分红（元）、peigujia=配股价（元）、
      songzhuangu=每股送转比例、peigu=每股配股比例
      （协议原值为每 10 股口径，解码层按参考实现归一化为每股）。
    """

    market: int
    code: str
    date: _date
    category: int
    fenhong: float | None = None
    peigujia: float | None = None
    songzhuangu: float | None = None
    peigu: float | None = None
    suogu: float | None = None  # category in (11, 12)
    xingquanjia: float | None = None  # category in (13, 14)
    fenshu: float | None = None
    panqian_liutong: float | None = None  # 股本变动类（万股）
    qian_zongguben: float | None = None
    panhou_liutong: float | None = None
    hou_zongguben: float | None = None


@dataclass(frozen=True)
class MinuteBar:
    """分时数据（标准 0x051d/0x0fb4 与 EX 0x240b/0x240c）。

    标准协议无显式时间字段：``index`` 为序号（第 n 分钟），时间由查询层
    按市场交易时段映射并在元数据声明口径；EX 协议带显式 ``time``。
    标准协议无已验证均价字段（协议第二个变长整数疑似均价，含义未验证），
    avg_price 置 None；EX 协议带均价。
    """

    price: float
    vol: float
    index: int | None = None  # 标准协议序号（0 起）
    time: tuple[int, int] | None = None  # EX 协议显式 (hour, minute)
    avg_price: float | None = None
    amount: float | None = None  # EX 协议字段（含义未验证，命名保留）


@dataclass(frozen=True)
class Transaction:
    """逐笔成交明细，统一三类协议的对外语义。

    direction: 0=买 1=卖 2=中性 5=盘后（MAC/EX 原生语义）；
    标准协议 buyorsell 与该语义一致（pytdx/参考实现同口径）。
    trade_count：当日 A 股标准协议有「成交笔数」，其余协议置 None。
    open_interest（zengcang/增仓）：仅 EX 期货逐笔有效。
    price 为已换算的计价货币浮点值。
    """

    time: tuple[int, int, int]  # (hour, minute, second)
    price: float
    volume: float
    direction: int
    trade_count: int | None = None
    open_interest: int | None = None


@dataclass(frozen=True)
class ExInstrumentInfo:
    """EX 协议商品/证券信息（0x23f5）。"""

    category: int
    market: int
    code: str
    name: str
    desc: str
