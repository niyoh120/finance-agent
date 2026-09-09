"""查询层测试：分页、市场路由、QFQ 流程、缓存与主机切换。

使用会话级替身（命令解析后的对象），验证 TdxService 的编排逻辑；
线级编解码由 test_protocol.py 覆盖，HTTP 契约由 test_http.py 覆盖。
"""

from __future__ import annotations

from datetime import datetime

import pytest
from tdx_api.client import TdxService
from tdx_api.errors import (
    AdjustmentUnavailableError,
    BudgetExceededError,
    InvalidParameterError,
    UnsupportedCapabilityError,
    UpstreamUnavailableError,
)
from tdx_api.markets import get_spec
from tdx_api.tdx.commands.ex.extended import (
    GetExInstrumentCountCmd,
    GetExInstrumentInfoCmd,
    GetExTransactionDataCmd,
)
from tdx_api.tdx.commands.mac.symbols import (
    MacSymbolInfoCmd,
    MacSymbolQuotesCmd,
    MacSymbolTransactionCmd,
)
from tdx_api.tdx.commands.standard.fundamentals import GetFinanceInfoCmd, GetXdxrInfoCmd
from tdx_api.tdx.commands.standard.securities import (
    GetSecurityCountCmd,
    GetSecurityListCmd,
)
from tdx_api.tdx.enums import Adjust, MacPeriod
from tdx_api.tdx.errors import TdxConnectionError, TdxDecodeError
from tdx_api.tdx.hosts import HostSelector
from tdx_api.tdx.models import (
    ExInstrumentInfo,
    MacQuote,
    MacSymbolInfo,
    SecurityListEntry,
    Transaction,
    XdxrRecord,
)
from tdx_fakes import FakeSession, fake_factory, make_config

SH = get_spec("cn_sh")
HK = get_spec("hk")
SHFE = get_spec("shfe")
CFFEX = get_spec("cffex")
SGE = get_spec("sge")


def make_service(factory, **kwargs) -> TdxService:
    config = kwargs.pop("config", None)
    selector = kwargs.pop("selector", None)
    cfg = config or make_config(**kwargs)
    return TdxService(cfg, selector=selector, factory=factory)


