"""Live 冒烟（opt-in）：对真实行情服务器的小规模验证。

仅 ``pytest -m live`` 时运行（``mise run tdx-api-test-live``）。
用例规模刻意保持很小：每市场一只代表性标的 + 一段短 K 线。
对外网/服务器可用性敏感的断言放宽为「结构正确」；
结构性破坏（字段缺失、时间乱序、非正价格）仍然失败。
"""

from __future__ import annotations

import pytest
from tdx_api.client import TdxService
from tdx_api.config import Config
from tdx_api.markets import get_spec

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def service() -> TdxService:
    return TdxService(Config.from_env())


def _kline_asserts(result, min_count: int = 3):
    data = result["data"]
    assert len(data) >= min_count
    stamps = [row["trade_date"] for row in data]
    assert stamps == sorted(stamps)
    for row in data:
        for field in ("open", "high", "low", "close"):
            assert row[field] is None or row[field] >= 0


def test_cn_daily_raw_and_qfq(service: TdxService):
    spec = get_spec("cn_sh")
    raw = service.klines(spec, "600000", "1d", "none", 0, 10)
    _kline_asserts(raw)
    assert raw["meta"]["volume_unit"] == "share"

    qfq = service.klines(spec, "600000", "1d", "qfq", 0, 10)
    _kline_asserts(qfq)
    assert qfq["meta"]["adjustment_source"] in ("server", "local_xdxr")
    # 两段收盘在重叠区间应同向且量级一致（复权不改变最新一段）
    assert abs((raw["data"][-1]["close"] or 0) - (qfq["data"][-1]["close"] or 0)) < 1e-6


def test_cn_quotes_batch(service: TdxService):
    spec = get_spec("cn_sh")
    result = service.quotes(spec, ["600000", "600036"])
    codes = {row["code"] for row in result["data"]}
    assert {"600000", "600036"} <= codes
    for row in result["data"]:
        assert row["pre_close"] is None or row["pre_close"] > 0


def test_cn_finance_and_xdxr(service: TdxService):
    spec = get_spec("cn_sh")
    finance = service.finance(spec, "600000")
    assert finance["data"] is not None
    assert finance["data"]["total_shares_wan"] > 0

    xdxr = service.xdxr(spec, "600000")
    assert xdxr["meta"]["complete"] is True
    assert all(row["date"] >= "1990-01-01" for row in xdxr["data"])


def test_cn_instruments_list_and_search(service: TdxService):
    spec = get_spec("cn_sh")
    instruments = service.instruments(spec, 0, 20)
    assert len(instruments["data"]) == 20
    assert instruments["meta"]["total"] > 20
    search = service.instrument_search(spec, "600000", 0, 5)
    assert any(row["code"] == "600000" for row in search["data"])


def test_cn_intraday_today(service: TdxService):
    spec = get_spec("cn_sz")
    result = service.intraday(spec, "000001", None)
    # 盘中约 120+ 条，收盘后 240 条；时间从 09:30 起（区间起点）。
    assert len(result["data"]) >= 100
    assert result["data"][0]["time"] == "09:30"
    assert result["meta"]["name"] == "平安银行"
    assert result["meta"]["pre_close"] and result["meta"]["pre_close"] > 0


def test_hk_kline_and_quote(service: TdxService):
    spec = get_spec("hk")
    kline = service.klines(spec, "00700", "1d", "none", 0, 10)
    _kline_asserts(kline)
    quotes = service.quotes(spec, ["00700"])
    assert quotes["data"], "港股报价无返回"
    assert quotes["data"][0]["code"] == "00700"


def test_hk_kline_qfq_server_source(service: TdxService):
    spec = get_spec("hk")
    result = service.klines(spec, "00700", "1d", "qfq", 0, 10)
    _kline_asserts(result)
    assert result["meta"]["adjustment_source"] == "server"


def test_us_kline(service: TdxService):
    spec = get_spec("us")
    result = service.klines(spec, "AAPL", "1d", "none", 0, 5)
    _kline_asserts(result)


def test_shfe_futures_kline(service: TdxService):
    spec = get_spec("shfe")
    result = service.klines(spec, "RBL8", "1d", "none", 0, 5)
    _kline_asserts(result)


def test_cffex_futures_kline_and_transactions(service: TdxService):
    spec = get_spec("cffex")
    result = service.klines(spec, "IFL0", "1d", "none", 0, 5)
    _kline_asserts(result)
    tx = service.transactions(spec, "IFL0", None, 0, 100)
    assert isinstance(tx["data"], list)


def test_sge_kline(service: TdxService):
    spec = get_spec("sge")
    result = service.klines(spec, "Au(T+D)", "1d", "none", 0, 5)
    _kline_asserts(result)


def test_indices_kline(service: TdxService):
    intl = service.klines(get_spec("intl_index"), "SPX", "1d", "none", 0, 5)
    _kline_asserts(intl)
    hk = service.klines(get_spec("hk_index"), "HSI", "1d", "none", 0, 5)
    _kline_asserts(hk)


def test_ex_instruments_directory(service: TdxService):
    hk = get_spec("hk")
    result = service.instruments(hk, 0, 10)
    assert len(result["data"]) >= 10
    assert result["meta"]["directory_complete"] is True
