"""Tests for economic indicators fetcher."""

import inspect

import pytest
from openbb import obb
from openbb_finance.models.available_indicators import (
    FinanceAvailableIndicatorsFetcher,
    FinanceAvailableIndicatorsQueryParams,
)
from openbb_finance.models.consumer_price_index import (
    FinanceConsumerPriceIndexFetcher,
    FinanceConsumerPriceIndexQueryParams,
)
from openbb_finance.models.economic_indicators import (
    FinanceEconomicIndicatorsFetcher,
    FinanceEconomicIndicatorsQueryParams,
)
from openbb_finance.models.gdp_nominal import (
    FinanceGdpNominalFetcher,
    FinanceGdpNominalQueryParams,
)
from openbb_finance.sources.akshare import AkshareSource, _normalize_macro_date

import openbb_finance  # noqa: F401


class MockAkshareSource:
    """Mock AKShare source for testing."""
    
    name = "akshare"
    enabled = True

    def __init__(self, data):
        self.data = data
    
    async def fetch_macro_indicators(self, symbol, start_date=None, end_date=None):
        return self.data


class MockRegistry:
    """Mock registry for testing."""
    
    def __init__(self, source=None):
        self.source = source
    
    def get(self, name):
        if name == "akshare" and self.source:
            return self.source
        return None


@pytest.mark.anyio
async def test_economic_indicators_china_gdp():
    """Test fetching China GDP data."""
    mock_data = [
        {
            "date": "2024-01-17",
            "symbol": "GDP_YOY",
            "symbol_root": "GDP",
            "country": "china",
            "value": 5.2,
            "consensus": 5.3,
            "previous": 4.9,
            "source": "akshare",
        }
    ]
    
    query = FinanceEconomicIndicatorsQueryParams(symbol="GDP", country="china")
    data = await FinanceEconomicIndicatorsFetcher.aextract_data(
        query,
        credentials=None,
        registry=MockRegistry(MockAkshareSource(mock_data))
    )
    
    assert len(data) == 1
    assert data[0]["symbol"] == "GDP_YOY"
    assert data[0]["country"] == "china"
    assert data[0]["value"] == 5.2


@pytest.mark.anyio
async def test_economic_indicators_china_cpi():
    """Test fetching China CPI data."""
    mock_data = [
        {
            "date": "2024-01-10",
            "symbol": "CPI_YOY",
            "symbol_root": "CPI",
            "country": "china",
            "value": -0.3,
            "consensus": -0.3,
            "previous": -0.5,
            "source": "akshare",
        }
    ]
    
    query = FinanceEconomicIndicatorsQueryParams(symbol="CPI", country="china")
    data = await FinanceEconomicIndicatorsFetcher.aextract_data(
        query,
        credentials=None,
        registry=MockRegistry(MockAkshareSource(mock_data))
    )
    
    assert len(data) == 1
    assert data[0]["symbol"] == "CPI_YOY"
    assert data[0]["country"] == "china"


@pytest.mark.anyio
async def test_economic_indicators_country_variants():
    """Test various China country name variants."""
    mock_data = [{"date": "2024-01-01", "symbol": "GDP", "country": "china", "value": 1.0}]
    
    # Test different China country name variants
    for country in ["china", "CN", "中国", "Chinese"]:
        query = FinanceEconomicIndicatorsQueryParams(symbol="GDP", country=country)
        data = await FinanceEconomicIndicatorsFetcher.aextract_data(
            query,
            credentials=None,
            registry=MockRegistry(MockAkshareSource(mock_data))
        )
        assert len(data) == 1, f"Failed for country={country}"


@pytest.mark.anyio
async def test_economic_indicators_defaults_international_frequency():
    """Test international indicator fallback defaults frequency for EconDB."""

    class MockResponse:
        results = [
            type(
                "IndicatorRow",
                (),
                {
                    "date": "2024-01-01",
                    "symbol": "GDPUS",
                    "symbol_root": "GDP",
                    "country": "United States",
                    "value": 100.0,
                },
            )()
        ]

    class MockEconomy:
        def indicators(
            self,
            symbol=None,
            country=None,
            frequency=None,
            start_date=None,
            end_date=None,
            provider=None,
        ):
            assert symbol == "GDP"
            assert country == "united_states"
            assert frequency == "quarter"
            assert start_date is None
            assert end_date is None
            assert provider == "econdb"
            return MockResponse()

    class MockOpenBB:
        economy = MockEconomy()

    query = FinanceEconomicIndicatorsQueryParams(symbol="GDP", country="united_states")
    data = await FinanceEconomicIndicatorsFetcher.aextract_data(
        query,
        credentials=None,
        openbb_client=MockOpenBB(),
    )

    assert data == [
        {
            "date": "2024-01-01",
            "symbol": "GDPUS",
            "symbol_root": "GDP",
            "country": "United States",
            "value": 100.0,
        }
    ]


