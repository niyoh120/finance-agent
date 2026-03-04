from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from shared.database import session_scope
from shared.logging import configure_logging
from shared.models.macro import (
    MacroFactorSnapshot,
    MacroModuleHistory,
    MacroModuleSnapshot,
    MacroReport,
    MacroTotalIndexHistory,
)
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from .scraper import DEFAULT_BASE_URL, MacroScraper

configure_logging(service="macro-scraper")
logger = logging.getLogger(__name__)


def parse_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default

    normalized = value.strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def get_base_url() -> str:
    value = os.getenv("FA_MACRO_SCRAPER_BASE_URL")
    if value and value.strip():
        return value
    return DEFAULT_BASE_URL


def get_poll_interval() -> int:
    return parse_int(os.getenv("FA_MACRO_SCRAPER_POLL_INTERVAL"), 3600)


def get_history_days() -> int:
    return parse_int(os.getenv("FA_MACRO_SCRAPER_HISTORY_DAYS"), 365)


def get_enable_protected_endpoints() -> bool:
    return parse_bool(
        os.getenv("FA_MACRO_SCRAPER_ENABLE_PROTECTED_ENDPOINTS"),
        False,
    )


def parse_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return None


def to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def to_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def extract_modules(dashboard: dict[str, Any], report: dict[str, Any]) -> list[dict[str, Any]]:
    modules = dashboard.get("modules") if isinstance(dashboard, dict) else None
    if not isinstance(modules, list):
        modules = report.get("modules") if isinstance(report, dict) else None
    return modules if isinstance(modules, list) else []


def build_module_map(
    modules: list[dict[str, Any]],
) -> dict[str, tuple[str | None, str | None]]:
    mapping: dict[str, tuple[str | None, str | None]] = {}
    for module in modules:
        if not isinstance(module, dict):
            continue
        module_id = module.get("id") or module.get("module_id")
        if not module_id:
            continue
        mapping[str(module_id)] = (
            to_str(module.get("name")),
            to_str(module.get("name_cn")),
        )
    return mapping


async def get_latest_total_index_date(session) -> date | None:
    result = await session.execute(select(func.max(MacroTotalIndexHistory.date)))
    return result.scalar_one_or_none()


async def get_latest_module_date(session, module_id: str) -> date | None:
    result = await session.execute(
        select(func.max(MacroModuleHistory.date)).where(MacroModuleHistory.module_id == module_id)
    )
    return result.scalar_one_or_none()


def compute_start_date(last_date: date | None, fallback: date) -> date:
    if last_date is None:
        return fallback
    return max(fallback, last_date + timedelta(days=1))


