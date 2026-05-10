"""Symbol normalization helpers for market data sources."""

from __future__ import annotations

from openbb_finance.sources.base import Market

SH_SUFFIXES = {"SH", "SS", "XSHG"}
SZ_SUFFIXES = {"SZ", "XSHE"}

# Non-CN index symbols whose yfinance ticker differs from the OpenBB symbol.
# Maps OpenBB symbol -> yfinance ticker.
# Symbols NOT in this map have no yfinance historical data source;
# they will fall through to the empty-list path and produce EMPTY_DATA.
YFINANCE_INDEX_SYMBOL_MAP: dict[str, str] = {
    # US indices: OpenBB name -> ^SYMBOL
    "SPX": "^SPX",
    "DJI": "^DJI",
    "IXIC": "^IXIC",
    "NDX": "^NDX",
    "RUT": "^RUT",
    "VIX": "^VIX",
    # HK indices
    "HSI": "^HSI",
    "HSCEI": "^HSCE",
    # HSTECH has no yfinance historical data source; deliberately omitted.
}

# Known HK index symbols (pure alphabetic, no .HK suffix).
HK_INDEX_SYMBOLS: frozenset[str] = frozenset({"HSI", "HSCEI", "HSTECH"})


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


def to_yfinance_symbol(symbol: str) -> str:
    code = cn_plain_symbol(symbol)
    exchange = cn_exchange(symbol)
    if code and exchange == "sh":
        return f"{code}.SS"
    if code and exchange == "sz":
        return f"{code}.SZ"
    value = symbol.strip().upper()
    if value in YFINANCE_INDEX_SYMBOL_MAP:
        return YFINANCE_INDEX_SYMBOL_MAP[value]
    return value


def infer_market_from_symbol(symbol: str) -> Market:
    value = symbol.strip().upper()
    if is_cn_symbol(value):
        return "cn"
    code, suffix = split_symbol(value)
    if suffix == "HK" or (code.isdigit() and len(code) == 5):
        return "hk"
    if code in HK_INDEX_SYMBOLS:
        return "hk"
    return "us"
