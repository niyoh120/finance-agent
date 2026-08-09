from datetime import datetime

from openbb_finance.sources.baostock import _normalize_price_row, _to_baostock_symbol
from openbb_finance.sources.base import infer_market
from openbb_finance.sources.symbols import (
    FUTURES_EXCHANGES,
    FUTURES_MONTH_LETTERS,
    SGE_SPOT_MAP,
    cn_plain_symbol,
    futures_exchange,
    futures_plain_code,
    is_futures_symbol,
    to_openbb_symbol,
)


def test_china_a_share_symbol_normalization():
    assert cn_plain_symbol("600000.SH") == "600000"
    assert cn_plain_symbol("000001.XSHE") == "000001"
    assert to_openbb_symbol("600000.SS") == "600000.XSHG"
    assert to_openbb_symbol("000001.SZ") == "000001.XSHE"
    assert to_openbb_symbol("600000") == "600000.XSHG"


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


def test_futures_exchange_table_covers_all_supported_exchanges():
    assert FUTURES_EXCHANGES == {
        "SHFE": 30,
        "DCE": 29,
        "CZCE": 28,
        "CFFEX": 47,
        "GFEX": 66,
        "COMEX": 16,
        "NYMEX": 17,
        "CBOT": 18,
        "SGE": 46,
    }


def test_futures_month_letters_match_industry_convention():
    assert FUTURES_MONTH_LETTERS == {
        1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
        7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z",
    }


def test_sge_spot_map_covers_core_products():
    assert SGE_SPOT_MAP == {
        "AU.SGE": "Au(T+D)",
        "AG.SGE": "Ag(T+D)",
        "AU9999.SGE": "Au99.99",
    }


def test_futures_symbol_recognition_case_insensitive():
    for symbol in ["rb.SHFE", "RB.SHFE", "rb.shfe", "IF.CFFEX", "GC.COMEX", "AU.SGE"]:
        assert is_futures_symbol(symbol)
        assert futures_exchange(symbol) == symbol.rsplit(".", 1)[-1].upper()


def test_futures_plain_code_uppercases_variety():
    assert futures_plain_code("rb.SHFE") == "RB"
    assert futures_plain_code("si.GFEX") == "SI"
    assert futures_plain_code("Au9999.SGE") == "AU9999"


def test_infer_market_recognizes_futures_suffixes():
    assert infer_market("rb.SHFE") == "future"
    assert infer_market("IF.CFFEX") == "future"
    assert infer_market("GC.COMEX") == "future"
    assert infer_market("AU.SGE") == "future"
    assert infer_market("si.GFEX") == "future"
    # Non-futures symbols unchanged.
    assert infer_market("600000.SH") == "cn"
    assert infer_market("AAPL") == "us"
    assert infer_market("700.HK") == "hk"


def test_infer_market_from_symbol_distinguishes_futures_from_us():
    from openbb_finance.sources.symbols import infer_market_from_symbol

    assert infer_market_from_symbol("GC.COMEX") == "future"
    assert infer_market_from_symbol("AU.SGE") == "future"
    assert infer_market_from_symbol("AAPL") == "us"
