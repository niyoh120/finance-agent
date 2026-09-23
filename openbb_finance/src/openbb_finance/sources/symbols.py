"""Symbol normalization helpers for market data sources."""

from __future__ import annotations

from openbb_finance.sources.base import Market

SH_SUFFIXES = {"SH", "SS", "XSHG"}
SZ_SUFFIXES = {"SZ", "XSHE"}

# Known HK index symbols (pure alphabetic, no .HK suffix).
HK_INDEX_SYMBOLS: frozenset[str] = frozenset({"HSI", "HSCEI", "HSTECH"})

# Known US index aliases accepted by index.price.historical. Source-side maps
# translate them per source (schwab _INDEX_SYMBOL_MAP prefixes $, tdx maps
# A_* service codes); RUT/VIX currently have no verified TDX fallback.
US_INDEX_ALIASES: frozenset[str] = frozenset({"SPX", "DJI", "IXIC", "COMPX", "NDX", "RUT", "VIX"})

# Supported futures/SGE exchange short codes. Service-native contract codes are
# owned by the tdx-api consumer mapping in sources/tdx.py; this set only decides
# symbol suffix recognition and routing.
FUTURES_EXCHANGES: frozenset[str] = frozenset(
    {
        "SHFE",  # 上海期货交易所
        "DCE",  # 大连商品交易所
        "CZCE",  # 郑州商品交易所
        "CFFEX",  # 中国金融期货交易所
        "GFEX",  # 广州期货交易所
        "COMEX",  # 纽约COMEX
        "NYMEX",  # 纽约NYMEX
        "CBOT",  # 芝加哥CBOT
        "SGE",  # 上海黄金交易所（现货递延）
    }
)

# Domestic commodity exchanges (month contract <CODE><YYMM>; CFFEX main
# continuous is <CODE>L0, the commodity exchanges use <CODE>L8).
DOMESTIC_FUTURES_EXCHANGES: frozenset[str] = frozenset({"SHFE", "DCE", "CZCE", "CFFEX", "GFEX"})
# International exchanges: main continuous is <CODE>00W, month contract <CODE><YY><letter>.
INTL_FUTURES_EXCHANGES: frozenset[str] = frozenset({"COMEX", "NYMEX", "CBOT"})

# International futures month letter (F=Jan ... Z=Dec, skipping I/L/O) appended
# to <YY> for month contracts, e.g. 2026-12 -> "26Z".
FUTURES_MONTH_LETTERS: dict[int, str] = {
    1: "F",
    2: "G",
    3: "H",
    4: "J",
    5: "K",
    6: "M",
    7: "N",
    8: "Q",
    9: "U",
    10: "V",
    11: "X",
    12: "Z",
}
FUTURES_MONTH_NUMBERS: dict[str, int] = {letter: month for month, letter in FUTURES_MONTH_LETTERS.items()}

# SGE (上海黄金交易所) spot-deferred products. These are not futures main
# continuous contracts: each maps to a fixed tdx-api native code and has no
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


def require_futures_exchange(symbol: str) -> str:
    """Validate a futures command symbol and return its exchange short code.

    Futures commands (quote/historical) require <CODE>.<EXCHANGE> with an
    exchange we cover. Unknown-suffix symbols like DX.NYBOT or bare ones like
    VIX would otherwise be inferred as US equities and routed to the US stock
    market, silently returning unrelated stock data (e.g. Dynex Capital for
    DX.NYBOT), so reject them up front with the supported exchange list.
    """
    exchange = futures_exchange(symbol)
    if exchange is not None:
        return exchange
    value = symbol.strip().upper()
    _, suffix = split_symbol(value)
    supported = ", ".join(sorted(FUTURES_EXCHANGES))
    if suffix is None:
        raise ValueError(
            f"Invalid futures symbol {value!r}: expected <CODE>.<EXCHANGE>, e.g. rb.SHFE or GC.COMEX; "
            f"supported exchanges: {supported}"
        )
    raise ValueError(
        f"Invalid futures symbol {value!r}: unsupported exchange {suffix!r}; "
        f"supported exchanges: {supported}. Use futures.search to discover available contracts."
    )


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


def _clean_symbol(value: str) -> str:
    return value.strip().upper()


def _cn_index_canonical(code: str, suffix: str | None) -> str | None:
    """Canonical XSHG/XSHE form for a six-digit code, or None when invalid."""
    if suffix in SH_SUFFIXES:
        return f"{code}.XSHG"
    if suffix in SZ_SUFFIXES:
        return f"{code}.XSHE"
    return None


