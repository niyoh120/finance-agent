from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from .compress import CompressedSeries, extract_pivots
from .schemas import (
    MovingAverages,
    Timeframe,
    WyckoffOverlay,
)


@dataclass(frozen=True)
class LlmConfig:
    base_url: str
    api_key: str
    model: str


def build_openai_compatible_agent(*, cfg: LlmConfig) -> Agent[None, WyckoffOverlay]:
    model = OpenAIChatModel(
        cfg.model,
        provider=OpenAIProvider(base_url=cfg.base_url, api_key=cfg.api_key),
    )

    system_prompt = (
        "你是交易史上最伟大的人物：理查德·D·威科夫（Richard D. Wyckoff）。\n"
        "你必须客观、严谨，不迎合用户。\n"
        "输出必须为中文，术语使用威科夫体系（SC/AR/ST/Spring/LPS/SOS/UTAD/Phase A-E等）。\n"
        "注意：不要强行凑齐阶段或事件，只输出你能从数据中合理识别到的部分。\n"
        "重要：给出吸筹/派发区时，y_low/y_high 请尽量体现 Phase B 收盘价最密集区间（可用分位数近似），不要简单用全局极值。"
    )

    return Agent(model=model, system_prompt=system_prompt, output_type=WyckoffOverlay)


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def build_overlay_prompt(
    *,
    symbol: str,
    timeframe: Timeframe,
    start: datetime,
    end: datetime,
    ma: MovingAverages | None,
    pivots: CompressedSeries,
    volume_spikes: list[dict],
    close_quantiles: dict[str, float],
) -> str:
    parts: list[str] = []

    parts.append(f"标的：{symbol}")
    parts.append(f"周期：{timeframe.value}")
    parts.append(f"时间范围：{start.isoformat()} ~ {end.isoformat()}")

    if ma is not None:
        parts.append(f"MA 交叉数：{len(ma.crosses)}")
        if ma.crosses:
            parts.append(
                "MA 交叉（最多5条）：\n"
                + "\n".join(
                    [
                        f"- {c.kind} @ {c.timestamp.isoformat()} close≈{c.price}"
                        for c in ma.crosses[:5]
                    ]
                )
            )

    parts.append(
        "收盘价分位数：\n"
        + "\n".join([f"- {k}: {v:.4f}" for k, v in close_quantiles.items()])
    )

    parts.append(f"拐点数（压缩后）：{len(pivots.pivots)}")
    if pivots.pivots:
        parts.append(
            "关键拐点（按时间，最多60个）：\n"
            + "\n".join(
                [
                    f"- {p.timestamp.isoformat()} {p.kind} {p.price:.4f} vol={p.volume}"
                    for p in pivots.pivots[:60]
                ]
            )
        )

    if volume_spikes:
        parts.append(
            "放量候选点（最多20个）：\n"
            + "\n".join(
                [
                    f"- {v['ts']} close={v['close']} vol={v['vol']}"
                    for v in volume_spikes[:20]
                ]
            )
        )

    parts.append(
        "\n你的任务：\n"
        "1) 用威科夫价格周期判断背景：吸筹/派发/趋势（markup/markdown）/区间，并给置信度。\n"
        "2) 识别并输出你能确认的 Phase（A-E，最多到你能确认的阶段，不要硬凑）。\n"
        "3) 识别关键事件（SC/AR/ST/Spring/LPS/SOS/UTAD/JAC 等），每条必须包含：术语 + 一句理由（可换行），并给出坐标（timestamp, price）。\n"
        "4) 如你判断存在吸筹或派发区，请输出 zones：\n"
        "   - x0/x1 用关键事件区间（例如从 SC 到最后一次 SOS/JAC）。\n"
        "   - y_low/y_high 以 Phase B 收盘价密集区间为准（允许用分位数近似），不要包含极端影线带来的噪音。\n"
        "5) 给至少 3 种后续走势情景（概率之和约等于 1）。\n"
        "6) 给至少 3 套交易策略（正股多、短期期权、LEAPS call 等），含止损/止盈与风险提示。\n"
    )

    return "\n\n".join(parts)


def compute_close_quantiles(closes: list[float]) -> dict[str, float]:
    if not closes:
        return {"q20": 0.0, "q50": 0.0, "q80": 0.0}
    sorted_c = sorted(closes)

    def q(p: float) -> float:
        idx = int((len(sorted_c) - 1) * p)
        idx = max(0, min(idx, len(sorted_c) - 1))
        return float(sorted_c[idx])

    return {"q20": q(0.2), "q50": q(0.5), "q80": q(0.8), "q10": q(0.1), "q90": q(0.9)}


def volume_spike_summary(*, candles: list, top_k: int = 20) -> list[dict]:
    items = []
    for c in candles:
        vol = getattr(c, "volume", 0.0) or 0.0
        items.append((vol, c))
    items.sort(key=lambda x: x[0], reverse=True)

    out = []
    for vol, c in items[:top_k]:
        out.append(
            {
                "ts": datetime.fromtimestamp(c.time, tz=UTC).isoformat(),
                "close": float(c.close),
                "vol": float(vol),
            }
        )
    return out


def pivots_for_llm(*, candles: list, timeframe: Timeframe) -> CompressedSeries:
    # 4H: larger swing threshold
    min_swing_pct = 0.02 if timeframe == Timeframe.hour_4 else 0.005
    return extract_pivots(candles=candles, min_swing_pct=min_swing_pct, max_pivots=300)
