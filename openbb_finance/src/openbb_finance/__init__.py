"""OpenBB finance provider."""

from openbb_core.provider.abstract.provider import Provider

from openbb_finance.config import apply_runtime_environment
from openbb_finance.models.company_news import FinanceCompanyNewsFetcher
from openbb_finance.models.economic_calendar import FinanceEconomicCalendarFetcher
from openbb_finance.models.equity_historical import FinanceEquityHistoricalFetcher
from openbb_finance.models.equity_quote import FinanceEquityQuoteFetcher
from openbb_finance.models.equity_search import FinanceEquitySearchFetcher
from openbb_finance.models.etf_historical import FinanceEtfHistoricalFetcher
from openbb_finance.models.etf_search import FinanceEtfSearchFetcher
from openbb_finance.models.index_available import FinanceAvailableIndicesFetcher
from openbb_finance.models.index_historical import FinanceIndexHistoricalFetcher
from openbb_finance.models.index_search import FinanceIndexSearchFetcher
from openbb_finance.models.index_snapshots import FinanceIndexSnapshotsFetcher
from openbb_finance.models.options_unusual import FinanceOptionsUnusualFetcher
from openbb_finance.models.world_news import FinanceWorldNewsFetcher

apply_runtime_environment()

provider = Provider(
    name="finance",
    website="https://github.com/niyoh120/finance-agent",
    description="Pluggable finance data provider for market data, calendars, news, and options flow.",
    credentials=None,
    fetcher_dict={
        "AvailableIndices": FinanceAvailableIndicesFetcher,
        "CompanyNews": FinanceCompanyNewsFetcher,
        "EconomicCalendar": FinanceEconomicCalendarFetcher,
        "EquityHistorical": FinanceEquityHistoricalFetcher,
        "EquityQuote": FinanceEquityQuoteFetcher,
        "EquitySearch": FinanceEquitySearchFetcher,
        "EtfHistorical": FinanceEtfHistoricalFetcher,
        "EtfSearch": FinanceEtfSearchFetcher,
        "IndexHistorical": FinanceIndexHistoricalFetcher,
        "IndexSearch": FinanceIndexSearchFetcher,
        "IndexSnapshots": FinanceIndexSnapshotsFetcher,
        "OptionsUnusual": FinanceOptionsUnusualFetcher,
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


_patch_etf_search_route()
