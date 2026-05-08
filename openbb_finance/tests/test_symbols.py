from datetime import datetime

from openbb_finance.sources.baostock import _normalize_price_row, _to_baostock_symbol
from openbb_finance.sources.base import infer_market
from openbb_finance.sources.symbols import cn_plain_symbol, to_openbb_symbol, to_yfinance_symbol


def test_china_a_share_symbol_normalization():
    assert cn_plain_symbol("600000.SH") == "600000"
    assert cn_plain_symbol("000001.XSHE") == "000001"
    assert to_openbb_symbol("600000.SS") == "600000.XSHG"
    assert to_openbb_symbol("000001.SZ") == "000001.XSHE"
    assert to_openbb_symbol("600000") == "600000.XSHG"
    assert to_yfinance_symbol("600000.XSHG") == "600000.SS"
    assert to_yfinance_symbol("000001.SZ") == "000001.SZ"


def test_infer_market_uses_china_symbol_suffixes():
    assert infer_market("600000.SH") == "cn"
    assert infer_market("600000.SS") == "cn"
    assert infer_market("000001.SZ") == "cn"
    assert infer_market("AAPL") == "us"


def test_baostock_symbol_conversion_preserves_exchange_suffix():
    assert _to_baostock_symbol("000001") == "sz.000001"
    assert _to_baostock_symbol("000001.XSHE") == "sz.000001"
    assert _to_baostock_symbol("000001.XSHG") == "sh.000001"
    assert _to_baostock_symbol("399001.XSHE") == "sz.399001"


def test_baostock_intraday_row_preserves_time():
    result = _normalize_price_row(
        {
            "date": "2026-05-06",
            "time": "20260506093500000",
            "open": "1",
            "high": "2",
            "low": "0.5",
            "close": "1.5",
            "volume": "100",
            "amount": "200",
        },
        "000001.XSHE",
    )

    assert result["date"] == datetime(2026, 5, 6, 9, 35)
