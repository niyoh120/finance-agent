from __future__ import annotations

from datetime import datetime

import plotly.graph_objects as go

from .plotting import PlotStyle, build_wyckoff_figure
from .schemas import Timeframe, WyckoffAnalysisResult


def render_default_figure(result: WyckoffAnalysisResult) -> go.Figure:
    # Choose the first timeframe in result for now.
    tf: Timeframe = result.timeframes_used[0]

    # The full candle series is not stored in result yet.
    # This function will be wired once we pass candles through analysis result.
    raise NotImplementedError("wire candles into analysis result before rendering")


def figure_to_json(fig: go.Figure) -> dict:
    return fig.to_plotly_json()


def figure_title(*, symbol: str, timeframe: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"{symbol} 威科夫结构标注图 ({timeframe}) - {now}"