@pytest.mark.anyio
async def test_gdp_nominal_defaults_to_china_without_country():
    """Test GDP nominal query works when country is omitted."""
    mock_data = [{"date": "2024-03-31", "country": "china", "value": 296299.0}]

    class MockGdpSource:
        async def fetch_macro_gdp(self):
            return mock_data

    query = FinanceGdpNominalQueryParams()
    data = await FinanceGdpNominalFetcher.aextract_data(
        query,
        credentials=None,
        registry=MockRegistry(MockGdpSource()),
    )

    assert data == [{**mock_data[0], "source": "akshare"}]


@pytest.mark.anyio
async def test_gdp_nominal_filters_china_date_range():
    """Test GDP nominal query filters China rows by requested date range."""
    mock_data = [
        {"date": "2024-03-31", "country": "china", "value": 296299.0},
        {"date": "2024-06-30", "country": "china", "value": 320537.0},
    ]

    class MockGdpSource:
        async def fetch_macro_gdp(self):
            return mock_data

    query = FinanceGdpNominalQueryParams(start_date="2024-06-01", end_date="2024-06-30")
    data = await FinanceGdpNominalFetcher.aextract_data(
        query,
        credentials=None,
        registry=MockRegistry(MockGdpSource()),
    )

    assert [row["date"] for row in data] == ["2024-06-30"]


@pytest.mark.anyio
async def test_gdp_nominal_forwards_country_to_openbb_fallback():
    """Test international GDP fallback forwards the requested country."""

    class MockResponse:
        results = [
            type(
                "GdpRow",
                (),
                {"date": "2024-01-01", "country": "united_states", "value": 100.0},
            )()
        ]

    class MockGdp:
        def nominal(self, start_date=None, end_date=None, country=None, provider=None):
            assert start_date is None
            assert end_date is None
            assert country == "united_states"
            assert provider == "oecd"
            return MockResponse()

    class MockEconomy:
        gdp = MockGdp()

    class MockOpenBB:
        economy = MockEconomy()

    query = FinanceGdpNominalQueryParams(country="united_states")
    data = await FinanceGdpNominalFetcher.aextract_data(
        query,
        credentials=None,
        openbb_client=MockOpenBB(),
    )

    assert data == [{"date": "2024-01-01", "country": "united_states", "value": 100.0}]


def test_cpi_transform_data_accepts_standard_shape():
    """Test CPI transform uses the standard date/country/value fields."""
    result = FinanceConsumerPriceIndexFetcher.transform_data(
        FinanceConsumerPriceIndexQueryParams(country="china"),
        [{"date": "2024-01-10", "country": "china", "value": -0.3}],
    )

    assert result[0].country == "china"
    assert result[0].value == -0.3


@pytest.mark.anyio
async def test_cpi_uses_monthly_source_and_filters_date_range():
    """Test China CPI default monthly query uses monthly source and filters dates."""
    mock_data = [
        {"date": "2024-01-01", "country": "china", "value": -0.8},
        {"date": "2024-02-01", "country": "china", "value": 0.7},
    ]

    class MockCpiSource:
        async def fetch_macro_cpi(self, transform="index"):
            assert transform == "yoy"
            return mock_data

    query = FinanceConsumerPriceIndexQueryParams(
        country="china",
        start_date="2024-02-01",
        end_date="2024-02-29",
    )
    data = await FinanceConsumerPriceIndexFetcher.aextract_data(
        query,
        credentials=None,
        registry=MockRegistry(MockCpiSource()),
    )

    assert data == [{**mock_data[1], "source": "akshare"}]


@pytest.mark.anyio
async def test_cpi_annual_aggregates_monthly_china_rows():
    """Test China annual CPI query aggregates monthly source rows by year."""
    mock_data = [
        {"date": "2024-01-01", "country": "china", "value": 100.0},
        {"date": "2024-02-01", "country": "china", "value": 102.0},
        {"date": "2025-01-01", "country": "china", "value": 104.0},
    ]

    class MockCpiSource:
        async def fetch_macro_cpi(self, transform="index"):
            assert transform == "yoy"
            return mock_data

    query = FinanceConsumerPriceIndexQueryParams(country="china", frequency="annual")
    data = await FinanceConsumerPriceIndexFetcher.aextract_data(
        query,
        credentials=None,
        registry=MockRegistry(MockCpiSource()),
    )

    assert data == [
        {"date": "2024-12-31", "country": "china", "value": 101.0, "source": "akshare"},
        {"date": "2025-12-31", "country": "china", "value": 104.0, "source": "akshare"},
    ]


def test_macro_month_date_normalization():
    """Test Chinese month labels are normalized before filtering and transform."""
    assert _normalize_macro_date("2022年10月份") == "2022-10-01"
    assert _normalize_macro_date("2024年第1季度") == "2024-03-31"
    assert _normalize_macro_date("2024年第1-4季度") == "2024-12-31"


def test_economy_routes_accept_finance_provider():
    """Test patched economy route signatures accept finance provider."""
    for route in [
        obb.economy.available_indicators,
        obb.economy.indicators,
        obb.economy.cpi,
        obb.economy.gdp.nominal,
    ]:
        provider_annotation = inspect.signature(route).parameters["provider"].annotation
        assert "finance" in str(provider_annotation)


