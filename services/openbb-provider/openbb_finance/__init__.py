"""OpenBB finance provider."""

from openbb_core.provider.abstract.provider import Provider

from openbb_finance.models.options_unusual import FinanceOptionsUnusualFetcher

provider = Provider(
    name="finance",
    website="https://unusualwhales.com",
    description="Options unusual flow data backed by finance-agent PostgreSQL cache.",
    credentials=None,
    fetcher_dict={"OptionsUnusual": FinanceOptionsUnusualFetcher},
)
