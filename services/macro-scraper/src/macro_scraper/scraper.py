from __future__ import annotations

from datetime import date
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://macro-dashboard-backend-f0x7.onrender.com/api/v1"


def normalize_base_url(raw_url: str) -> str:
    value = raw_url.strip().rstrip("/")
    if not value:
        return DEFAULT_BASE_URL
    if not value.endswith("/api/v1"):
        value = f"{value}/api/v1"
    return value


class MacroScraper:
    def __init__(self, client: httpx.AsyncClient, base_url: str) -> None:
        self.client = client
        self.base_url = normalize_base_url(base_url)

    async def _get_json(
        self, path: str, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        response = await self.client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    async def fetch_dashboard(self) -> dict[str, Any]:
        return await self._get_json("dashboard")

    async def fetch_report(self) -> dict[str, Any]:
        return await self._get_json("export/report")

    async def fetch_total_index_history(
        self, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        payload = await self._get_json(
            "dashboard/total-index/history",
            params={
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )
        data = payload.get("data")
        return data if isinstance(data, list) else []

    async def fetch_module_history(
        self, module_id: str, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        payload = await self._get_json(
            f"modules/{module_id}/history",
            params={
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )
        data = payload.get("data")
        return data if isinstance(data, list) else []