def test_economy_routes_preserve_upstream_list_contracts():
    """Test patched routes keep list parameters accepted by upstream providers."""
    indicators_signature = inspect.signature(obb.economy.indicators)
    cpi_signature = inspect.signature(obb.economy.cpi)

    assert "list" in str(indicators_signature.parameters["symbol"].annotation)
    assert "list" in str(indicators_signature.parameters["country"].annotation)
    assert "list" in str(cpi_signature.parameters["country"].annotation)


def test_gdp_nominal_route_does_not_default_non_finance_country_to_china():
    """Test GDP nominal route leaves country optional for upstream providers."""
    signature = inspect.signature(obb.economy.gdp.nominal)

    assert signature.parameters["country"].default is None


def test_gdp_nominal_route_passes_country_to_finance_fetcher():
    """Test patched GDP nominal route passes country through standard params."""
    original_transform_query = FinanceGdpNominalFetcher.transform_query
    seen_countries = []

    def spy_transform_query(params):
        query = original_transform_query(params)
        seen_countries.append(query.country)
        return query

    FinanceGdpNominalFetcher.transform_query = staticmethod(spy_transform_query)
    try:
        obb.economy.gdp.nominal(country="united_states", provider="finance")
    finally:
        FinanceGdpNominalFetcher.transform_query = original_transform_query

    assert seen_countries[0] == "united_states"


@pytest.mark.anyio
async def test_akshare_macro_indicators_supports_cpi_yoy_symbol():
    """Test advertised CPI_YOY symbol dispatches to the yearly CPI source."""

    class MockAkshareMacroSource:
        fetch_macro_indicators = AkshareSource.fetch_macro_indicators

        async def fetch_macro_cpi_yearly(self):
            return [
                {
                    "date": "2024-01-10",
                    "symbol": "CPI_YOY",
                    "symbol_root": "CPI",
                    "country": "china",
                    "value": -0.3,
                }
            ]

    data = await MockAkshareMacroSource().fetch_macro_indicators("CPI_YOY")

    assert data[0]["symbol"] == "CPI_YOY"


@pytest.mark.anyio
async def test_akshare_macro_indicators_dispatches_base_and_yoy_symbols():
    """Test base macro symbols dispatch to base series and YoY symbols to YoY series."""

    class MockAkshareMacroSource:
        fetch_macro_indicators = AkshareSource.fetch_macro_indicators

        async def fetch_macro_gdp(self):
            return [{"date": "2024-03-31", "symbol": "GDP", "value": 296299.0}]

        async def fetch_macro_gdp_yearly(self):
            return [{"date": "2024-04-16", "symbol": "GDP_YOY", "value": 5.3}]

        async def fetch_macro_cpi(self, transform="index"):
            assert transform == "index"
            return [{"date": "2024-01-01", "symbol": "CPI", "value": 100.1}]

        async def fetch_macro_cpi_yearly(self):
            return [{"date": "2024-01-10", "symbol": "CPI_YOY", "value": -0.3}]

    source = MockAkshareMacroSource()

    assert (await source.fetch_macro_indicators("GDP"))[0]["symbol"] == "GDP"
    assert (await source.fetch_macro_indicators("GDP_YOY"))[0]["symbol"] == "GDP_YOY"
    assert (await source.fetch_macro_indicators("CPI"))[0]["symbol"] == "CPI"
    assert (await source.fetch_macro_indicators("CPI_YOY"))[0]["symbol"] == "CPI_YOY"


@pytest.mark.anyio
async def test_available_indicators_returns_china_macro_symbols():
    """Test finance available indicators includes supported China macro symbols."""
    data = await FinanceAvailableIndicatorsFetcher.aextract_data(
        FinanceAvailableIndicatorsQueryParams(),
        credentials=None,
        openbb_client=None,
    )
    result = FinanceAvailableIndicatorsFetcher.transform_data(
        FinanceAvailableIndicatorsQueryParams(),
        data,
    )
    symbols = {item.symbol for item in result}

    assert {"GDP", "GDP_YOY", "CPI", "CPI_YOY", "PPI", "PMI"} <= symbols


@pytest.mark.anyio
async def test_available_indicators_merges_openbb_international_symbols():
    """Test finance available indicators includes OpenBB international macro symbols."""

    class MockResponse:
        results = [
            {
                "symbol_root": "GDP",
                "symbol": "RGDPUS",
                "country": "united_states",
                "iso": "USA",
                "description": "United States real GDP.",
                "frequency": "quarter",
            }
        ]

    class MockEconomy:
        def available_indicators(self, provider):
            assert provider in {"econdb", "imf"}
            return MockResponse()

    class MockOpenBB:
        economy = MockEconomy()

    data = await FinanceAvailableIndicatorsFetcher.aextract_data(
        FinanceAvailableIndicatorsQueryParams(),
        credentials=None,
        openbb_client=MockOpenBB(),
    )
    result = FinanceAvailableIndicatorsFetcher.transform_data(
        FinanceAvailableIndicatorsQueryParams(),
        data,
    )

    assert any(item.iso == "CHN" for item in result)
    assert any(item.iso == "USA" and item.symbol == "RGDPUS" for item in result)
