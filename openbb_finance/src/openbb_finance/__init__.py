"""OpenBB finance provider."""

from openbb_core.provider.abstract.provider import Provider

from openbb_finance.config import apply_runtime_environment
from openbb_finance.models.analyst_estimates import FinanceAnalystEstimatesFetcher
from openbb_finance.models.available_indicators import FinanceAvailableIndicatorsFetcher
from openbb_finance.models.balance_sheet_statement import FinanceBalanceSheetFetcher
from openbb_finance.models.cash_flow_statement import FinanceCashFlowFetcher
from openbb_finance.models.company_filings import FinanceCompanyFilingsFetcher
from openbb_finance.models.company_news import FinanceCompanyNewsFetcher
from openbb_finance.models.consumer_price_index import FinanceConsumerPriceIndexFetcher
from openbb_finance.models.economic_calendar import FinanceEconomicCalendarFetcher
from openbb_finance.models.economic_indicators import FinanceEconomicIndicatorsFetcher
from openbb_finance.models.equity_historical import FinanceEquityHistoricalFetcher
from openbb_finance.models.equity_options_chain import FinanceOptionsChainFetcher
from openbb_finance.models.equity_options_daily import FinanceOptionDailyFetcher
from openbb_finance.models.equity_options_historical import FinanceOptionHistoricalFetcher
from openbb_finance.models.equity_options_query import FinanceOptionsQueryFetcher
from openbb_finance.models.equity_options_screener import FinanceOptionsScreenerFetcher
from openbb_finance.models.equity_quote import FinanceEquityQuoteFetcher
from openbb_finance.models.equity_screener import FinanceEquityScreenerFetcher
from openbb_finance.models.equity_search import FinanceEquitySearchFetcher
from openbb_finance.models.etf_historical import FinanceEtfHistoricalFetcher
from openbb_finance.models.etf_holdings import FinanceEtfHoldingsFetcher
from openbb_finance.models.etf_search import FinanceEtfSearchFetcher
from openbb_finance.models.etf_sectors import FinanceEtfSectorsFetcher
from openbb_finance.models.financial_ratios import FinanceFinancialRatiosFetcher
from openbb_finance.models.futures_historical import FinanceFuturesHistoricalFetcher
from openbb_finance.models.futures_quote import FinanceFuturesQuoteFetcher
from openbb_finance.models.futures_search import FinanceFuturesSearchFetcher
from openbb_finance.models.gdp_nominal import (
    FinanceGdpNominalFetcher,
    reset_gdp_nominal_country_context,
    set_gdp_nominal_country_context,
)
from openbb_finance.models.government_trades import FinanceGovernmentTradesFetcher
from openbb_finance.models.income_statement import FinanceIncomeStatementFetcher
from openbb_finance.models.index_available import FinanceAvailableIndicesFetcher
from openbb_finance.models.index_historical import FinanceIndexHistoricalFetcher
from openbb_finance.models.index_search import FinanceIndexSearchFetcher
from openbb_finance.models.index_snapshots import FinanceIndexSnapshotsFetcher
from openbb_finance.models.insider_trading import FinanceInsiderTradingFetcher
from openbb_finance.models.options_unusual import FinanceOptionsUnusualFetcher
from openbb_finance.models.technical_indicators import FinanceTechnicalIndicatorsFetcher
from openbb_finance.models.world_news import FinanceWorldNewsFetcher

apply_runtime_environment()