def normalize_index_symbol(symbol: str) -> str:
    """Validate and canonicalize an index symbol (index.price.historical).

    Accepted identities:
    - CN indices: six-digit code with an explicit exchange suffix
      (``000300.sh``/``.SS``/``.XSHG`` -> ``000300.XSHG``; ``399006.sz`` ->
      ``399006.XSHE``). Bare six-digit codes are rejected: ``000001`` is
      ambiguous (上证指数 vs 平安银行), so the suffix is mandatory — use
      index.search / index.available to discover full symbols.
    - US indices: the known aliases SPX/DJI/IXIC/COMPX/NDX/RUT/VIX; a leading
      ``$`` (Schwab wire form) is accepted and stripped.
    - HK indices: HSI/HSCEI/HSTECH.

    Anything else — six-digit codes with unknown suffixes (``000300.BAD``,
    unconnected ``.BJ``), unknown alphabetic identifiers, empty or
    multi-symbol input — fails here, before any network request, so an unknown
    index never reaches the common-stock market chains.
    """
    value = _clean_symbol(symbol)
    if not value:
        raise ValueError("index symbol must not be empty; use index.search / index.available to discover symbols")
    if value.startswith("$"):
        value = value[1:].strip()
    code, suffix = split_symbol(value)
    if len(code) == 6 and code.isdigit():
        canonical = _cn_index_canonical(code, suffix)
        if canonical is not None:
            return canonical
        if suffix is None:
            raise ValueError(
                f"ambiguous bare CN index code {value!r}: append the exchange suffix (.XSHG/.XSHE or .SH/.SZ), "
                "or use the full symbol from index.search / index.available"
            )
        raise ValueError(
            f"invalid CN index symbol {value!r}: unsupported exchange suffix {suffix!r}; "
            "use .XSHG/.XSHE (or .SH/.SZ), or pick a full symbol from index.search"
        )
    if code in US_INDEX_ALIASES and suffix is None:
        return code
    if code in HK_INDEX_SYMBOLS and suffix is None:
        return code
    raise ValueError(
        f"unknown index symbol {symbol.strip()!r}; supported forms: CN '<code>.<XSHG|XSHE>' "
        f"(e.g. 000300.XSHG), US aliases {', '.join(sorted(US_INDEX_ALIASES))}, "
        f"HK aliases {', '.join(sorted(HK_INDEX_SYMBOLS))}; discover symbols via index.search / index.available"
    )


def normalize_etf_symbol(symbol: str) -> str:
    """Validate and canonicalize an ETF symbol (etf.historical).

    - CN ETFs: bare six-digit codes keep their market inference (``510300`` ->
      ``510300.XSHG``, ``159915`` -> ``159915.XSHE``; digit-prefix heuristic,
      no security-type directory) and explicit CN suffixes canonicalize;
      six-digit codes with unknown suffixes fail.
    - HK ETFs: digit codes keep the effective source form (``02800.HK``; any
      digit length with an explicit .HK). Bare codes must be five digits —
      shorter bare digit codes would infer the US market and are rejected.
    - US ETFs: alphabetic tickers (SPY/QQQ, internal dots like BRK.B kept)
      pass through with whitespace/case normalization.

    Empty or multi-symbol input fails before any network request. Bare-code
    compatibility only decides the market; it does not verify the security is
    actually an ETF — prefer the full symbol from etf.search results.
    """
    value = _clean_symbol(symbol)
    if not value:
        raise ValueError("ETF symbol must not be empty; use etf.search to discover symbols")
    code, suffix = split_symbol(value)
    if len(code) == 6 and code.isdigit():
        canonical = _cn_index_canonical(code, suffix)
        if canonical is not None:
            return canonical
        if suffix is None:
            # Existing market inference for bare CN codes: 5/6/9 -> Shanghai.
            return to_openbb_symbol(code)
        raise ValueError(
            f"invalid CN ETF symbol {value!r}: unsupported exchange suffix {suffix!r}; "
            "use .XSHG/.XSHE (or .SH/.SZ), or pick a full symbol from etf.search"
        )
    if code.isdigit():
        if suffix == "HK":
            return value
        if suffix is None and len(code) == 5:
            return value
        hint = "; append .HK (e.g. 02800.HK)" if suffix is None else f"; unsupported suffix {suffix!r}"
        raise ValueError(f"invalid HK ETF symbol {value!r}{hint}")
    if code.replace(".", "").isalpha():
        if suffix in SH_SUFFIXES | SZ_SUFFIXES | {"HK"}:
            # An explicit exchange suffix on an alphabetic code is inconsistent
            # (exchange suffixes are a CN/HK digit-code concept); fail instead
            # of treating it as a dotted US ticker.
            raise ValueError(f"invalid ETF symbol {value!r}: exchange suffix {suffix!r} requires a CN/HK digit code")
        # US tickers; internal dots (BRK.B) stay.
        return value
    raise ValueError(
        f"invalid ETF symbol {symbol.strip()!r}; supported forms: CN '<code>.<XSHG|XSHE>' or bare six-digit code, "
        "HK '<code>.HK', US ticker (e.g. SPY); discover symbols via etf.search"
    )


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
