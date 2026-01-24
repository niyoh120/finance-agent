"""威科夫分析流程

该模块提供威科夫分析的主流程函数，包括：
- run_default: 默认分析（4H/1年）
- run_intraday: 日内分析（1m/14天）
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import plotly.graph_objects as go
from pydantic_ai import ModelMessage

from .indicators import compute_moving_averages
from .logging_utils import log_agent_messages
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

logger = logging.getLogger(__name__)


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


async def run_default(
    agent, symbol_msg: str
) -> tuple[RunArtifacts, list[ModelMessage]]:
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

    # 2. LLM 自主运行（会调用 MCP tools 获取数据）
    logger.info("Wyckoff analysis start: symbol=%s mode=default", symbol_msg)
    try:
        async with agent:
            result = await agent.run(
                f"请分析用户提问中的股票的威科夫结构，使用天周期（timeframe='D'），"
                f"覆盖约 1 年数据（range=365）, 再回答用户的问题。 "
                f"如果提问只有股票代码，那么就只分析威科夫结构。"
                f"用户的提问: {symbol_msg}"
            )
    except Exception:
        logger.exception("Wyckoff agent run failed: symbol=%s mode=default", symbol_msg)
        raise

    # 3. 从消息历史中提取 K 线数据
    messages = result.new_messages()
    log_agent_messages(logger, messages)
    candles = extract_candles_from_messages(messages)
    timeframe = extract_timeframe_from_messages(messages) or Timeframe.hour_4

    # 检查是否成功获取数据
    if not candles:
        logger.error("No candles returned: symbol=%s mode=default", symbol_msg)
        raise RuntimeError(
            f"LLM 未能成功获取 {symbol_msg} 的 K 线数据。"
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
        symbol=symbol_msg,
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
    title = f"{symbol_msg} 威科夫结构标注图 ({timeframe.value})"
    fig = build_wyckoff_figure(
        symbol=symbol_msg,
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
        out_dir = _artifact_dir() / symbol_msg.replace(":", "_")
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
    ), result.all_messages()
