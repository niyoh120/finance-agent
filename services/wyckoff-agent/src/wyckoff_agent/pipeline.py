"""威科夫分析流程

该模块提供威科夫分析的主流程函数，包括：
- run_default: 默认分析（4H/1年）
- run_intraday: 日内分析（1m/14天）
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import plotly.graph_objects as go

from .agent import build_wyckoff_agent
from .indicators import compute_moving_averages
from .message_utils import (
    extract_candles_from_messages,
    extract_timeframe_from_messages,
)
from .plotting import build_wyckoff_figure
from .schemas import (
    CandlesMeta,
    Timeframe,
    WyckoffAnalysisResult,
)


@dataclass(frozen=True)
class RunArtifacts:
    """运行产物"""

    analysis: WyckoffAnalysisResult
    figure: go.Figure
    figure_json: dict
    analysis_json: dict
    png_path: str | None
    analysis_json_path: str | None
    figure_json_path: str | None


def _artifact_dir() -> Path:
    """获取 artifacts 保存目录"""
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
    """写入 JSON 文件"""
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def run_default(symbol: str) -> RunArtifacts:
    """运行默认威科夫分析（4H/1年）

    该函数会：
    1. 构建 Agent（带 MCP toolset）
    2. 让 LLM 自主获取数据并进行威科夫分析
    3. 从消息历史中提取 K 线数据用于绘图
    4. 保存分析结果和图表

    Args:
        symbol: 股票代码（如 "NASDAQ:AAPL"）

    Returns:
        RunArtifacts 包含分析结果、图表等
    """
    now = datetime.now(tz=UTC)

    # 1. 构建 Agent
    agent = build_wyckoff_agent()

    # 2. LLM 自主运行（会调用 MCP tools 获取数据）
    async with agent:
        result = await agent.run(
            f"请分析 {symbol} 的威科夫结构，使用 4H 周期（timeframe='240'），"
            f"覆盖约 1 年数据（range=2000）"
        )

    # 3. 从消息历史中提取 K 线数据
    candles = extract_candles_from_messages(result.new_messages())
    timeframe = (
        extract_timeframe_from_messages(result.new_messages()) or Timeframe.hour_4
    )

    # 检查是否成功获取数据
    if not candles:
        raise RuntimeError(
            f"LLM 未能成功获取 {symbol} 的 K 线数据。"
            f"请检查 MCP server 是否正常运行，或重试。"
        )

    # 4. 计算均线（应用层，用于绘图）
    ma = compute_moving_averages(timeframe=timeframe, candles=candles)

    # 5. 构建最终分析结果
    overlay = result.output  # WyckoffOverlay 类型

    # 计算时间窗口（从 K 线数据推断）
    start_time = datetime.fromtimestamp(min(c.time for c in candles), tz=UTC)
    end_time = datetime.fromtimestamp(max(c.time for c in candles), tz=UTC)

    analysis = WyckoffAnalysisResult(
        symbol=symbol,
        generated_at=now,
        timeframes_used=[timeframe],
        candles_meta=[
            CandlesMeta(
                timeframe=timeframe,
                start=start_time,
                end=end_time,
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

    # 6. 绘图（应用层）
    title = f"{symbol} 威科夫结构标注图 ({timeframe.value})"
    fig = build_wyckoff_figure(
        symbol=symbol,
        timeframe=timeframe.value,
        candles=candles,
        ma=ma,
        zones=analysis.zones,
        phases=analysis.phases,
        events=analysis.events,
        title=title,
    )

    # 7. 保存 artifacts
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
        # PNG export is best-effort
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


async def run_intraday(symbol: str) -> RunArtifacts:
    """运行日内威科夫分析（1m/14天）

    Args:
        symbol: 股票代码（如 "NASDAQ:TSLA"）

    Returns:
        RunArtifacts 包含分析结果、图表等
    """
    now = datetime.now(tz=UTC)

    # 构建 Agent
    agent = build_wyckoff_agent()

    # LLM 自主运行（日内分析）
    async with agent:
        result = await agent.run(
            f"请分析 {symbol} 的日内威科夫结构，使用 1 分钟周期（timeframe='1'），"
            f"覆盖最近数据（range=5000，注意 1 分钟线数据有 14 天限制）"
        )

    # 提取数据
    candles = extract_candles_from_messages(result.new_messages())
    timeframe = (
        extract_timeframe_from_messages(result.new_messages()) or Timeframe.minute_1
    )

    if not candles:
        raise RuntimeError(
            f"LLM 未能成功获取 {symbol} 的日内 K 线数据。"
            f"请检查 MCP server 是否正常运行，或重试。"
        )

    # 日内分析可选计算均线
    ma = None

    # 构建结果
    overlay = result.output

    start_time = datetime.fromtimestamp(min(c.time for c in candles), tz=UTC)
    end_time = datetime.fromtimestamp(max(c.time for c in candles), tz=UTC)

    analysis = WyckoffAnalysisResult(
        symbol=symbol,
        generated_at=now,
        timeframes_used=[timeframe],
        candles_meta=[
            CandlesMeta(
                timeframe=timeframe,
                start=start_time,
                end=end_time,
                count=len(candles),
            )
        ],
        wyckoff_context=overlay.wyckoff_context,
        phases=overlay.phases,
        events=overlay.events,
        zones=overlay.zones,
        moving_averages=[],
        scenarios=overlay.scenarios,
        strategies=overlay.strategies,
        summary=overlay.summary,
        details=overlay.details,
    )

    # 绘图
    title = f"{symbol} 日内威科夫结构 ({timeframe.value})"
    fig = build_wyckoff_figure(
        symbol=symbol,
        timeframe=timeframe.value,
        candles=candles,
        ma=ma,
        zones=analysis.zones,
        phases=analysis.phases,
        events=analysis.events,
        title=title,
    )

    # 保存 artifacts
    figure_json = fig.to_plotly_json()
    analysis_json = analysis.model_dump(mode="json")

    png_path = None
    analysis_json_path = None
    figure_json_path = None

    try:
        out_dir = _artifact_dir() / symbol.replace(":", "_")
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = now.strftime("%Y%m%d_%H%M%S")

        png = out_dir / f"wyckoff_intraday_{ts}.png"
        fig.write_image(str(png), width=1600, height=900, scale=2)
        png_path = str(png)

        aj = out_dir / f"analysis_intraday_{ts}.json"
        _write_json(aj, analysis_json)
        analysis_json_path = str(aj)

        fj = out_dir / f"figure_intraday_{ts}.json"
        _write_json(fj, figure_json)
        figure_json_path = str(fj)
    except Exception:
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
