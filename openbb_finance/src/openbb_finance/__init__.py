"""OpenBB finance provider."""

from openbb_core.provider.abstract.provider import Provider

from openbb_finance.config import apply_runtime_environment
from openbb_finance.models.company_news import FinanceCompanyNewsFetcher
from openbb_finance.models.economic_calendar import FinanceEconomicCalendarFetcher
from openbb_finance.models.equity_historical import FinanceEquityHistoricalFetcher
from openbb_finance.models.equity_quote import FinanceEquityQuoteFetcher
from openbb_finance.models.equity_search import FinanceEquitySearchFetcher
from openbb_finance.models.etf_historical import FinanceEtfHistoricalFetcher
from openbb_finance.models.index_historical import FinanceIndexHistoricalFetcher
from openbb_finance.models.options_unusual import FinanceOptionsUnusualFetcher

apply_runtime_environment()

provider = Provider(
    name="finance",
    website="https://github.com/niyoh120/finance-agent",
    description="Pluggable finance data provider for market data, calendars, news, and options flow.",
    credentials=None,
    fetcher_dict={
        "CompanyNews": FinanceCompanyNewsFetcher,
        "EconomicCalendar": FinanceEconomicCalendarFetcher,
        "EquityHistorical": FinanceEquityHistoricalFetcher,
        "EquityQuote": FinanceEquityQuoteFetcher,
        "EquitySearch": FinanceEquitySearchFetcher,
        "EtfHistorical": FinanceEtfHistoricalFetcher,
        "IndexHistorical": FinanceIndexHistoricalFetcher,
        "OptionsUnusual": FinanceOptionsUnusualFetcher,
    },
)
