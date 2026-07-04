"""Registry for pluggable finance data sources."""

from __future__ import annotations

from dataclasses import dataclass, field

from openbb_finance.config import get_source_config
from openbb_finance.sources.base import DataSource


@dataclass
class DataSourceRegistry:
    sources: dict[str, DataSource] = field(default_factory=dict)

    def register(self, source: DataSource) -> None:
        self.sources[source.name] = source

    def unregister(self, name: str) -> None:
        self.sources.pop(name, None)

    def get(self, name: str) -> DataSource | None:
        return self.sources.get(name)

    def ordered_by_names(self, names: list[str]) -> list[DataSource]:
        """Return enabled sources in the order their names appear in *names*.

        The list order IS the priority: callers pass ["tdx", "tickflow", ...]
        and the first source that returns data wins. No numeric priority field.
        """
        return [source for name in names if (source := self.sources.get(name)) and source.enabled]


def build_default_registry() -> DataSourceRegistry:
    from openbb_finance.sources.akshare import AkshareSource
    from openbb_finance.sources.baostock import BaostockSource
    from openbb_finance.sources.eastmoney import EastmoneySource
    from openbb_finance.sources.finnhub import FinnhubSource
    from openbb_finance.sources.futunn import FutunnSource
    from openbb_finance.sources.openbb import OpenbbSource
    from openbb_finance.sources.sina import SinaSource
    from openbb_finance.sources.tdx import TdxSource
    from openbb_finance.sources.tickflow import TickflowSource

    registry = DataSourceRegistry()
    for source_cls in [
        TdxSource,
        AkshareSource,
        BaostockSource,
        SinaSource,
        EastmoneySource,
        TickflowSource,
        FinnhubSource,
        FutunnSource,
        OpenbbSource,
    ]:
        config = get_source_config(source_cls.name)
        registry.register(source_cls(config))
    return registry
