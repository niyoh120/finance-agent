"""Multi-source aggregation.

Records from multiple sources are merged by key. When several sources provide
a value for the same field, the source that appears FIRST in the input list
wins (list order IS the priority). Later sources only fill fields that earlier
sources left as None.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class AggregationSource(Protocol):
    name: str
    enabled: bool


FetchFn = Callable[[AggregationSource], Awaitable[Iterable[dict[str, Any]]]]


async def aggregate_records(
    sources: Iterable[AggregationSource],
    fetch: FetchFn,
    *,
    key_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Merge records by key, keeping the first-source non-null value per field.

    The order of *sources* determines precedence: the first source's value for
    a field is kept; later sources only contribute fields the earlier sources
    did not populate.
    """

    # Materialize first so we can safely handle one-shot iterables/generators.
    # The list order IS the precedence (index 0 = highest, later sources only
    # fill fields the earlier sources did not populate).
    ordered = list(sources)

    # rank[source.name] = precedence (0 = highest). Later occurrences overwrite
    # so the earliest index wins, matching "first source wins" semantics.
    rank: dict[str, int] = {}
    for index, source in enumerate(ordered):
        rank[source.name] = rank.get(source.name, index)

    # field -> (value, rank, source_name). Lower rank wins.
    merged: dict[tuple[Any, ...], dict[str, tuple[Any, int, str]]] = {}

    for source in ordered:
        if not source.enabled:
            continue
        try:
            records = await fetch(source)
        except Exception as exc:  # noqa: BLE001
            logger.warning("data source failed source=%s error=%s", source.name, exc)
            continue

        source_rank = rank[source.name]
        for record in records:
            key = tuple(record.get(field) for field in key_fields)
            if any(value is None for value in key):
                continue
            current = merged.setdefault(key, {})
            for field, value in record.items():
                if value is None:
                    continue
                existing = current.get(field)
                if existing is None or source_rank < existing[1]:
                    current[field] = (value, source_rank, source.name)

    results: list[dict[str, Any]] = []
    for key, fields in merged.items():
        item: dict[str, Any] = {field: value for field, value in zip(key_fields, key, strict=True)}
        for field, (value, _, source_name) in fields.items():
            item[field] = value
            item[f"{field}_source"] = source_name
        results.append(item)
    return results
