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
