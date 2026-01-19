from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import plotly.graph_objects as go

from .data_fetch import MarketDataWindow, fetch_window
from .indicators import compute_moving_averages
from .llm_overlay import (
    LlmConfig,
    build_openai_compatible_agent,
    build_overlay_prompt,
    compute_close_quantiles,
    pivots_for_llm,
    volume_spike_summary,
)
from .plotting import build_wyckoff_figure
from .schemas import (
    CandlesMeta,
    Timeframe,
    WyckoffAnalysisResult,
    WyckoffContext,
    WyckoffOverlay,
)


@dataclass(frozen=True)
class RunArtifacts:
    analysis: WyckoffAnalysisResult
    figure: go.Figure
    figure_json: dict
    analysis_json: dict
    png_path: str | None
    analysis_json_path: str | None
    figure_json_path: str | None


def _artifact_dir() -> Path:
    base = (
        Path(__file__).resolve().parent.parent.parent
        / "services"
        / "wyckoff-agent"
        / ".artifacts"
    )
    # Fallback: if running from service dir
    if not base.exists():
        base = Path.cwd() / ".artifacts"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def run_default(symbol: str) -> RunArtifacts:
    now = datetime.now(tz=UTC)
    window = MarketDataWindow(
        timeframe=Timeframe.hour_4, start=now - timedelta(days=365), end=now
    )
    candles = await fetch_window(symbol=symbol, window=window)

    ma = (
        compute_moving_averages(timeframe=Timeframe.hour_4, candles=candles)
        if candles
        else None
    )

    # LLM overlay (required)
    overlay: WyckoffOverlay  # type: ignore[valid-type]
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    base_url = os.getenv("OPENAI_BASE_URL", "").strip() or "https://api.openai.com/v1"
    model = os.getenv("OPENAI_MODEL", "").strip() or "gpt-4o"

    pivots = pivots_for_llm(candles=candles, timeframe=Timeframe.hour_4)
    vol_summary = volume_spike_summary(candles=candles)
    close_q = compute_close_quantiles([c.close for c in candles])

    if not api_key:
        raise RuntimeError("missing OPENAI_API_KEY")

    agent = build_openai_compatible_agent(
        cfg=LlmConfig(base_url=base_url, api_key=api_key, model=model)
    )
    prompt = build_overlay_prompt(
        symbol=symbol,
        timeframe=Timeframe.hour_4,
        start=window.start,
        end=window.end,
        ma=ma,
        pivots=pivots,
        volume_spikes=vol_summary,
        close_quantiles=close_q,
    )
    overlay = (await agent.run(prompt)).output

    analysis = WyckoffAnalysisResult(
        symbol=symbol,
        generated_at=now,
        timeframes_used=[Timeframe.hour_4],
        candles_meta=[
            CandlesMeta(
                timeframe=Timeframe.hour_4,
                start=window.start,
                end=window.end,
                count=len(candles),
            )
        ],
        wyckoff_context=overlay.wyckoff_context,
        phases=overlay.phases,
        events=overlay.events,
        zones=overlay.zones,
        moving_averages=[ma] if ma is not None else [],
        scenarios=overlay.scenarios,
        strategies=overlay.strategies,
        summary=overlay.summary,
        details=overlay.details,
    )

    title = f"{symbol} 威科夫结构标注图 (240)"
    fig = build_wyckoff_figure(
        symbol=symbol,
        timeframe=Timeframe.hour_4.value,
        candles=candles,
        ma=ma,
        zones=analysis.zones,
        phases=analysis.phases,
        events=analysis.events,
        title=title,
    )

    figure_json = fig.to_plotly_json()
    analysis_json = analysis.model_dump(mode="json")

    png_path = None
    analysis_json_path = None
    figure_json_path = None

    try:
        out_dir = _artifact_dir() / symbol.replace(":", "_")
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = now.strftime("%Y%m%d_%H%M%S")

        png = out_dir / f"wyckoff_{ts}.png"
        fig.write_image(str(png), width=1600, height=900, scale=2)
        png_path = str(png)

        aj = out_dir / f"analysis_{ts}.json"
        _write_json(aj, analysis_json)
        analysis_json_path = str(aj)

        fj = out_dir / f"figure_{ts}.json"
        _write_json(fj, figure_json)
        figure_json_path = str(fj)
    except Exception:
        # PNG export is best-effort; interactive plot still works.
        pass

    return RunArtifacts(
        analysis=analysis,
        figure=fig,
        figure_json=figure_json,
        analysis_json=analysis_json,
        png_path=png_path,
        analysis_json_path=analysis_json_path,
        figure_json_path=figure_json_path,
    )
