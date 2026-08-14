"""TDX data source backed by the local easy-tdx SDK."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime
from typing import Any

from easy_tdx import Adjust, ExMarket, MacClient, MacExClient, Period

from openbb_finance.config import SourceConfig
from openbb_finance.sources.base import (
    DataType,
    Market,
    PriceQuery,
    SourceError,
    is_intraday_interval,
    normalize_interval,
)
from openbb_finance.sources.symbols import (
    FUTURES_EXCHANGES,
    FUTURES_MONTH_LETTERS,
    FUTURES_MONTH_NUMBERS,
    INTL_FUTURES_EXCHANGES,
    SGE_SPOT_MAP,
    cn_exchange,
    cn_plain_symbol,
    futures_exchange,
    futures_plain_code,
    split_symbol,
    to_openbb_symbol,
)

CN_MARKET_SZ = 0
CN_MARKET_SH = 1
TDX_COUNT_LIMIT = 700
DEFAULT_TIMEOUT = 15.0
TDX_INDEX_SYMBOLS: dict[str, tuple[int, str]] = {
    "SPX": (ExMarket.INTL_INDEX, "A_SPX"),
    "DJI": (ExMarket.INTL_INDEX, "A_DJI"),
    "IXIC": (ExMarket.INTL_INDEX, "A_IXIC"),
    "NDX": (ExMarket.INTL_INDEX, "A_NDX"),
    "HSI": (ExMarket.HK_INDEX, "HSI"),
    "HSCEI": (ExMarket.HK_INDEX, "HZ5014"),
    "HSTECH": (ExMarket.HK_INDEX, "HZ5017"),
}
logger = logging.getLogger(__name__)


class TdxSource:
    """TDX market data source using easy-tdx local SDK clients."""

    name = "tdx"

    def __init__(self, config: SourceConfig) -> None:
        self.enabled = config.enabled
        self.timeout = DEFAULT_TIMEOUT

    def supports(self, market: Market, data_type: DataType, **kwargs: Any) -> bool:
        del kwargs
        return market in {"cn", "hk", "us", "future"} and data_type in {"price", "search"}

    async def fetch_price(self, query: PriceQuery) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._fetch_price_sync, query)

    async def fetch_quote(self, symbol: str, expiration: str | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(self._fetch_quote_sync, symbol, expiration)

    async def fetch_futures_search(self, query: str, is_symbol: bool | None = None) -> list[dict[str, Any]]:
        """Enumerate easy-tdx futures instruments and match code/name against query.

        easy-tdx does not expose a futures keyword search API; the EX goods_list
        enumerates each exchange's contracts (including L8/00W main continuous
        codes). CFFEX contracts are not present in goods_list, so CFFEX results
        fall through to the akshare fallback in the fetcher.
        """

        return await asyncio.to_thread(self._fetch_futures_search_sync, query, is_symbol)

    async def fetch_equity_search(self, query: str, is_symbol: bool | None = None) -> list[dict[str, Any]]:
        """Return exact-symbol metadata when easy-tdx can resolve it.

        easy-tdx does not expose the broad keyword search API previously used by
        the HTTP TDX service. Keep this method lightweight so existing search
        routing can still fall through to richer sources for name searches.
        """

        if not is_symbol:
            return []
        try:
            return await asyncio.to_thread(self._fetch_exact_symbol_sync, query)
        except SourceError:
            return []
        except Exception:
            logger.warning("TDX exact symbol lookup failed for %r", query, exc_info=True)
            return []

    def _fetch_price_sync(self, query: PriceQuery) -> list[dict[str, Any]]:
        period = _to_tdx_period(query.interval)
        adjust = _to_tdx_adjust(query.adjusted)
        market = query.market

        if market == "cn":
            easy_market, code = _to_cn_market_code(query.symbol)
            with MacClient.from_best_host(timeout=self.timeout) as client:
                frame = client.get_stock_kline(easy_market, code, period, 0, TDX_COUNT_LIMIT, adjust=adjust)
        elif market in {"hk", "us"}:
            easy_market, code = _to_ex_market_code(query.symbol, market)
            with MacExClient.from_best_host(timeout=self.timeout) as client:
                frame = client.goods_kline(easy_market, code, period, 0, TDX_COUNT_LIMIT, adjust=adjust)
        elif market == "future":
            easy_market, code = _to_futures_market_code(query.symbol, query.expiration)
            with MacExClient.from_best_host(timeout=self.timeout) as client:
                frame = client.goods_kline(easy_market, code, period, 0, TDX_COUNT_LIMIT, adjust=adjust)
        else:
            raise SourceError(f"TDX unsupported market: {market}")

        records = [_normalize_price_row(row, query) for row in _iter_frame_rows(frame)]
        return [
            record
            for record in records
            if (query.start_date is None or _as_date(record["date"]) >= query.start_date)
            and (query.end_date is None or _as_date(record["date"]) <= query.end_date)
        ]

    def _fetch_quote_sync(self, symbol: str, expiration: str | None = None) -> dict[str, Any]:
        market = _infer_tdx_market(symbol)
        if market == "cn":
            easy_market, code = _to_cn_market_code(symbol)
            with MacClient.from_best_host(timeout=self.timeout) as client:
                frame = client.get_stock_quotes([(easy_market, code)])
        elif market in {"hk", "us"}:
            easy_market, code = _to_ex_market_code(symbol, market)
            with MacExClient.from_best_host(timeout=self.timeout) as client:
                frame = client.goods_quotes([(easy_market, code)])
        elif market == "future":
            easy_market, code = _to_futures_market_code(symbol, expiration)
            with MacExClient.from_best_host(timeout=self.timeout) as client:
                frame = client.goods_quotes([(easy_market, code)])
        else:
            raise SourceError(f"TDX unsupported market: {market}")

        rows = list(_iter_frame_rows(frame))
        if not rows:
            raise SourceError(f"TDX quote returned no data for {symbol}")
        if market == "future":
            return _normalize_futures_quote(rows[0], symbol)
        return _normalize_quote(rows[0], symbol)

    def _fetch_futures_search_sync(self, query: str, is_symbol: bool | None) -> list[dict[str, Any]]:
        text = query.strip().upper()
        results: list[dict[str, Any]] = []
        with MacExClient.from_best_host(timeout=self.timeout) as client:
            for exchange in FUTURES_EXCHANGES:
                try:
                    frame = client.goods_list(FUTURES_EXCHANGES[exchange], start=0, count=1000)
                except Exception:
                    continue
                for row in _iter_frame_rows(frame):
                    code = str(row.get("code") or "").strip()
                    if not code:
                        continue
                    if not _is_queryable_futures_code(exchange, code):
                        continue
                    symbol, expiration = _futures_contract_symbol(exchange, code)
                    name = str(row.get("name") or "").strip()
                    if _futures_search_match(text, code.upper(), name.upper(), symbol.upper(), is_symbol):
                        results.append(
                            {
                                "symbol": symbol,
                                "expiration": expiration,
                                "code": code,
                                "name": name,
                                "exchange": exchange,
                                "source": "tdx",
                            }
                        )
        return results

    def _fetch_exact_symbol_sync(self, query: str) -> list[dict[str, Any]]:
        market = _infer_tdx_market(query)
        if market != "cn":
            return []
        easy_market, code = _to_cn_market_code(query)
        with MacClient.from_best_host(timeout=self.timeout) as client:
            frame = client.get_symbol_info(easy_market, code)
        rows = list(_iter_frame_rows(frame))
        if not rows:
            return []
        name = str(rows[0].get("name") or "").strip()
        return [{"symbol": to_openbb_symbol(query), "name": name, "source": "tdx"}]


def _infer_tdx_market(symbol: str) -> Market:
    from openbb_finance.sources.base import infer_market

    return infer_market(symbol)


def _to_cn_market_code(symbol: str) -> tuple[int, str]:
    code = _to_tdx_code(symbol)
    exchange = cn_exchange(symbol)
    return (CN_MARKET_SH if exchange == "sh" else CN_MARKET_SZ), code


def _to_ex_market_code(symbol: str, market: Market) -> tuple[int, str]:
    code, suffix = split_symbol(symbol)
    del suffix
    value = code.strip().upper()
    if value in TDX_INDEX_SYMBOLS:
        return TDX_INDEX_SYMBOLS[value]
    if market == "hk":
        if not code.isdigit():
            raise SourceError(f"TDX invalid Hong Kong symbol: {symbol}")
        padded = code.zfill(5)
        if padded.startswith("08"):
            return ExMarket.HK_GEM, padded
        return ExMarket.HK_MAIN_BOARD, padded
    if market == "us":
        if not value:
            raise SourceError(f"TDX invalid US symbol: {symbol}")
        return ExMarket.US_STOCK, value
    raise SourceError(f"TDX unsupported extended market: {market}")


def _to_tdx_code(symbol: str) -> str:
    code = cn_plain_symbol(symbol)
    if code is None:
        raise SourceError(f"TDX only supports China A-share symbols: {symbol}")
    return code


def _parse_expiration(expiration: str) -> tuple[str, int]:
    """Parse YYYY-MM into (YY string, month int), e.g. 2026-10 -> ("26", 10)."""
    year, month = expiration.split("-", 1)
    return year[-2:], int(month)


def _to_futures_market_code(symbol: str, expiration: str | None = None) -> tuple[int, str]:
    """Translate a user futures symbol + optional YYYY-MM expiration to easy-tdx (ExMarket, code).

    Three code families:
    - SGE spot-deferred products use the fixed SGE_SPOT_MAP and ignore expiration.
    - Domestic exchanges (SHFE/DCE/CZCE/CFFEX/GFEX): main continuous <CODE>L8,
      month contract <CODE><YYMM>.
    - International exchanges (COMEX/NYMEX/CBOT): main continuous <CODE>00W,
      month contract <CODE><YY><month-letter>.
    """
    exchange = futures_exchange(symbol)
    if exchange is None:
        raise SourceError(f"TDX invalid futures symbol: {symbol}")
    if exchange == "SGE":
        code = SGE_SPOT_MAP.get(f"{futures_plain_code(symbol)}.SGE")
        if code is None:
            raise SourceError(f"TDX unknown SGE product: {symbol}")
        return ExMarket.SH_GOLD, code
    code = futures_plain_code(symbol)
    if expiration is None:
        code = f"{code}00W" if exchange in INTL_FUTURES_EXCHANGES else f"{code}L8"
    else:
        year, month = _parse_expiration(expiration)
        if exchange in INTL_FUTURES_EXCHANGES:
            code = f"{code}{year}{FUTURES_MONTH_LETTERS[month]}"
        else:
            code = f"{code}{year}{month:02d}"
    return ExMarket(FUTURES_EXCHANGES[exchange]), code


def _futures_contract_symbol(exchange: str, code: str) -> tuple[str, str | None]:
    """Map a raw tdx contract code to (user symbol, expiration YYYY-MM | None).

    Reverse of _to_futures_market_code: strips the L8/00W main-continuous suffix
    or the YYMM / YY+month-letter suffix from the variety code and recomputes the
    user-facing symbol and expiration.
    """
    raw = code.strip()
    if exchange == "SGE":
        reverse = {tdx_code: user_symbol for user_symbol, tdx_code in SGE_SPOT_MAP.items()}
        user_symbol = reverse.get(raw)
        if user_symbol:
            return user_symbol, None
        return f"{raw.replace('.', '').upper()}.SGE", None
    upper = raw.upper()
    if exchange in INTL_FUTURES_EXCHANGES:
        if upper.endswith("00W"):
            return f"{upper[:-3]}.{exchange}", None
        # Month contract: <VARIETY><YY><month-letter>, e.g. GC26Z.
        if len(upper) >= 4:
            for index in range(len(upper) - 3, 0, -1):
                suffix = upper[index:]
                if suffix[0:2].isdigit() and suffix[2] in FUTURES_MONTH_NUMBERS:
                    month = FUTURES_MONTH_NUMBERS[suffix[2]]
                    return f"{upper[:index]}.{exchange}", f"20{suffix[0:2]}-{month:02d}"
        return f"{upper}.{exchange}", None
    # Domestic: main continuous <CODE>L8, month contract <CODE><YYMM>.
    if upper.endswith("L8"):
        return f"{upper[:-2]}.{exchange}", None
    if len(upper) >= 5:
        for index in range(len(upper) - 4, 0, -1):
            suffix = upper[index:]
            if suffix.isdigit() and len(suffix) == 4:
                return f"{upper[:index]}.{exchange}", f"20{suffix[0:2]}-{suffix[2:4]}"
    return f"{upper}.{exchange}", None


def _is_queryable_futures_code(exchange: str, code: str) -> bool:
    """Whether a tdx goods_list code maps back to a queryable user symbol.

    Main continuous (L8 / 00W) and month contracts (YYMM / YY+month-letter) are
    queryable through _to_futures_market_code; auxiliary continuous codes (次连
    L7, 加权 L9, 连续 00Y) are not, so they are filtered from search results.
    """
    upper = code.strip().upper()
    if exchange == "SGE":
        return True
    if exchange in INTL_FUTURES_EXCHANGES:
        if re.fullmatch(r"[A-Z0-9]+00[A-Z]", upper):
            return upper.endswith("00W")
        return True
    if re.fullmatch(r"[A-Z]+L\d", upper):
        return upper.endswith("L8")
    return True


def _futures_search_match(text: str, code: str, name: str, symbol: str, is_symbol: bool | None) -> bool:
    """Match a futures search query against code/name/symbol.

    With is_symbol=True the query is treated as a symbol fragment and matched
    against the tdx code and the user-facing symbol. Otherwise it may also match
    the Chinese product name.
    """
    if is_symbol:
        return text in code or text in symbol
    return text in code or text in symbol or text in name


def _normalize_futures_quote(row: dict[str, Any], symbol: str) -> dict[str, Any]:
    quote = _normalize_quote(row, symbol)
    quote["name"] = str(row.get("name") or "").strip() or None
    return quote


def _to_tdx_period(interval: str) -> Period:
    normalized = normalize_interval(interval)
    mapping = {
        "1m": Period.MIN_1,
        "5m": Period.MIN_5,
        "15m": Period.MIN_15,
        "30m": Period.MIN_30,
        "60m": Period.MIN_60,
        "1h": Period.MIN_60,
        "1d": Period.DAILY,
        "1w": Period.WEEKLY,
        "1M": Period.MONTHLY,
    }
    if normalized not in mapping:
        raise SourceError(f"TDX unsupported interval: {interval}")
    return mapping[normalized]


def _to_tdx_adjust(adjusted: bool) -> Adjust:
    return Adjust.QFQ if adjusted else Adjust.NONE


def _iter_frame_rows(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if hasattr(frame, "empty") and frame.empty:
        return []
    if hasattr(frame, "to_dict"):
        rows = frame.to_dict("records")
        return [dict(row) for row in rows]
    if isinstance(frame, list):
        return [dict(row) for row in frame if isinstance(row, dict)]
    return []


def _normalize_price_row(row: dict[str, Any], query: PriceQuery) -> dict[str, Any]:
    date_value = _parse_date(row.get("datetime") or row.get("date") or row.get("time"))
    if not is_intraday_interval(normalize_interval(query.interval)):
        date_value = _as_date(date_value)
    return {
        "symbol": _normalize_symbol(query.symbol),
        "date": date_value,
        "open": _optional_float(row.get("open")),
        "high": _optional_float(row.get("high")),
        "low": _optional_float(row.get("low")),
        "close": _optional_float(row.get("close")),
        "volume": _normalize_price_volume(row.get("vol") or row.get("volume"), query.market),
        "amount": _optional_float(row.get("amount")),
        "source": "tdx",
    }


def _normalize_quote(row: dict[str, Any], symbol: str) -> dict[str, Any]:
    last_price = _optional_float(row.get("close") or row.get("price") or row.get("last_price"))
    prev_close = _optional_float(row.get("pre_close") or row.get("prev_close"))
    market = _infer_tdx_market(symbol)
    change = last_price - prev_close if last_price is not None and prev_close not in {None, 0} else None
    return {
        "symbol": _normalize_symbol(symbol),
        "last_price": last_price,
        "open": _optional_float(row.get("open")),
        "high": _optional_float(row.get("high")),
        "low": _optional_float(row.get("low")),
        "prev_close": prev_close,
        "volume": _normalize_quote_volume(row.get("vol") or row.get("volume"), market),
        "change": change,
        "change_percent": (change / prev_close * 100) if change is not None and prev_close else None,
        "source": "tdx",
    }


def _normalize_symbol(symbol: str) -> str:
    if cn_plain_symbol(symbol) is not None:
        return to_openbb_symbol(symbol)
    return symbol.strip().upper()


def _parse_date(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    text = str(value or "").strip()
    if not text:
        raise SourceError("TDX returned price row without datetime")
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _as_date(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def _normalize_price_volume(value: Any, market: Market) -> float | None:
    # easy-tdx MacEx HK kline volume is in board lots; other tested markets already return shares.
    multiplier = 100.0 if market == "hk" else 1.0
    return _optional_float(value, multiplier=multiplier)


def _normalize_quote_volume(value: Any, market: Market) -> float | None:
    # easy-tdx MacClient CN quote volume is in lots; HK/US quotes return shares.
    multiplier = 100.0 if market == "cn" else 1.0
    return _optional_float(value, multiplier=multiplier)


def _optional_float(value: Any, *, multiplier: float = 1.0) -> float | None:
    if value in {None, ""}:
        return None
    return float(value) * multiplier
