from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .schemas import Candle, Timeframe


@dataclass(frozen=True)
class MarketDataWindow:
    timeframe: Timeframe
    start: datetime
    end: datetime


def _parse_history_payload(payload: dict[str, Any]) -> list[Candle]:
    candles_raw = payload.get("candles")
    if not isinstance(candles_raw, list):
        return []
    out: list[Candle] = []
    for c in candles_raw:
        if not isinstance(c, dict):
            continue
        try:
            out.append(Candle.model_validate(c))
        except Exception:
            continue
    return out


def _default_mcp_command() -> tuple[str, list[str]]:
    # Prefer invoking as module, same pattern as mise task: `uv run python -m mcp_server.main`
    # Here we run it via uv so workspace deps resolve.
    cmd = os.getenv("WYCKOFF_MCP_COMMAND", "uv")
    args_s = os.getenv("WYCKOFF_MCP_ARGS", "run python -m mcp_server.main")
    return cmd, args_s.split()


async def _call_fetch_stock_history(
    *,
    session: ClientSession,
    symbol: str,
    timeframe: Timeframe,
    range_bars: int,
    to: int | None,
) -> list[Candle]:
    result = await session.call_tool(
        "fetch_stock_history",
        {
            "symbol": symbol,
            "timeframe": timeframe.value,
            "range": range_bars,
            **({"to": to} if to is not None else {}),
        },
    )

    # mcp-server returns a JSON string.
    if not result.content:
        return []
    text = getattr(result.content[0], "text", None)
    if not isinstance(text, str):
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    if payload.get("error"):
        return []
    return _parse_history_payload(payload)


async def fetch_window(
    *,
    symbol: str,
    window: MarketDataWindow,
    max_chunk_bars: int = 2000,
) -> list[Candle]:
    """Fetch candles for a [start,end] window.

    Notes:
    - TradingView range/to uses end time as an anchor; we fetch backward in chunks.
    - We do not assume a fixed "1 year" bar count; we fetch until start reached.

    Performance:
    - Starts ONE stdio MCP session and reuses it across chunk calls.
    """

    # Defensive: enforce 1m window limit 14d
    if window.timeframe == Timeframe.minute_1:
        max_start = window.end - timedelta(days=14)
        if window.start < max_start:
            window = MarketDataWindow(
                timeframe=window.timeframe, start=max_start, end=window.end
            )

    cmd, args = _default_mcp_command()
    server_params = StdioServerParameters(command=cmd, args=args, env=os.environ)

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await _fetch_window_with_session(
                session=session,
                symbol=symbol,
                window=window,
                max_chunk_bars=max_chunk_bars,
            )


async def _fetch_window_with_session(
    *,
    session: ClientSession,
    symbol: str,
    window: MarketDataWindow,
    max_chunk_bars: int,
) -> list[Candle]:
    all_candles: list[Candle] = []
    to_s = int(window.end.timestamp())

    safety_iters = 0
    while safety_iters < 50:
        safety_iters += 1

        chunk = await _call_fetch_stock_history(
            session=session,
            symbol=symbol,
            timeframe=window.timeframe,
            range_bars=max_chunk_bars,
            to=to_s,
        )
        if not chunk:
            break

        all_candles.extend(chunk)

        oldest = min(chunk, key=lambda c: c.time)
        if datetime.fromtimestamp(oldest.time, tz=UTC) <= window.start:
            break

        # Move anchor backward.
        to_s = oldest.time

    uniq: dict[int, Candle] = {c.time: c for c in all_candles}
    merged = sorted(uniq.values(), key=lambda c: c.time)

    start_s = int(window.start.timestamp())
    end_s = int(window.end.timestamp())
    return [c for c in merged if start_s <= c.time <= end_s]