async def upsert_report(session, report: dict[str, Any]) -> tuple[int, int, int]:
    report_date = parse_date(report.get("report_date"))
    if report_date is None:
        logger.warning("Report missing report_date, skipping snapshot")
        return 0, 0, 0

    total_index = report.get("total_index") if isinstance(report.get("total_index"), dict) else {}
    report_row = {
        "report_date": report_date,
        "current_snapshot_date": parse_date(report.get("current_snapshot_date")),
        "compare_date": parse_date(report.get("compare_date")),
        "generated_at": parse_datetime(report.get("generated_at")),
        "current_score": to_float(total_index.get("current_score")),
        "compare_score": to_float(total_index.get("compare_score")),
        "change": to_float(total_index.get("change")),
        "change_pct": to_float(total_index.get("change_pct")),
    }

    report_stmt = insert(MacroReport).values(report_row)
    report_stmt = report_stmt.on_conflict_do_update(
        constraint="uq_macro_report",
        set_={
            "current_snapshot_date": report_stmt.excluded.current_snapshot_date,
            "compare_date": report_stmt.excluded.compare_date,
            "generated_at": report_stmt.excluded.generated_at,
            "current_score": report_stmt.excluded.current_score,
            "compare_score": report_stmt.excluded.compare_score,
            "change": report_stmt.excluded.change,
            "change_pct": report_stmt.excluded.change_pct,
        },
    )
    await session.execute(report_stmt)

    modules = report.get("modules") if isinstance(report.get("modules"), list) else []
    module_rows: list[dict[str, Any]] = []
    for module in modules:
        if not isinstance(module, dict):
            continue
        module_id = module.get("module_id") or module.get("id")
        if not module_id:
            continue
        module_rows.append(
            {
                "report_date": report_date,
                "module_id": str(module_id),
                "name": to_str(module.get("name")),
                "name_cn": to_str(module.get("name_cn")),
                "current_score": to_float(
                    module.get("current_score") if module.get("current_score") is not None else module.get("score")
                ),
                "compare_score": to_float(module.get("compare_score")),
                "change": to_float(module.get("change")),
                "change_pct": to_float(module.get("change_pct")),
            }
        )

    if module_rows:
        module_stmt = insert(MacroModuleSnapshot).values(module_rows)
        module_stmt = module_stmt.on_conflict_do_update(
            constraint="uq_macro_module_snapshot",
            set_={
                "name": module_stmt.excluded.name,
                "name_cn": module_stmt.excluded.name_cn,
                "current_score": module_stmt.excluded.current_score,
                "compare_score": module_stmt.excluded.compare_score,
                "change": module_stmt.excluded.change,
                "change_pct": module_stmt.excluded.change_pct,
            },
        )
        await session.execute(module_stmt)

    module_map = build_module_map(modules)

    factors = report.get("factors") if isinstance(report.get("factors"), list) else []
    factor_rows: list[dict[str, Any]] = []
    for factor in factors:
        if not isinstance(factor, dict):
            continue
        module_id = factor.get("module_id")
        factor_id = factor.get("factor_id")
        if not module_id or not factor_id:
            continue
        module_name, module_name_cn = module_map.get(str(module_id), (None, None))
        display_only = factor.get("display_only")
        display_only_value = display_only if isinstance(display_only, bool) else None
        factor_rows.append(
            {
                "report_date": report_date,
                "module_id": str(module_id),
                "module_name": to_str(factor.get("module_name")) or module_name,
                "module_name_cn": to_str(factor.get("module_name_cn")) or module_name_cn,
                "factor_id": str(factor_id),
                "name": to_str(factor.get("name")),
                "name_cn": to_str(factor.get("name_cn")),
                "display_only": display_only_value,
                "current_value": to_float(factor.get("current_value")),
                "current_value_formatted": to_str(factor.get("current_value_formatted")),
                "current_percentile": to_float(factor.get("current_percentile")),
                "compare_value": to_float(factor.get("compare_value")),
                "compare_value_formatted": to_str(factor.get("compare_value_formatted")),
                "compare_percentile": to_float(factor.get("compare_percentile")),
                "value_change": to_float(factor.get("value_change")),
                "value_change_pct": to_float(factor.get("value_change_pct")),
                "percentile_change": to_float(factor.get("percentile_change")),
                "percentile_change_pct": to_float(factor.get("percentile_change_pct")),
                "color": to_str(factor.get("color")),
            }
        )

    if factor_rows:
        factor_stmt = insert(MacroFactorSnapshot).values(factor_rows)
        factor_stmt = factor_stmt.on_conflict_do_update(
            constraint="uq_macro_factor_snapshot",
            set_={
                "module_name": factor_stmt.excluded.module_name,
                "module_name_cn": factor_stmt.excluded.module_name_cn,
                "name": factor_stmt.excluded.name,
                "name_cn": factor_stmt.excluded.name_cn,
                "display_only": factor_stmt.excluded.display_only,
                "current_value": factor_stmt.excluded.current_value,
                "current_value_formatted": factor_stmt.excluded.current_value_formatted,
                "current_percentile": factor_stmt.excluded.current_percentile,
                "compare_value": factor_stmt.excluded.compare_value,
                "compare_value_formatted": factor_stmt.excluded.compare_value_formatted,
                "compare_percentile": factor_stmt.excluded.compare_percentile,
                "value_change": factor_stmt.excluded.value_change,
                "value_change_pct": factor_stmt.excluded.value_change_pct,
                "percentile_change": factor_stmt.excluded.percentile_change,
                "percentile_change_pct": factor_stmt.excluded.percentile_change_pct,
                "color": factor_stmt.excluded.color,
            },
        )
        await session.execute(factor_stmt)

    return 1, len(module_rows), len(factor_rows)