def day(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _bar(d, close, vol=100.0):
    stamp = day(d) if len(d) == 10 else d
    return {"datetime": stamp, "open": close, "high": close, "low": close, "close": close, "vol": vol, "amount": vol}


def _bars_handlers(daily_none, daily_qfq=None, min1=None, min1_qfq=None, weekly=None):
    """K 线命令假分页：history 升序全量，按 TDX 语义切片（start=0 最新段）。"""

    def dispatch(cmd):
        if cmd.period == MacPeriod.DAILY:
            history = daily_qfq if (daily_qfq is not None and cmd.fq == Adjust.QFQ) else daily_none
        elif cmd.period == MacPeriod.MIN_1:
            if cmd.fq == Adjust.QFQ and min1_qfq is not None:
                history = min1_qfq
            else:
                assert min1 is not None, "未提供分钟线数据"
                history = min1
        else:
            assert weekly is not None, "未提供周/月线数据"
            history = weekly
        end = len(history) - cmd.start
        return history[max(end - cmd.count, 0) : end]

    return {MacSymbolBarCmd_Cls: dispatch}


from tdx_api.tdx.commands.mac.symbols import MacSymbolBarCmd as MacSymbolBarCmd_Cls  # noqa: E402

# --------------------------------------------------------------------- #
# K 线
# --------------------------------------------------------------------- #


def test_klines_cn_none_returns_ascending_with_paging_meta():
    history = [_bar(f"2024-01-{d:02d}", 10.5) for d in range(1, 6)]
    service = make_service(fake_factory(_bars_handlers(history)))
    result = service.klines(SH, "600000", "1d", "none", 0, 3)
    data = result["data"]
    assert [row["trade_date"] for row in data] == ["2024-01-03", "2024-01-04", "2024-01-05"]
    meta = result["meta"]
    assert meta["offset"] == 0 and meta["count"] == 3
    assert meta["next_offset"] == 3
    assert meta["complete"] is False  # 满页无法证明结束
    assert meta["adjustment_source"] is None
    assert meta["volume_unit"] == "share"  # CN 日线量单位（参考实现验证口径）


def test_klines_cn_offset_window_and_complete():
    history = [_bar(f"2024-01-{d:02d}", 10.5) for d in range(1, 6)]
    service = make_service(fake_factory(_bars_handlers(history)))
    result = service.klines(SH, "600000", "1d", "none", 3, 5)
    data = result["data"]
    # 跳过最新 3 根（01-05/04/03），历史只剩 01-01/01-02 两根。
    assert [row["trade_date"] for row in data] == ["2024-01-01", "2024-01-02"]
    assert result["meta"]["complete"] is True  # 历史尽头短页
    assert result["meta"]["next_offset"] is None


def test_klines_cn_qfq_server_clean_marks_source():
    history = [_bar("2024-01-04", 10.5), _bar("2024-01-05", 10.6)]
    service = make_service(fake_factory(_bars_handlers(history, daily_qfq=history)))
    result = service.klines(SH, "600000", "1d", "qfq", 0, 100)
    assert result["meta"]["adjustment_source"] == "server"
    assert result["meta"]["adjust"] == "qfq"


def test_klines_cn_qfq_no_actions_from_explicit_empty_query():
    """无公司行动的服务端 QFQ 正常返回 server 来源；空查询结果显式保留。"""
    history = [_bar("2024-01-04", 10.5), _bar("2024-01-05", 10.6)]
    handlers = _bars_handlers(history, daily_qfq=history)
    handlers[GetXdxrInfoCmd] = lambda cmd: []  # 成功且明确的空 XDXR
    service = make_service(fake_factory(handlers))
    result = service.klines(SH, "600000", "1d", "qfq", 0, 100)
    assert result["meta"]["adjustment_source"] == "server"


def test_klines_cn_qfq_anomaly_triggers_local_recompute():
    """服务端 QFQ 出现负价 → 补取原始 K 线 + XDXR 本地重算。"""
    raw_history = [
        _bar("2024-01-04", 20.0),
        _bar("2024-01-05", 19.5),
    ]
    bad_qfq = [{**row, "open": -3.0, "high": -2.0, "low": -4.0, "close": -3.5} for row in raw_history]
    xdxr = [XdxrRecord(market=1, code="600000", date=datetime(2024, 1, 5).date(), category=1, fenhong=0.5)]

    handlers = _bars_handlers(raw_history, daily_qfq=bad_qfq)
    handlers[GetXdxrInfoCmd] = lambda cmd: xdxr
    service = make_service(fake_factory(handlers))
    result = service.klines(SH, "600000", "1d", "qfq", 0, 100)

    meta = result["meta"]
    assert meta["adjustment_source"] == "local_xdxr"
    assert meta["adjustment_events"] == 1
    # 01-04 早于除权日：×(20-0.5)/20 = 0.975 → 19.5；01-05 为除权日：原样 19.5。
    assert result["data"][0]["close"] == pytest.approx(19.5)
    assert result["data"][1]["close"] == pytest.approx(19.5)


def test_klines_cn_qfq_xdxr_unavailable_is_explicit_failure():
    """服务端 QFQ 异常且 XDXR 上游不可用 → adjustment_unavailable（502）。"""
    bad_qfq = [_bar("2024-01-05", -3.5)]
    raw_history = [_bar("2024-01-05", 10.0)]
    handlers = _bars_handlers(raw_history, daily_qfq=bad_qfq)

    def run_with_xdxr_down(kind, budget, fn):
        if kind == "standard":
            raise UpstreamUnavailableError("standard down")
        # mac 请求也走默认成功路径（bars handler）
        return _fake_run(handlers, kind, budget, fn)

    service = make_service(fake_factory(handlers))
    service._run = run_with_xdxr_down
    with pytest.raises(AdjustmentUnavailableError):
        service.klines(SH, "600000", "1d", "qfq", 0, 100)


def _fake_run(handlers, kind, budget, fn):
    session = FakeSession(handlers)
    try:
        return fn(session)
    finally:
        session.close()


def test_klines_cn_qfq_invalid_factor_is_explicit_failure():
    """缺前收盘 → 因子非法 → adjustment_unavailable（502），静默跳过被禁止。"""
    bad_qfq = [_bar("2024-01-05", -3.5)]
    # 原始窗口包含除权日前一根 bar（01-04），但该 bar 缺收盘价 → 因子非法。
    raw_history = [
        {"datetime": day("2024-01-04"), "open": 20, "high": 20, "low": 20, "close": None, "vol": 1, "amount": 1},
        {"datetime": day("2024-01-05"), "open": 19.5, "high": 19.5, "low": 19.5, "close": 19.5, "vol": 1, "amount": 1},
    ]
    xdxr = [XdxrRecord(market=1, code="600000", date=datetime(2024, 1, 5).date(), category=1, fenhong=0.5)]
    handlers = _bars_handlers(raw_history, daily_qfq=bad_qfq)
    handlers[GetXdxrInfoCmd] = lambda cmd: xdxr
    service = make_service(fake_factory(handlers))
    with pytest.raises(AdjustmentUnavailableError):
        service.klines(SH, "600000", "1d", "qfq", 0, 100)


def test_klines_cn_weekly_qfq_aggregates_from_adjusted_daily():
    """周线本地重算：原始日线复权后聚合周线（计划要求路径）。"""
    rows = [
        ("2024-01-02", 20.0),
        ("2024-01-03", 20.0),
        ("2024-01-04", 20.0),
        ("2024-01-05", 19.5),
        ("2024-01-08", 19.5),
        ("2024-01-09", 19.6),
    ]
    raw_history = [_bar(d, c) for d, c in rows]
    bad_qfq = [{**row, "close": -1.0, "open": -1.0, "high": -1.0, "low": -1.0} for row in raw_history]
    xdxr = [XdxrRecord(market=1, code="600000", date=datetime(2024, 1, 5).date(), category=1, fenhong=0.5)]

    # 服务端周线 QFQ 直接返回异常值 → 触发本地「日线复权后聚合」路径。
    weekly_bad = [_bar("2024-01-05", -1.0), _bar("2024-01-09", -1.0)]
    handlers = _bars_handlers(raw_history, daily_qfq=bad_qfq, weekly=weekly_bad)
    handlers[GetXdxrInfoCmd] = lambda cmd: xdxr
    service = make_service(fake_factory(handlers))
    result = service.klines(SH, "600000", "1w", "qfq", 0, 10)

    meta = result["meta"]
    assert meta["adjustment_source"] == "local_xdxr"
    assert meta["period_label"] == "trading_period_end"
    data = result["data"]
    assert len(data) == 2
    # 第 1 周：01-02/03/04 早于除权日 1/5 → ×0.975；周标签 = 周内最后交易日 01-05。
    assert data[0]["trade_date"] == "2024-01-05"
    assert data[0]["open"] == pytest.approx(20.0 * 0.975)
    assert data[0]["close"] == pytest.approx(19.5)  # 周收盘 = 除权日（01-05）bar 原样
    assert data[0]["volume"] == pytest.approx(400.0)  # 4 根日线量合计，不复权
    # 第 2 周：全部 bar 晚于除权日 → 原样。
    assert data[1]["trade_date"] == "2024-01-09"
    assert data[1]["close"] == pytest.approx(19.6)


def test_klines_ex_qfq_bad_prices_fails_explicitly():
    """港美股服务端 QFQ 异常且无本地路径 → 502。"""
    bad_qfq = [_bar("2024-01-05", -1.0)]
    service = make_service(fake_factory(_bars_handlers([], daily_qfq=bad_qfq)))
    with pytest.raises(AdjustmentUnavailableError):
        service.klines(HK, "00700", "1d", "qfq", 0, 100)


def test_klines_minute_qfq_applies_factors_by_day():
    """分钟线本地重算：日线因子链按交易日应用。"""
    min1_raw = [
        {
            "datetime": datetime(2024, 1, 4, 9, 31),
            "open": 20,
            "high": 20,
            "low": 20,
            "close": 20,
            "vol": 10,
            "amount": 10,
        },
        {
            "datetime": datetime(2024, 1, 5, 9, 31),
            "open": 19.5,
            "high": 19.5,
            "low": 19.5,
            "close": 19.5,
            "vol": 10,
            "amount": 10,
        },
    ]  # noqa: E501
    bad_qfq = [{**row, "close": -1.0} for row in min1_raw]
    daily = [_bar("2024-01-04", 20.0), _bar("2024-01-05", 19.5)]
    xdxr = [XdxrRecord(market=1, code="600000", date=datetime(2024, 1, 5).date(), category=1, fenhong=0.5)]

    handlers = _bars_handlers(daily, min1=min1_raw, min1_qfq=bad_qfq)
    handlers[GetXdxrInfoCmd] = lambda cmd: xdxr
    service = make_service(fake_factory(handlers))
    result = service.klines(SH, "600000", "1m", "qfq", 0, 10)
    data = result["data"]
    assert data[0]["close"] == pytest.approx(19.5)  # 20 × 0.975
    assert data[1]["close"] == pytest.approx(19.5)  # 除权日分钟线原样
    assert result["meta"]["adjustment_source"] == "local_xdxr"
    assert result["meta"]["time_semantics"] == "interval_start"


def test_klines_rejects_unsupported_adjust_and_interval():
    service = make_service(fake_factory({}))
    with pytest.raises(UnsupportedCapabilityError):
        service.klines(SHFE, "RBL8", "1d", "qfq", 0, 10)
    with pytest.raises(InvalidParameterError):
        service.klines(SH, "600000", "2h", "none", 0, 10)


def test_klines_cn_code_validation():
    service = make_service(fake_factory({}))
    with pytest.raises(InvalidParameterError):
        service.klines(SH, "AAPL", "1d", "none", 0, 10)


# --------------------------------------------------------------------- #
# 报价
# --------------------------------------------------------------------- #


def test_quotes_normalizes_fields_and_units():
    def handler(cmd):
        return [
            MacQuote(market=1, code="600000", name="浦发银行", fields={"close": 7.89, "pre_close": 7.9, "vol": 123456}),
            MacQuote(market=1, code="600000", name="", fields={}),
        ]

    service = make_service(fake_factory({MacSymbolQuotesCmd: handler}))
    result = service.quotes(SH, ["600000"])
    row = result["data"][0]
    assert row["price"] == 7.89
    assert row["volume"] == 123456
    assert result["meta"]["volume_unit"] == "lot"  # CN 报价单位=手
    assert result["meta"]["lot_size"] == 100
    assert result["meta"]["count"] == 2
    # 缺失字段 → null（非 0）
    assert result["data"][1]["price"] is None
    assert result["data"][1]["name"] is None


def test_quotes_rejects_over_batch_limit():
    cfg = make_config(quotes_batch_limit=5)
    service = make_service(fake_factory({}), config=cfg)
    with pytest.raises(InvalidParameterError):
        service.quotes(SH, [f"60000{i}" for i in range(6)])


def test_quotes_hk_pads_codes():
    captured = {}

    def handler(cmd):
        captured["stocks"] = cmd.stocks
        return [MacQuote(market=31, code="00700", name="腾讯控股", fields={"close": 300.0})]

    service = make_service(fake_factory({MacSymbolQuotesCmd: handler}))
    result = service.quotes(HK, ["700"])
    assert captured["stocks"][0] == (31, "00700")
    assert result["data"][0]["code"] == "00700"


def test_quotes_intl_index_alias_mapping():
    captured = {}

    def handler(cmd):
        captured["stocks"] = cmd.stocks
        return []

    service = make_service(fake_factory({MacSymbolQuotesCmd: handler}))
    spec = get_spec("intl_index")
    service.quotes(spec, ["SPX"])
    assert captured["stocks"][0][1] == "A_SPX"


def test_quotes_sge_preserves_case():
    captured = {}

    def handler(cmd):
        captured["stocks"] = cmd.stocks
        return []

    service = make_service(fake_factory({MacSymbolQuotesCmd: handler}))
    service.quotes(SGE, ["Au(T+D)"])
    assert captured["stocks"][0][1] == "Au(T+D)"


# --------------------------------------------------------------------- #
# 标的目录
# --------------------------------------------------------------------- #


def _cn_list_handlers(total, entries):
    return {
        GetSecurityCountCmd: lambda cmd: total,
        GetSecurityListCmd: lambda cmd: entries[cmd.start : cmd.start + 1000],
    }


def test_instruments_cn_paging():
    entries = [
        SecurityListEntry(market=1, code=f"60000{i}", name=f"股票{i}", volunit=100, decimal_point=2, pre_close=10.0)
        for i in range(10)
    ]
    service = make_service(fake_factory(_cn_list_handlers(10, entries)))
    result = service.instruments(SH, 0, 4)
    assert len(result["data"]) == 4
    assert result["data"][0]["code"] == "600000"
    assert result["data"][0]["lot_size"] == 100
    assert result["meta"]["next_offset"] == 4
    assert result["meta"]["total"] == 10

    page2 = service.instruments(SH, 8, 4)
    assert [row["code"] for row in page2["data"]] == ["600008", "600009"]
    assert page2["meta"]["complete"] is True  # 短页证明目录尽


def test_instruments_cffex_directory_unsupported():
    service = make_service(fake_factory({}))
    with pytest.raises(UnsupportedCapabilityError):
        service.instruments(CFFEX, 0, 10)


def test_instruments_ex_directory_with_binary_search_and_cache():
    # 全局目录：market 30 两只、market 31 三只、market 47 一只（升序模拟）
    global_list = (
        [ExInstrumentInfo(category=1, market=30, code=f"cu{i}", name="", desc="") for i in range(2)]
        + [ExInstrumentInfo(category=1, market=31, code=f"0{i}700", name=f"港股{i}", desc="") for i in range(3)]
        + [ExInstrumentInfo(category=1, market=47, code="IFL8", name="", desc="")]
    )

    def info_handler(cmd):
        return global_list[cmd.start : cmd.start + cmd.count]

    handlers = {GetExInstrumentInfoCmd: info_handler, GetExInstrumentCountCmd: lambda cmd: len(global_list)}
    service = make_service(fake_factory(handlers))

    result = service.instruments(HK, 0, 2)
    assert [row["code"] for row in result["data"]] == ["00700", "01700"]
    assert result["meta"]["directory_cached"] is False

    # 第二次请求命中缓存
    result2 = service.instruments(HK, 2, 10)
    assert [row["code"] for row in result2["data"]] == ["02700"]
    assert result2["meta"]["directory_cached"] is True
    assert result2["meta"]["complete"] is True


def test_instrument_search_cn_filters_code_and_name():
    entries = [
        SecurityListEntry(market=1, code="600000", name="浦发银行", volunit=100, decimal_point=2, pre_close=10),
        SecurityListEntry(market=1, code="600036", name="招商银行", volunit=100, decimal_point=2, pre_close=30),
        SecurityListEntry(market=1, code="000001", name="上证指数", volunit=100, decimal_point=3, pre_close=3000),
    ]
    service = make_service(fake_factory(_cn_list_handlers(3, entries)))
    result = service.instrument_search(SH, "银行", 0, 10)
    assert sorted(row["code"] for row in result["data"]) == ["600000", "600036"]
    assert result["meta"]["total_matches"] == 2

    result2 = service.instrument_search(SH, "60003", 0, 10)
    assert [row["code"] for row in result2["data"]] == ["600036"]


def test_instrument_info_cn_uses_mac_session():
    def info_handler(cmd):
        return MacSymbolInfo(
            market=1,
            code="600000",
            name="浦发银行",
            time=datetime(2024, 1, 5, 15, 0, 0),
            pre_close=7.9,
            open=7.9,
            high=8.0,
            low=7.8,
            close=7.89,
            vol=123456,
            amount=9.7e8,
        )

    service = make_service(fake_factory({MacSymbolInfoCmd: info_handler}))
    result = service.instrument_info(SH, "600000")
    assert result["data"]["name"] == "浦发银行"
    assert result["data"]["price"] == 7.89
    assert result["meta"]["found"] is True


def test_instrument_info_missing_returns_null_data():
    service = make_service(fake_factory({MacSymbolInfoCmd: lambda cmd: None}))
    result = service.instrument_info(SH, "999999")
    assert result["data"] is None
    assert result["meta"]["found"] is False


# --------------------------------------------------------------------- #
# 分时与逐笔
# --------------------------------------------------------------------- #


def test_intraday_cn_uses_mac_tick_chart():
    """CN 分时走 MAC 0x122D：显式时间（区间起点）+ 均价 + 摘要。"""
    from tdx_api.tdx.commands.mac.symbols import MacSymbolTickChartCmd

    ticks = [
        {"time": (9, 30), "price": 11.72, "avg_price": 11.68, "vol": 31764},
        {"time": (9, 31), "price": 11.72, "avg_price": 11.69, "vol": 4606},
    ]
    chart = {
        "ticks": ticks,
        "summary": {
            "name": "平安银行",
            "pre_close": 11.7,
            "open": 11.66,
            "high": 11.79,
            "low": 11.65,
            "close": 11.75,
            "vol": 430934,
            "amount": 5.0e8,
        },
    }
    service = make_service(fake_factory({MacSymbolTickChartCmd: lambda cmd: chart}))
    result = service.intraday(SH, "000001", None)
    assert [row["time"] for row in result["data"]] == ["09:30", "09:31"]
    assert result["data"][1]["avg_price"] == 11.69
    assert result["meta"]["time_semantics"] == "interval_start"
    assert result["meta"]["period"] == "today"
    assert result["meta"]["name"] == "平安银行"
    assert result["meta"]["pre_close"] == 11.7


def test_intraday_sge_unsupported():
    service = make_service(fake_factory({}))
    with pytest.raises(UnsupportedCapabilityError):
        service.intraday(SGE, "Au(T+D)", None)


def test_transactions_hk_routes_to_ex_protocol():
    captured = {}

    def handler(cmd):
        captured["cmd"] = cmd
        return [Transaction(time=(10, 0, 0), price=0.4314, volume=100, direction=1)]

    service = make_service(fake_factory({GetExTransactionDataCmd: handler}))
    result = service.transactions(HK, "00700", None, 0, 100)
    assert isinstance(captured["cmd"], GetExTransactionDataCmd)
    row = result["data"][0]
    assert row["direction_label"] == "sell"
    assert result["meta"]["order"] == "newest_first"


def test_transactions_cffex_routes_to_mac_122f_on_ex_session():
    captured = {}
    sessions: list[FakeSession] = []

    def handler(cmd):
        captured["cmd"] = cmd
        return [Transaction(time=(9, 30, 0), price=3900.0, volume=2, direction=0)]

    factory = fake_factory({MacSymbolTransactionCmd: handler}, sessions=sessions)
    service = make_service(factory)
    service.transactions(CFFEX, "IFL0", None, 0, 100)
    assert sessions[0].kind == "mac_ex"  # EX 会话执行 0x122F
    assert captured["cmd"].market == 47


def test_transactions_cn_routes_to_mac_122f():
    """CN 逐笔走 MAC 0x122F（标准 0x0fc5 在部分服务器已无数据）。"""
    sessions: list[FakeSession] = []
    rows = [
        Transaction(time=(9, 30, 0), price=10.0, volume=5, direction=0),
        Transaction(time=(9, 30, 1), price=10.0, volume=5, direction=1),
        Transaction(time=(9, 30, 2), price=10.0, volume=5, direction=2),
        Transaction(time=(9, 30, 3), price=10.0, volume=5, direction=7),
    ]
    factory = fake_factory({MacSymbolTransactionCmd: lambda cmd: rows}, sessions=sessions)
    service = make_service(factory)
    result = service.transactions(SH, "600000", None, 0, 100)
    assert sessions[0].kind == "mac"
    labels = [row["direction_label"] for row in result["data"]]
    assert labels == ["buy", "sell", "neutral", None]  # 未知方向标签置 null
    assert result["meta"]["order"] == "newest_first"


# --------------------------------------------------------------------- #
# 财务与 XDXR
# --------------------------------------------------------------------- #


def test_finance_returns_units_meta():
    from tdx_api.tdx.models import FinanceInfo

    info = FinanceInfo(
        market=1,
        code="600000",
        liutong_guben=100.0,
        zong_guben=200.0,
        province=9,
        industry=3,
        updated_date=20240331,
        ipo_date=19991110,
        gudong_renshu=500000,
        zong_zichan=1.0,
        liudong_zichan=1.0,
        guding_zichan=1.0,
        wuxing_zichan=1.0,
        liudong_fuzhai=1.0,
        changqi_fuzhai=1.0,
        ziben_gongjijin=1.0,
        jing_zichan=1.0,
        zhuying_shouru=1.0,
        zhuying_lirun=1.0,
        yingshou_zhangkuan=1.0,
        yingye_lirun=1.0,
        touzi_shouyu=1.0,
        jingying_xianjinliu=1.0,
        zong_xianjinliu=1.0,
        cunhuo=1.0,
        lirun_zonghe=1.0,
        shuihou_lirun=1.0,
        jing_lirun=1.0,
        weifen_lirun=1.0,
        meigujing_zichan=7.5,
        reserve2=0.0,
    )
    service = make_service(fake_factory({GetFinanceInfoCmd: lambda cmd: info}))
    result = service.finance(SH, "600000")
    assert result["data"]["total_shares_wan"] == 200.0
    assert result["data"]["book_value_per_share"] == 7.5
    assert result["meta"]["units"]["monetary"] == "万元(CNY)"


def test_xdxr_endpoint_normalizes_per_10_to_per_share():
    records = [
        XdxrRecord(
            market=1,
            code="600000",
            date=datetime(2024, 1, 5).date(),
            category=1,
            fenhong=0.5,
            peigujia=5.0,
            songzhuangu=0.1,
            peigu=0.2,
        ),
    ]
    service = make_service(fake_factory({GetXdxrInfoCmd: lambda cmd: records}))
    result = service.xdxr(SH, "600000")
    assert result["data"][0]["dividend_per_share"] == 0.5
    assert result["data"][0]["bonus_per_share"] == pytest.approx(0.1)
    assert result["data"][0]["category_name"] == "除权除息"


# --------------------------------------------------------------------- #
# 主机切换与预算
# --------------------------------------------------------------------- #


def _selector_with(hosts_by_kind):
    candidates = {kind: (tuple(hosts), 7709 if kind != "mac_ex" else 7727) for kind, hosts in hosts_by_kind.items()}
    return HostSelector(candidates=candidates, ttl=300.0, clock=lambda: 0.0)


def test_failover_to_next_host_on_connection_error():
    """缓存首选主机建会话失败 → 换下一台并重放查询 → 缓存更新。"""
    selector = _selector_with({"standard": ["8.8.8.8", "127.0.0.1"]})
    selector.mark_good("standard", "8.8.8.8")

    entries = [SecurityListEntry(market=1, code="600000", name="x", volunit=100, decimal_point=2, pre_close=1)]
    handlers = _cn_list_handlers(1, entries)
    calls: list[str] = []

    def factory(kind, host, budget):
        calls.append(host)
        if host == "8.8.8.8":
            raise TdxConnectionError("refused")
        return FakeSession(handlers)

    service = make_service(factory, selector=selector)
    result = service.instruments(SH, 0, 10)
    assert result["data"][0]["code"] == "600000"
    # 每页独立会话（目录连页节流规避）：首个会话失败后其余均落在新主机。
    assert calls[0] == "8.8.8.8"
    assert set(calls[1:]) == {"127.0.0.1"}
    assert service.selector.has_fresh("standard")
    assert service.selector.candidates_for("standard")[0][0] == "127.0.0.1"  # 缓存已切换


def test_all_hosts_down_raises_upstream_unavailable():
    calls: list[str] = []

    def factory(kind, host, budget):
        calls.append(host)
        raise TdxConnectionError("refused")

    cfg = make_config()
    selector = _selector_with({"standard": ["10.0.0.1", "10.0.0.2", "10.0.0.3"]})
    service = TdxService(cfg, selector=selector, factory=factory)
    with pytest.raises(UpstreamUnavailableError):
        service.finance(SH, "600000")
    assert len(calls) == 3  # 1 + max_host_switches(2)


def test_budget_exhausted_raises_504_error():
    cfg = make_config(request_budget_seconds=0.0000001)
    service = TdxService(cfg, factory=fake_factory({}))
    with pytest.raises(BudgetExceededError):
        service.quotes(SH, ["600000"])


def test_decode_error_propagates_immediately():
    def boom(cmd):
        raise TdxDecodeError("truncated")

    cfg = make_config()
    selector = _selector_with({"standard": ["127.0.0.1", "127.0.0.2"]})
    service = TdxService(cfg, selector=selector, factory=fake_factory({GetFinanceInfoCmd: boom}))
    with pytest.raises(TdxDecodeError):
        service.finance(SH, "600000")  # 确定性解析错误直接失败


def test_xdxr_cache_hits_within_ttl():
    calls = {"n": 0}

    def handler(cmd):
        calls["n"] += 1
        return []

    clock = {"t": 0.0}
    cfg = make_config(cache_ttl_seconds=100.0)
    service = TdxService(cfg, factory=fake_factory({GetXdxrInfoCmd: handler}), clock=lambda: clock["t"])
    service.xdxr(SH, "600000")
    service.xdxr(SH, "600000")
    assert calls["n"] == 1  # TTL 内命中缓存
    clock["t"] = 200.0  # 过期
    service.xdxr(SH, "600000")
    assert calls["n"] == 2
