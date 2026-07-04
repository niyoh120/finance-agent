"""OpenBB built-in source placeholder."""

from __future__ import annotations

from typing import Any

from openbb_finance.config import SourceConfig
from openbb_finance.sources.base import DataType, Market


class OpenbbSource:
    name = "openbb"

    def __init__(self, config: SourceConfig) -> None:
        self.enabled = config.enabled

    def supports(self, market: Market, data_type: DataType, **kwargs: Any) -> bool:
        del market, kwargs
        return data_type in {"news", "calendar", "fundamental", "macro"}
