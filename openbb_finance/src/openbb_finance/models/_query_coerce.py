"""Shared QueryParams base for ConvexValue-backed models.

The OpenBB API layer wraps fetcher QueryParams in a dynamic class whose unset
fields default to Query(...) markers (used for API docs). When those markers
reach a Literal/list-typed field, Pydantic rejects them. CV models inherit
this base so a single before-validator replaces Query objects with the field's
declared default (or drops the key if there is no default, letting Pydantic
apply its own missing-value handling).
"""

from __future__ import annotations

from typing import Any

from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import model_validator


def _is_query_marker(value: Any) -> bool:
    return type(value).__name__ == "Query"


class ConvexValueQueryParams(QueryParams):
    """QueryParams base that strips openbb Query(...) defaults before validation."""

    @model_validator(mode="before")
    @classmethod
    def _strip_query_markers(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        cleaned: dict[str, Any] = {}
        for key, value in values.items():
            if _is_query_marker(value):
                # Replace the marker with the field's declared default; if the
                # field has no default, drop the key so Pydantic treats it as
                # missing (and applies the default declared on the Field).
                field = cls.model_fields.get(key) if hasattr(cls, "model_fields") else None
                if field is not None and not field.is_required():
                    cleaned[key] = field.get_default(call_default_factory=True)
                # else: omit the key entirely
            else:
                cleaned[key] = value
        return cleaned
