"""Symbol normalization helpers for market data sources."""

from __future__ import annotations

from openbb_finance.sources.base import Market

SH_SUFFIXES = {"SH", "SS", "XSHG"}
SZ_SUFFIXES = {"SZ", "XSHE"}

# Known HK index symbols (pure alphabetic, no .HK suffix).
HK_INDEX_SYMBOLS: frozenset[str] = frozenset({"HSI", "HSCEI", "HSTECH"})

# Exchange short code -> easy-tdx ExMarket enum value.
FUTURES_EXCHANGES: dict[str, int] = {
    "SHFE": 30,  # 上海期货交易所
    "DCE": 29,  # 大连商品交易所
    "CZCE": 28,  # 郑州商品交易所
    "CFFEX": 47,  # 中国金融期货交易所
    "GFEX": 66,  # 广州期货交易所
    "COMEX": 16,  # 纽约COMEX
    "NYMEX": 17,  # 纽约NYMEX
    "CBOT": 18,  # 芝加哥CBOT
    "SGE": 46,  # 上海黄金交易所（现货递延）
}

# Domestic commodity exchanges: main continuous is <CODE>L8, month contract <CODE><YYMM>.
DOMESTIC_FUTURES_EXCHANGES: frozenset[str] = frozenset({"SHFE", "DCE", "CZCE", "CFFEX", "GFEX"})
# International exchanges: main continuous is <CODE>00W, month contract <CODE><YY><letter>.
INTL_FUTURES_EXCHANGES: frozenset[str] = frozenset({"COMEX", "NYMEX", "CBOT"})

# International futures month letter (F=Jan ... Z=Dec, skipping I/L/O) appended
# to <YY> for month contracts, e.g. 2026-12 -> "26Z".
FUTURES_MONTH_LETTERS: dict[int, str] = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z",
}
FUTURES_MONTH_NUMBERS: dict[str, int] = {
    letter: month for month, letter in FUTURES_MONTH_LETTERS.items()
}

# SGE (上海黄金交易所) spot-deferred products. These are not futures main
# continuous contracts: each maps to a fixed easy-tdx code and has no
# expiration concept.
SGE_SPOT_MAP: dict[str, str] = {
    "AU.SGE": "Au(T+D)",  # 黄金递延
    "AG.SGE": "Ag(T+D)",  # 白银递延
    "AU9999.SGE": "Au99.99",  # 黄金99.99
}


def split_symbol(symbol: str) -> tuple[str, str | None]:
    value = symbol.strip().upper()
    code, _, suffix = value.partition(".")
    return code, suffix or None


def cn_plain_symbol(symbol: str) -> str | None:
    code, suffix = split_symbol(symbol)
    if len(code) == 6 and code.isdigit() and (suffix is None or suffix in SH_SUFFIXES | SZ_SUFFIXES):
        return code
    return None


def is_cn_symbol(symbol: str) -> bool:
    return cn_plain_symbol(symbol) is not None


def futures_exchange(symbol: str) -> str | None:
    """Return the futures exchange short code (e.g. SHFE) or None."""
    _, suffix = split_symbol(symbol)
    if suffix in FUTURES_EXCHANGES:
        return suffix
    return None


def is_futures_symbol(symbol: str) -> bool:
    return futures_exchange(symbol) is not None


def futures_plain_code(symbol: str) -> str:
    """Uppercase variety code part of a futures symbol, e.g. rb.SHFE -> RB."""
    code, _ = split_symbol(symbol)
    return code


def cn_exchange(symbol: str) -> str | None:
    code = cn_plain_symbol(symbol)
    if code is None:
        return None

    _, suffix = split_symbol(symbol)
    if suffix in SH_SUFFIXES:
        return "sh"
    if suffix in SZ_SUFFIXES:
        return "sz"
    if code.startswith(("5", "6", "9")):
        return "sh"
    return "sz"


def to_openbb_symbol(symbol: str) -> str:
    code = cn_plain_symbol(symbol)
    exchange = cn_exchange(symbol)
    if code and exchange == "sh":
        return f"{code}.XSHG"
    if code and exchange == "sz":
        return f"{code}.XSHE"
    return symbol.strip().upper()


def infer_market_from_symbol(symbol: str) -> Market:
    value = symbol.strip().upper()
    if is_cn_symbol(value):
        return "cn"
    code, suffix = split_symbol(value)
    if suffix in FUTURES_EXCHANGES:
        return "future"
    if suffix == "HK" or (code.isdigit() and len(code) == 5):
        return "hk"
    if code in HK_INDEX_SYMBOLS:
        return "hk"
    return "us"
