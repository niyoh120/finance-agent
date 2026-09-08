from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest
from openbb_finance.config import SourceConfig
from openbb_finance.sources.base import PriceQuery, SourceError
from openbb_finance.sources.schwab import SchwabSource

pytestmark = pytest.mark.anyio

_ET = ZoneInfo("America/New_York")


def _source(base_url: str = "http://127.0.0.1:8010", api_key: str | None = None) -> SchwabSource:
    return SchwabSource(SourceConfig(name="schwab", enabled=True, base_url=base_url, api_key=api_key))


# ---- gating / supports -------------------------------------------------------


def test_schwab_disables_without_base_url():
    # ${SCHWAB_API_BASE_URL} expands to "" without the env var -> disabled.
    source = SchwabSource(SourceConfig(name="schwab", enabled=True, base_url=""))

    assert source.enabled is False


def test_schwab_supports_us_price_fundamental_search_only():
    source = _source()

    assert source.supports("us", "price") is True
    assert source.supports("us", "fundamental") is True
    assert source.supports("us", "search") is True
    assert source.supports("cn", "price") is False
    assert source.supports("hk", "price") is False
    assert source.supports("us", "news") is False


# ---- price -------------------------------------------------------------------


async def test_schwab_price_rejects_unsupported_interval():
    source = _source()

    with pytest.raises(SourceError, match="interval"):
        await source.fetch_price(PriceQuery(symbol="AAPL", market="us", interval="60m"))


async def test_schwab_price_normalizes_minute_candles_to_et_naive():
    ts_ms = 1788433200000  # 2026-09-03 11:00 UTC == 07:00 America/New_York (EDT)

    class FakeSchwab(SchwabSource):
        async def _get(self, path, params):
            assert path == "/api/v1/equity/price/historical"
            assert params["symbol"] == "AAPL"
            assert params["interval"] == "5m"
            assert params["extended"] == "false"
            return {
                "symbol": "AAPL",
                "empty": False,
                "candles": [
                    {
                        "open": 324.23,
                        "high": 324.46,
                        "low": 324.0,
                        "close": 324.46,
                        "volume": 12502,
                        "datetime": ts_ms,
                    }
                ],
            }

    rows = await FakeSchwab(_source()).fetch_price(PriceQuery(symbol="AAPL", market="us", interval="5m"))

    expected = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).astimezone(_ET).replace(tzinfo=None)
    assert expected == datetime(2026, 9, 3, 7, 0)
    assert rows == [
        {
            "symbol": "AAPL",
            "date": expected,
            "open": 324.23,
            "high": 324.46,
            "low": 324.0,
            "close": 324.46,
            "volume": 12502.0,
            "source": "schwab",
        }
    ]


