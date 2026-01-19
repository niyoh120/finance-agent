from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .schemas import (
    Candle,
    Timeframe,
    WyckoffEvent,
    WyckoffEventType,
    WyckoffZone,
    WyckoffZoneKind,
)


@dataclass(frozen=True)
class CandidateConfig:
    volume_spike_quantile: float = 0.95
    spring_break_pct: float = 0.01


def _dt(ts_s: int) -> datetime:
    return datetime.fromtimestamp(ts_s, tz=UTC)


def find_volume_spikes(
    *,
    candles: list[Candle],
    timeframe: Timeframe,
    config: CandidateConfig | None = None,
) -> list[WyckoffEvent]:
    """Generate volume spike *candidates* only.

    This is not Wyckoff labeling yet; it only surfaces locations worth attention.
    """

    if config is None:
        config = CandidateConfig()

    vols = [c.volume or 0.0 for c in candles]
    if not vols:
        return []

    sorted_vols = sorted(vols)
    idx = int(len(sorted_vols) * config.volume_spike_quantile)
    idx = min(max(idx, 0), len(sorted_vols) - 1)
    thresh = sorted_vols[idx]

    out: list[WyckoffEvent] = []
    for c in candles:
        v = c.volume or 0.0
        if v >= thresh and thresh > 0:
            out.append(
                WyckoffEvent(
                    type=WyckoffEventType.OTHER,
                    timestamp=_dt(c.time),
                    price=c.close,
                    timeframe=timeframe,
                    reason=(
                        f"放量（候选）：成交量显著高于近段分位数阈值（{config.volume_spike_quantile:.2f}）。\n"
                        "综合人常借助放量完成换手与吸收/派发，请结合结构位置复核。"
                    ),
                    extra={"volume": v, "threshold": thresh},
                )
            )
    return out


def guess_accumulation_zone(
    *,
    candles: list[Candle],
    timeframe: Timeframe,
) -> WyckoffZone | None:
    """Placeholder zone generator.

    Real zones come from Phase segmentation; this function only provides a
    conservative band for early rendering.
    """

    if len(candles) < 50:
        return None

    closes = [c.close for c in candles]
    sorted_c = sorted(closes)
    lo = sorted_c[int(len(sorted_c) * 0.2)]
    hi = sorted_c[int(len(sorted_c) * 0.8)]

    return WyckoffZone(
        kind=WyckoffZoneKind.ACCUMULATION,
        timeframe=timeframe,
        x0=_dt(candles[0].time),
        x1=_dt(candles[-1].time),
        y_low=lo,
        y_high=hi,
        reason=(
            "吸筹区（占位）：暂用收盘价分位数近似 Phase B 密集区间；"
            "后续以威科夫阶段识别精确裁剪（剔除 SC/AR 影线影响）"
        ),
    )