def build_total_index_rows(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        entry_date = parse_date(item.get("date"))
        if entry_date is None:
            continue
        rows.append(
            {
                "date": entry_date,
                "value": to_float(item.get("value")),
                "percentile": to_float(item.get("percentile")),
            }
        )
    return rows


def build_module_history_rows(
    module_id: str,
    module_name: str | None,
    module_name_cn: str | None,
    data: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        entry_date = parse_date(item.get("date"))
        if entry_date is None:
            continue
        rows.append(
            {
                "module_id": module_id,
                "module_name": module_name,
                "module_name_cn": module_name_cn,
                "date": entry_date,
                "value": to_float(item.get("value")),
                "percentile": to_float(item.get("percentile")),
            }
        )
    return rows


async def upsert_total_index_history(session, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    stmt = insert(MacroTotalIndexHistory).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_macro_total_index_history",
        set_={
            "value": stmt.excluded.value,
            "percentile": stmt.excluded.percentile,
        },
    )
    await session.execute(stmt)
    return len(rows)


async def upsert_module_history(session, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    stmt = insert(MacroModuleHistory).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_macro_module_history",
        set_={
            "module_name": stmt.excluded.module_name,
            "module_name_cn": stmt.excluded.module_name_cn,
            "value": stmt.excluded.value,
            "percentile": stmt.excluded.percentile,
        },
    )
    await session.execute(stmt)
    return len(rows)


async def fetch_dashboard(scraper: MacroScraper) -> dict[str, Any]:
    try:
        return await scraper.fetch_dashboard()
    except httpx.HTTPError as exc:
        logger.warning("Failed to fetch dashboard: %s", exc)
        return {}


async def fetch_report(scraper: MacroScraper) -> dict[str, Any]:
    try:
        return await scraper.fetch_report()
    except httpx.HTTPError as exc:
        logger.warning("Failed to fetch report: %s", exc)
        return {}


async def fetch_total_history(scraper: MacroScraper, start_date: date, end_date: date) -> list[dict[str, Any]]:
    try:
        return await scraper.fetch_total_index_history(start_date, end_date)
    except httpx.HTTPError as exc:
        logger.warning("Failed to fetch total index history: %s", exc)
        return []


async def fetch_module_history(
    scraper: MacroScraper, module_id: str, start_date: date, end_date: date
) -> list[dict[str, Any]]:
    try:
        return await scraper.fetch_module_history(module_id, start_date, end_date)
    except httpx.HTTPError as exc:
        logger.warning("Failed to fetch module %s history: %s", module_id, exc)
        return []


async def run_cycle(
    scraper: MacroScraper,
    history_days: int,
    enable_protected_endpoints: bool,
) -> None:
    dashboard = await fetch_dashboard(scraper)
    report: dict[str, Any] = {}
    if enable_protected_endpoints:
        report = await fetch_report(scraper)
    else:
        logger.info("Skipping protected endpoint export/report (FA_MACRO_SCRAPER_ENABLE_PROTECTED_ENDPOINTS=false)")

    modules = extract_modules(dashboard, report)
    module_map = build_module_map(modules)

    report_counts = (0, 0, 0)
    async with session_scope() as session:
        if report:
            report_counts = await upsert_report(session, report)

    end_date = datetime.now(UTC).date()
    default_start = end_date - timedelta(days=history_days)

    async with session_scope() as session:
        total_last = await get_latest_total_index_date(session)
        total_start = compute_start_date(total_last, default_start)
        module_windows: dict[str, date] = {}
        for module_id in module_map:
            last_date = await get_latest_module_date(session, module_id)
            start_date = compute_start_date(last_date, default_start)
            if start_date <= end_date:
                module_windows[module_id] = start_date

    total_rows: list[dict[str, Any]] = []
    if total_start <= end_date:
        total_rows = build_total_index_rows(await fetch_total_history(scraper, total_start, end_date))

    module_history_rows: list[dict[str, Any]] = []
    module_requests = list(module_windows.items())
    if module_requests:
        tasks = [
            fetch_module_history(scraper, module_id, start_date, end_date) for module_id, start_date in module_requests
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for (module_id, _), result in zip(module_requests, results):
            if isinstance(result, Exception):
                logger.warning("Module history task failed for %s: %s", module_id, result)
                continue
            module_name, module_name_cn = module_map.get(module_id, (None, None))
            module_history_rows.extend(build_module_history_rows(module_id, module_name, module_name_cn, result))

    history_counts = (0, 0)
    async with session_scope() as session:
        total_saved = await upsert_total_index_history(session, total_rows)
        module_saved = await upsert_module_history(session, module_history_rows)
        history_counts = (total_saved, module_saved)

    logger.info(
        "Macro cycle complete protected_endpoints=%s report_rows=%s module_snapshots=%s factor_snapshots=%s total_history=%s module_history=%s",
        enable_protected_endpoints,
        report_counts[0],
        report_counts[1],
        report_counts[2],
        history_counts[0],
        history_counts[1],
    )


async def main() -> None:
    poll_interval = get_poll_interval()
    history_days = get_history_days()
    enable_protected_endpoints = get_enable_protected_endpoints()

    logger.info(
        "Starting Macro Scraper base_url=%s poll=%ss history_days=%s protected_endpoints=%s",
        get_base_url(),
        poll_interval,
        history_days,
        enable_protected_endpoints,
    )

    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        scraper = MacroScraper(client, get_base_url())
        while True:
            start_time = datetime.now(UTC)
            try:
                await run_cycle(scraper, history_days, enable_protected_endpoints)
            except Exception as exc:
                logger.exception("Macro scraper cycle failed: %s", exc)

            elapsed = (datetime.now(UTC) - start_time).total_seconds()
            sleep_time = max(1, poll_interval - elapsed)
            await asyncio.sleep(sleep_time)


if __name__ == "__main__":
    asyncio.run(main())