provider = Provider(
    name="finance",
    website="https://github.com/niyoh120/finance-agent",
    description="Pluggable finance data provider for market data, calendars, news, and options flow.",
    credentials=None,
    fetcher_dict={
        "AnalystEstimates": FinanceAnalystEstimatesFetcher,
        "AvailableIndices": FinanceAvailableIndicesFetcher,
        "AvailableIndicators": FinanceAvailableIndicatorsFetcher,
        "BalanceSheetStatement": FinanceBalanceSheetFetcher,
        "CashFlowStatement": FinanceCashFlowFetcher,
        "CompanyFilings": FinanceCompanyFilingsFetcher,
        "CompanyNews": FinanceCompanyNewsFetcher,
        "ConsumerPriceIndex": FinanceConsumerPriceIndexFetcher,
        "EconomicCalendar": FinanceEconomicCalendarFetcher,
        "EconomicIndicators": FinanceEconomicIndicatorsFetcher,
        "EquityHistorical": FinanceEquityHistoricalFetcher,
        "EquityQuote": FinanceEquityQuoteFetcher,
        "EquityScreener": FinanceEquityScreenerFetcher,
        "EquitySearch": FinanceEquitySearchFetcher,
        "EtfHistorical": FinanceEtfHistoricalFetcher,
        "EtfHoldings": FinanceEtfHoldingsFetcher,
        "EtfSearch": FinanceEtfSearchFetcher,
        "EtfSectors": FinanceEtfSectorsFetcher,
        "FinancialRatios": FinanceFinancialRatiosFetcher,
        # Futures endpoints are CLI-only: the openbb_futures router extension is
        # not installed, so these are driven through _execute_provider_model. The
        # openbb standard model names are FuturesInstruments/FuturesInfo; we
        # register FuturesSearch (CLI naming) instead.
        "FuturesHistorical": FinanceFuturesHistoricalFetcher,
        "FuturesQuote": FinanceFuturesQuoteFetcher,
        "FuturesSearch": FinanceFuturesSearchFetcher,
        "GdpNominal": FinanceGdpNominalFetcher,
        "GovernmentTrades": FinanceGovernmentTradesFetcher,
        "IncomeStatement": FinanceIncomeStatementFetcher,
        "IndexHistorical": FinanceIndexHistoricalFetcher,
        "IndexSearch": FinanceIndexSearchFetcher,
        "IndexSnapshots": FinanceIndexSnapshotsFetcher,
        "InsiderTrading": FinanceInsiderTradingFetcher,
        "OptionsChain": FinanceOptionsChainFetcher,
        "OptionsDaily": FinanceOptionDailyFetcher,
        "OptionsHistorical": FinanceOptionHistoricalFetcher,
        "OptionsQuery": FinanceOptionsQueryFetcher,
        "OptionsScreener": FinanceOptionsScreenerFetcher,
        "OptionsUnusual": FinanceOptionsUnusualFetcher,
        "TechnicalIndicators": FinanceTechnicalIndicatorsFetcher,
        "WorldNews": FinanceWorldNewsFetcher,
    },
)


def _patch_etf_search_route() -> None:
    """Allow the generated OpenBB ETF search route to accept the finance provider."""
    try:
        from typing import Annotated, Literal, Optional

        from openbb.package.etf import ROUTER_etf
        from openbb_core.app.model.field import OpenBBField
        from openbb_core.app.model.obbject import OBBject
        from openbb_core.app.static.utils.decorators import exception_handler, validate
        from openbb_core.app.static.utils.filters import filter_inputs

        @exception_handler
        @validate
        def search(
            self,
            query: Annotated[str | None, OpenBBField(description="Search query.")] = "",
            provider: Annotated[
                Optional[Literal["fmp", "intrinio", "tmx", "finance"]],
                OpenBBField(
                    description=(
                        "The provider to use, by default None. If None, the"
                        "priority list configured in the settings is used."
                        "Default priority: fmp, intrinio, tmx, finance."
                    )
                ),
            ] = None,
            **kwargs,
        ) -> OBBject:
            return self._run(
                "/etf/search",
                **filter_inputs(
                    provider_choices={
                        "provider": self._get_provider(
                            provider,
                            "etf.search",
                            ("fmp", "intrinio", "tmx", "finance"),
                        )
                    },
                    standard_params={"query": query},
                    extra_params=kwargs,
                ),
            )

        ROUTER_etf.search = search
    except Exception:
        return


