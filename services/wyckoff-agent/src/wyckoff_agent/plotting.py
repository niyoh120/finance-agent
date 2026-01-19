from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .schemas import Candle, MovingAverages, WyckoffEvent, WyckoffPhase, WyckoffZone


@dataclass(frozen=True)
class PlotStyle:
    price_increasing: str = "#2ca02c"
    price_decreasing: str = "#d62728"
    ma50: str = "#1f77b4"
    ma200: str = "#d62728"
    zone_accumulation: str = "rgba(46, 204, 113, 0.18)"
    zone_distribution: str = "rgba(231, 76, 60, 0.18)"


def build_wyckoff_figure(
    *,
    symbol: str,
    timeframe: str,
    candles: list[Candle],
    ma: MovingAverages | None,
    zones: list[WyckoffZone],
    phases: list[WyckoffPhase],
    events: list[WyckoffEvent],
    title: str,
    style: PlotStyle = PlotStyle(),
) -> go.Figure:
    """Build Plotly figure for candlestick+MAs+volume and Wyckoff overlays.

    Contract:
    - Row 1: price (candlestick) + MA50/MA200
    - Row 2: volume bars
    - shapes: vrect zones, vline phases (added later), annotations for events
    """

    x = [datetime.fromtimestamp(c.time) for c in candles]

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.02,
        row_heights=[0.75, 0.25],
    )

    fig.add_trace(
        go.Candlestick(
            x=x,
            open=[c.open for c in candles],
            high=[c.high for c in candles],
            low=[c.low for c in candles],
            close=[c.close for c in candles],
            increasing_line_color=style.price_increasing,
            decreasing_line_color=style.price_decreasing,
            name=f"{symbol} {timeframe}",
        ),
        row=1,
        col=1,
    )

    if ma is not None:
        fig.add_trace(
            go.Scatter(
                x=x,
                y=ma.ma50,
                mode="lines",
                line=dict(color=style.ma50, dash="dash"),
                name="MA50",
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=x,
                y=ma.ma200,
                mode="lines",
                line=dict(color=style.ma200, dash="dash"),
                name="MA200",
            ),
            row=1,
            col=1,
        )

    vol = [c.volume or 0.0 for c in candles]
    fig.add_trace(
        go.Bar(x=x, y=vol, name="Volume", marker_color="rgba(120,120,120,0.5)"),
        row=2,
        col=1,
    )

    for zone in zones:
        fill = (
            style.zone_accumulation
            if zone.kind.value == "accumulation"
            else style.zone_distribution
        )
        fig.add_vrect(
            x0=zone.x0,
            x1=zone.x1,
            y0=zone.y_low,
            y1=zone.y_high,
            fillcolor=fill,
            opacity=1.0,
            line_width=0,
            layer="below",
            row=1,
            col=1,
        )

    # Phase separators and labels
    for ph in phases:
        fig.add_vline(
            x=ph.start,
            line_width=3,
            line_dash="dash",
            line_color="black",
        )
        fig.add_annotation(
            x=ph.start,
            y=1.02,
            xref="x",
            yref="paper",
            text=ph.name.value,
            showarrow=False,
            font=dict(color="#cc0000", size=18),
        )

    for event in events:
        fig.add_annotation(
            x=event.timestamp,
            y=event.price,
            xref="x",
            yref="y",
            text=event.reason.replace("\n", "<br>"),
            showarrow=True,
            arrowhead=2,
            ax=40,
            ay=-40,
            bgcolor="rgba(255,255,255,0.8)",
            bordercolor="rgba(0,0,0,0.2)",
            font=dict(color="#111", size=12),
        )

    fig.update_layout(
        title=title,
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h"),
        margin=dict(l=40, r=20, t=80, b=40),
        font=dict(family="SimHei, Noto Sans CJK SC, Microsoft YaHei, Arial"),
    )

    return fig