async def test_schwab_price_daily_candles_yield_dates():
    class FakeSchwab(SchwabSource):
        async def _get(self, path, params):
            assert params["interval"] == "1d"
            return {
                "candles": [{"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100, "datetime": 1788433200000}]
            }

    rows = await FakeSchwab(_source()).fetch_price(PriceQuery(symbol="AAPL", market="us", interval="1d"))

    assert rows[0]["date"] == date(2026, 9, 3)


async def test_schwab_price_extended_hours_passthrough():
    class FakeSchwab(SchwabSource):
        async def _get(self, path, params):
            assert params["extended"] == "true"
            return {"candles": []}

    rows = await FakeSchwab(_source()).fetch_price(PriceQuery(symbol="AAPL", market="us", interval="5m", extended=True))

    assert rows == []


async def test_schwab_price_empty_returns_no_rows():
    class FakeSchwab(SchwabSource):
        async def _get(self, path, params):
            assert params["symbol"] == "BRK.B"
            return {"symbol": "BRK.B", "empty": True, "candles": []}

    rows = await FakeSchwab(_source()).fetch_price(PriceQuery(symbol="BRK.B", market="us", interval="1d"))

    assert rows == []


async def test_schwab_price_pages_backward_across_40k_cap():
    """A full 40k page triggers a follow-up request with `end` moved just
    before the earliest kept bar; pages concatenate oldest-first."""
    page_candles = [{"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "datetime": ms} for ms in range(40_000)]

    class FakeSchwab(SchwabSource):
        def __init__(self):
            super().__init__(_source())
            self.calls = []

        async def _get(self, path, params):
            self.calls.append(dict(params))
            if "end" not in params:
                return {"symbol": "AAPL", "candles": page_candles}
            return {"candles": [{"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "datetime": -1_000}]}

    source = FakeSchwab()
    rows = await source.fetch_price(PriceQuery(symbol="AAPL", market="us", interval="1m"))

    assert len(source.calls) == 2
    assert "end" in source.calls[1]
    assert rows[0]["date"] == datetime.fromtimestamp(-1.0, tz=timezone.utc).astimezone(_ET).replace(tzinfo=None)
    assert len(rows) == 40_001
    assert rows[-1]["date"] == datetime.fromtimestamp(39_999 / 1000, tz=timezone.utc).astimezone(_ET).replace(
        tzinfo=None
    )


async def test_schwab_price_pagination_never_duplicates_boundary_bar():
    """endDate is inclusive: the next page's end must sit 1ms before the
    earliest kept bar, and any boundary overlap must be deduped (live-verified
    regression: exact-timestamp boundary produced 337 duplicated bars)."""

    class FakeSchwab(SchwabSource):
        def __init__(self):
            super().__init__(_source())
            self.calls = []

        async def _get(self, path, params):
            self.calls.append(dict(params))
            if "end" not in params:
                # newest page: full cap -> must page again
                return {
                    "candles": [
                        {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "datetime": ms}
                        for ms in range(40_000)
                    ]
                }
            # server honours endDate inclusively AND returns the boundary bar
            # again despite end == earliest - 1 (defensive scenario)
            return {
                "candles": [
                    {"open": 0.5, "high": 0.5, "low": 0.5, "close": 0.5, "volume": 9, "datetime": -1_000},
                    {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "datetime": 0},
                ]
            }

    source = FakeSchwab()
    rows = await source.fetch_price(PriceQuery(symbol="AAPL", market="us", interval="1m"))

    assert source.calls[1]["end"] == "1969-12-31T23:59:59.999000+00:00"  # earliest - 1ms
    stamps = [row["date"] for row in rows]
    assert len(stamps) == len(set(stamps))  # no duplicated bars
    assert len(rows) == 40_001


async def test_schwab_price_pages_backward_with_bounded_windows(monkeypatch: pytest.MonkeyPatch):
    """Deep history pages must use bounded request spans: wide sub-windows
    degrade server-side to tiny responses, silently losing older bars."""
    import openbb_finance.sources.schwab as schwab_module

    monkeypatch.setattr(schwab_module, "_MAX_PAGES", 6)

    class FakeSchwab(SchwabSource):
        def __init__(self):
            super().__init__(_source())
            self.spans = []

        async def _get(self, path, params):
            start = datetime.fromisoformat(params["start"]).timestamp() * 1000
            end = datetime.fromisoformat(params["end"]).timestamp() * 1000
            self.spans.append((start, end))
            # one bar 30 days before the cursor end -> covers the bounded span
            return {
                "candles": [
                    {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "datetime": int(end - 30 * 86_400_000)}
                ]
            }

    source = FakeSchwab()
    rows = await source.fetch_price(
        PriceQuery(symbol="AAPL", market="us", interval="1m", start_date=date(2026, 1, 1), end_date=date(2026, 3, 1))
    )

    assert rows  # paged until the start cover
    span_ms = schwab_module._PAGE_SPAN_DAYS["1m"] * 86_400_000
    for start, end in source.spans:
        assert end - start <= span_ms + 1  # every page window stays bounded
    # the last page's window lower bound is the requested start (ET midnight)
    expected_start_ms = schwab_module._et_date_to_ms(date(2026, 1, 1))
    assert source.spans[-1][0] == expected_start_ms


async def test_schwab_price_clips_window_to_requested_dates():
    class FakeSchwab(SchwabSource):
        async def _get(self, path, params):
            # window edges anchored to ET-midnight (2026-09-04 00:00 EDT == 04:00 UTC)
            assert params["start"] == "2026-09-04T04:00:00+00:00"
            assert params["end"] == "2026-09-05T03:59:59.999000+00:00"
            return {
                "candles": [
                    # tail bar from the previous trading day (boundary behaviour)
                    {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "datetime": 1788346800000},
                    {"open": 2, "high": 2, "low": 2, "close": 2, "volume": 2, "datetime": 1788433200000},
                    {"open": 3, "high": 3, "low": 3, "close": 3, "volume": 3, "datetime": 1788519600000},
                ]
            }

    rows = await FakeSchwab(_source()).fetch_price(
        PriceQuery(symbol="AAPL", market="us", interval="1d", start_date=date(2026, 9, 4), end_date=date(2026, 9, 4))
    )

    assert [row["date"] for row in rows] == [date(2026, 9, 4)]


# ---- quote -------------------------------------------------------------------


async def test_schwab_quote_maps_fields():
    class FakeSchwab(SchwabSource):
        async def _get(self, path, params):
            assert path == "/api/v1/equity/price/quote"
            assert params == {"symbols": "AAPL"}
            return {
                "AAPL": {
                    "symbol": "AAPL",
                    "description": "Apple Inc.",
                    "quote": {
                        "lastPrice": 320.01,
                        "bidPrice": 320.01,
                        "bidSize": 40,
                        "askPrice": 320.07,
                        "askSize": 120,
                        "openPrice": 328.93,
                        "highPrice": 328.93,
                        "lowPrice": 317.86,
                        "closePrice": 319.97,
                        "totalVolume": 39606884,
                        "netChange": 0.04,
                        "netPercentChange": 0.01250117,
                        "52WeekHigh": 344.5699,
                        "52WeekLow": 225.95,
                    },
                }
            }

    row = await FakeSchwab(_source()).fetch_quote("aapl")

    assert row == {
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "last_price": 320.01,
        "bid": 320.01,
        "bid_size": 40.0,
        "ask": 320.07,
        "ask_size": 120.0,
        "open": 328.93,
        "high": 328.93,
        "low": 317.86,
        "prev_close": 319.97,
        "volume": 39606884.0,
        "change": 0.04,
        "change_percent": 0.01250117,
        "year_high": 344.5699,
        "year_low": 225.95,
        "source": "schwab",
    }


async def test_schwab_index_quote_uses_dollar_symbol_and_indicative():
    class FakeSchwab(SchwabSource):
        async def _get(self, path, params):
            assert params == {"symbols": "$SPX", "indicative": "true"}
            return {"$SPX": {"symbol": "$SPX", "quote": {"lastPrice": 7718.6, "closePrice": 7718.6}}}

    row = await FakeSchwab(_source()).fetch_quote("SPX")

    assert row["symbol"] == "SPX"
    assert row["last_price"] == 7718.6


async def test_schwab_quote_invalid_symbols_raises():
    class FakeSchwab(SchwabSource):
        async def _get(self, path, params):
            return {"errors": {"invalidSymbols": ["$VIX"]}}

    with pytest.raises(SourceError, match="invalid"):
        await FakeSchwab(_source()).fetch_quote("VIX")


# ---- search / fundamental ------------------------------------------------------


def _instrument(symbol: str, asset_type: str, description: str = "APPLE INC") -> dict:
    return {"symbol": symbol, "description": description, "exchange": "NASDAQ", "assetType": asset_type}


async def test_schwab_search_keeps_equities_only():
    class FakeSchwab(SchwabSource):
        async def _get(self, path, params):
            assert path == "/api/v1/equity/search"
            assert params == {"symbol": "apple", "projection": "desc-search"}
            return {
                "instruments": [
                    _instrument("APPLX", "MUTUAL_FUND", "APPLESEED INVESTOR"),
                    _instrument("AAPL", "EQUITY"),
                ]
            }

    rows = await FakeSchwab(_source()).fetch_equity_search("apple", is_symbol=False)

    assert rows == [{"symbol": "AAPL", "name": "APPLE INC", "exchange": "NASDAQ", "type": "EQUITY", "source": "schwab"}]


async def test_schwab_search_symbol_projection_and_non_ascii_shortcut():
    calls = []

    class FakeSchwab(SchwabSource):
        async def _get(self, path, params):
            calls.append(params)
            return {"instruments": [_instrument("AAPL", "EQUITY")]}

    source = FakeSchwab(_source())
    by_symbol = await source.fetch_equity_search("aapl", is_symbol=True)
    cjk = await source.fetch_equity_search("茅台", is_symbol=False)

    assert calls == [{"symbol": "aapl", "projection": "symbol-search"}]
    assert by_symbol[0]["symbol"] == "AAPL"
    assert cjk == []


async def test_schwab_fundamental_wraps_fundamental_section():
    class FakeSchwab(SchwabSource):
        async def _get(self, path, params):
            assert path == "/api/v1/equity/fundamental"
            assert params == {"symbol": "AAPL"}
            return {
                "AAPL": {
                    "symbol": "AAPL",
                    "assetMainType": "EQUITY",
                    "fundamental": {"peRatio": 36.7, "divYield": 0.329},
                }
            }

    row = await FakeSchwab(_source()).fetch_fundamental("AAPL")

    assert row == {"symbol": "AAPL", "source": "schwab", "peRatio": 36.7, "divYield": 0.329}


# ---- plumbing ------------------------------------------------------------------


def _patch_http_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    real_async_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("openbb_finance.sources.schwab.httpx.AsyncClient", factory)


async def test_schwab_get_503_raises_with_hint(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text='{"detail":"not authenticated"}')

    _patch_http_transport(monkeypatch, handler)

    with pytest.raises(SourceError, match="503"):
        await _source()._get("/api/v1/equity/price/quote", {"symbols": "AAPL"})


async def test_schwab_get_sends_api_key_header(monkeypatch: pytest.MonkeyPatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["x-api-key"] = request.headers.get("x-api-key")
        return httpx.Response(200, json={})

    _patch_http_transport(monkeypatch, handler)

    await _source(api_key="secret")._get("/api/v1/status", {})

    assert seen["x-api-key"] == "secret"


async def test_schwab_get_connection_error_raises(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _patch_http_transport(monkeypatch, handler)

    with pytest.raises(SourceError, match="unreachable"):
        await _source()._get("/api/v1/status", {})