def _patch_equity_screener_route() -> None:
    """Allow the generated OpenBB equity screener route to accept the finance provider."""
    try:
        from typing import Annotated, Any, Literal, Optional

        from openbb.package.equity import ROUTER_equity
        from openbb_core.app.model.field import OpenBBField
        from openbb_core.app.model.obbject import OBBject
        from openbb_core.app.static.utils.decorators import exception_handler, validate

        original_screener = ROUTER_equity.screener

        @exception_handler
        @validate
        def screener(
            self,
            provider: Annotated[
                Optional[Literal["finviz", "fmp", "nasdaq", "finance"]],
                OpenBBField(
                    description=(
                        "The provider to use, by default None. If None, the"
                        "priority list configured in the settings is used."
                    )
                ),
            ] = None,
            **kwargs: Any,
        ) -> OBBject:
            selected_provider = self._get_provider(
                provider,
                "equity.screener",
                ("finviz", "fmp", "nasdaq", "finance"),
            )
            if selected_provider != "finance":
                return original_screener(self, provider=selected_provider, **kwargs)

            return self._run(
                "/equity/screener",
                provider_choices={"provider": selected_provider},
                standard_params={},
                extra_params=kwargs,
            )

        ROUTER_equity.screener = screener
    except Exception:
        return


def _patch_economy_macro_routes() -> None:
    """Allow generated OpenBB economy macro routes to accept the finance provider."""
    try:
        from datetime import date as dateType
        from typing import Annotated, Any, Literal, Optional

        from openbb.package.economy import ROUTER_economy
        from openbb.package.economy_gdp import ROUTER_economy_gdp
        from openbb_core.app.model.field import OpenBBField
        from openbb_core.app.model.obbject import OBBject
        from openbb_core.app.static.utils.decorators import exception_handler, validate
        from openbb_core.app.static.utils.filters import filter_inputs

        original_indicators = ROUTER_economy.indicators
        original_available_indicators = ROUTER_economy.available_indicators
        original_cpi = ROUTER_economy.cpi
        original_gdp_nominal = ROUTER_economy_gdp.nominal

        @exception_handler
        @validate
        def available_indicators(
            self,
            provider: Annotated[
                Optional[Literal["econdb", "imf", "finance"]],
                OpenBBField(description="The provider to use, by default None."),
            ] = None,
            **kwargs: Any,
        ) -> OBBject:
            selected_provider = self._get_provider(
                provider,
                "economy.available_indicators",
                ("econdb", "imf", "finance"),
            )
            if selected_provider != "finance":
                return original_available_indicators(self, provider=selected_provider, **kwargs)

            return self._run(
                "/economy/available_indicators",
                **filter_inputs(
                    provider_choices={"provider": selected_provider},
                    standard_params={},
                    extra_params=kwargs,
                ),
            )

        @exception_handler
        @validate
        def indicators(
            self,
            symbol: Annotated[
                str | None | list[str | None],
                OpenBBField(description="Symbol to get data for."),
            ] = None,
            country: Annotated[
                str | None | list[str | None],
                OpenBBField(description="The country to get data."),
            ] = None,
            frequency: Annotated[str | None, OpenBBField(description="The frequency of the data.")] = None,
            start_date: Annotated[
                dateType | str | None,
                OpenBBField(description="Start date of the data, in YYYY-MM-DD format."),
            ] = None,
            end_date: Annotated[
                dateType | str | None,
                OpenBBField(description="End date of the data, in YYYY-MM-DD format."),
            ] = None,
            provider: Annotated[
                Optional[Literal["econdb", "imf", "finance"]],
                OpenBBField(description="The provider to use, by default None."),
            ] = None,
            **kwargs: Any,
        ) -> OBBject:
            selected_provider = self._get_provider(
                provider,
                "economy.indicators",
                ("econdb", "imf", "finance"),
            )
            if selected_provider != "finance":
                return original_indicators(
                    self,
                    symbol=symbol,
                    country=country,
                    frequency=frequency,
                    start_date=start_date,
                    end_date=end_date,
                    provider=selected_provider,
                    **kwargs,
                )

            return self._run(
                "/economy/indicators",
                **filter_inputs(
                    provider_choices={"provider": selected_provider},
                    standard_params={
                        "symbol": symbol,
                        "country": country,
                        "frequency": frequency,
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                    extra_params=kwargs,
                ),
            )

        @exception_handler
        @validate
        def cpi(
            self,
            country: Annotated[
                str | list[str],
                OpenBBField(description="The country to get data."),
            ] = "united_states",
            transform: Annotated[str, OpenBBField(description="Transformation of the CPI data.")] = "yoy",
            frequency: Annotated[
                Literal["annual", "quarter", "monthly"],
                OpenBBField(description="The frequency of the data."),
            ] = "monthly",
            harmonized: Annotated[bool, OpenBBField(description="If true, returns harmonized data.")] = False,
            start_date: Annotated[
                dateType | str | None,
                OpenBBField(description="Start date of the data, in YYYY-MM-DD format."),
            ] = None,
            end_date: Annotated[
                dateType | str | None,
                OpenBBField(description="End date of the data, in YYYY-MM-DD format."),
            ] = None,
            provider: Annotated[
                Optional[Literal["fred", "imf", "oecd", "finance"]],
                OpenBBField(description="The provider to use, by default None."),
            ] = None,
            **kwargs: Any,
        ) -> OBBject:
            selected_provider = self._get_provider(
                provider,
                "economy.cpi",
                ("fred", "imf", "oecd", "finance"),
            )
            if selected_provider != "finance":
                return original_cpi(
                    self,
                    country=country,
                    transform=transform,
                    frequency=frequency,
                    harmonized=harmonized,
                    start_date=start_date,
                    end_date=end_date,
                    provider=selected_provider,
                    **kwargs,
                )

            return self._run(
                "/economy/cpi",
                **filter_inputs(
                    provider_choices={"provider": selected_provider},
                    standard_params={
                        "country": country,
                        "transform": transform,
                        "frequency": frequency,
                        "harmonized": harmonized,
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                    extra_params=kwargs,
                ),
            )

        @exception_handler
        @validate
        def nominal(
            self,
            start_date: Annotated[
                dateType | str | None,
                OpenBBField(description="Start date of the data, in YYYY-MM-DD format."),
            ] = None,
            end_date: Annotated[
                dateType | str | None,
                OpenBBField(description="End date of the data, in YYYY-MM-DD format."),
            ] = None,
            provider: Annotated[
                Optional[Literal["econdb", "oecd", "finance"]],
                OpenBBField(description="The provider to use, by default None."),
            ] = None,
            country: Annotated[str | None, OpenBBField(description="The country to get data.")] = None,
            **kwargs: Any,
        ) -> OBBject:
            selected_provider = self._get_provider(
                provider,
                "economy.gdp.nominal",
                ("econdb", "oecd", "finance"),
            )
            if selected_provider != "finance":
                original_kwargs = {**kwargs}
                if country is not None:
                    original_kwargs["country"] = country
                return original_gdp_nominal(
                    self,
                    start_date=start_date,
                    end_date=end_date,
                    provider=selected_provider,
                    **original_kwargs,
                )

            finance_country = country or "china"
            token = set_gdp_nominal_country_context(finance_country)
            try:
                return self._run(
                    "/economy/gdp/nominal",
                    **filter_inputs(
                        provider_choices={"provider": selected_provider},
                        standard_params={
                            "start_date": start_date,
                            "end_date": end_date,
                            "country": finance_country,
                        },
                        extra_params=kwargs,
                    ),
                )
            finally:
                reset_gdp_nominal_country_context(token)

        ROUTER_economy.available_indicators = available_indicators
        ROUTER_economy.indicators = indicators
        ROUTER_economy.cpi = cpi
        ROUTER_economy_gdp.nominal = nominal
    except Exception:
        return


def _patch_technical_indicators_route() -> None:
    """Expose finance technical indicators on the generated OpenBB technical router."""
    try:
        from datetime import date as dateType
        from typing import Annotated, Any, Literal, Optional

        from openbb.package.technical import ROUTER_technical
        from openbb_core.app.model.field import OpenBBField
        from openbb_core.app.model.obbject import OBBject
        from openbb_core.app.static.utils.decorators import exception_handler, validate
        from openbb_core.provider.utils.helpers import run_async

        @exception_handler
        @validate
        def indicators(
            self,
            symbol: Annotated[str, OpenBBField(description="Symbol to get technical indicators for.")],
            start_date: Annotated[
                dateType | str | None,
                OpenBBField(description="Start date of the historical data, in YYYY-MM-DD format."),
            ] = None,
            end_date: Annotated[
                dateType | str | None,
                OpenBBField(description="End date of the historical data, in YYYY-MM-DD format."),
            ] = None,
            interval: Annotated[str, OpenBBField(description="Price interval, e.g. 1d, 1w, 5m, 15m.")] = "1d",
            adjusted: Annotated[bool, OpenBBField(description="Whether to request adjusted prices.")] = False,
            indicators: Annotated[
                list[Literal["rsi", "macd", "sma", "ema", "bbands", "atr", "stoch", "vwap"]] | None,
                OpenBBField(description="Technical indicators to compute."),
            ] = None,
            provider: Annotated[
                Optional[Literal["finance"]],
                OpenBBField(description="The provider to use, by default finance."),
            ] = None,
            **kwargs: Any,
        ) -> OBBject:
            selected_provider = self._get_provider(provider, "technical.indicators", ("finance",))
            params = {
                "symbol": symbol,
                "start_date": start_date,
                "end_date": end_date,
                "interval": interval,
                "adjusted": adjusted,
                **kwargs,
            }
            if indicators is not None:
                params["indicators"] = indicators

            results = run_async(
                FinanceTechnicalIndicatorsFetcher.fetch_data,
                params=params,
                credentials=None,
            )
            obbject = OBBject(results=results, provider=selected_provider)
            output_type = self._command_runner.user_settings.preferences.output_type
            if output_type == "OBBject":
                return obbject
            return getattr(obbject, "to_" + output_type)()

        ROUTER_technical.indicators = indicators
    except Exception:
        return


def _patch_technical_indicators_coverage() -> None:
    """Register the patched technical indicators route in OpenBB coverage metadata."""
    try:
        from openbb_core.app.static.coverage import Coverage

        command = ".technical.indicators"
        model = "TechnicalIndicators"

        if not getattr(Coverage, "_finance_technical_indicators_coverage_patched", False):
            original_providers = Coverage.providers.fget
            original_commands = Coverage.commands.fget
            original_command_model = Coverage.command_model.fget

            def providers(self):
                coverage = original_providers(self)
                coverage.setdefault("finance", [])
                if command not in coverage["finance"]:
                    coverage["finance"].append(command)
                return coverage

            def commands(self):
                coverage = original_commands(self)
                coverage.setdefault(command, [])
                if "finance" not in coverage[command]:
                    coverage[command].append("finance")
                return coverage

            def command_model(self):
                coverage = original_command_model(self)
                coverage[command] = self._provider_interface.map[model]  # noqa: SLF001
                return coverage

            Coverage.providers = property(providers)
            Coverage.commands = property(commands)
            Coverage.command_model = property(command_model)
            Coverage._finance_technical_indicators_coverage_patched = True
    except Exception:
        return


_patch_etf_search_route()
_patch_equity_screener_route()
_patch_economy_macro_routes()
_patch_technical_indicators_route()
_patch_technical_indicators_coverage()
