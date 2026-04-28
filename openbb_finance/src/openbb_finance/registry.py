"""Registry for pluggable finance data sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from openbb_finance.config import get_source_config
from openbb_finance.sources.base import DataSource, DataType, Market


@dataclass
class DataSourceRegistry:
    sources: dict[str, DataSource] = field(default_factory=dict)

    def register(self, source: DataSource) -> None:
        self.sources[source.name] = source

    def unregister(self, name: str) -> None:
        self.sources.pop(name, None)

    def get(self, name: str) -> DataSource | None:
        return self.sources.get(name)

    def enabled_sources(self, market: Market, data_type: DataType, **kwargs: Any) -> list[DataSource]:
        return sorted(
            [
                source
                for source in self.sources.values()
                if source.enabled and source.supports(market, data_type, **kwargs)
            ],
            key=lambda source: source.priority,
            reverse=True,
        )

    def ordered_by_names(self, names: list[str]) -> list[DataSource]:
        return [source for name in names if (source := self.sources.get(name)) and source.enabled]


def build_default_registry() -> DataSourceRegistry:
    from openbb_finance.sources.akshare import AkshareSource
    from openbb_finance.sources.baostock import BaostockSource
    from openbb_finance.sources.futunn import FutunnSource
    from openbb_finance.sources.openbb import OpenbbSource
    from openbb_finance.sources.tickflow import TickflowSource
    from openbb_finance.sources.yahoo import YahooSource

    registry = DataSourceRegistry()
    for source_cls in [AkshareSource, BaostockSource, TickflowSource, FutunnSource, YahooSource, OpenbbSource]:
        config = get_source_config(source_cls.name)
        registry.register(source_cls(config))
    return registry
