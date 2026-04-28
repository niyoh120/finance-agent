"""Priority-aware multi-source aggregation."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class AggregationSource(Protocol):
    name: str
    priority: int
    enabled: bool


FetchFn = Callable[[AggregationSource], Awaitable[Iterable[dict[str, Any]]]]


async def aggregate_records(
    sources: Iterable[AggregationSource],
    fetch: FetchFn,
    *,
    key_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Merge records by key, keeping the highest-priority non-null value per field."""

    merged: dict[tuple[Any, ...], dict[str, tuple[Any, int, str]]] = {}

    for source in sorted(sources, key=lambda item: item.priority, reverse=True):
        if not source.enabled:
            continue
        try:
            records = await fetch(source)
        except Exception as exc:  # noqa: BLE001
            logger.warning("data source failed source=%s error=%s", source.name, exc)
            continue

        for record in records:
            key = tuple(record.get(field) for field in key_fields)
            if any(value is None for value in key):
                continue
            current = merged.setdefault(key, {})
            for field, value in record.items():
                if value is None:
                    continue
                existing = current.get(field)
                if existing is None or source.priority > existing[1]:
                    current[field] = (value, source.priority, source.name)

    results: list[dict[str, Any]] = []
    for key, fields in merged.items():
        item = {field: value for field, value in zip(key_fields, key, strict=True)}
        for field, (value, _, source_name) in fields.items():
            item[field] = value
            item[f"{field}_source"] = source_name
        results.append(item)
    return results
