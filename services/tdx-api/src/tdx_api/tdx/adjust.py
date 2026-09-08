"""前复权（QFQ）纯函数与本地重算。

移植自 niyoh120/easy_tdx（固定提交 e374a0da2834119ac695c1083805d1b0a60967c2）
的 ``mac/adjust.py``，去除 pandas/numpy 依赖，改为纯 list[dict] 输入输出，
语义逐项对齐参考实现：

公式（锚定最新）::

    复权价 = (原价 - 每股分红 + 每股配股价 × 每股配股比例) /
             (1 + 每股送转股比例 + 每股配股比例)

以除权日**前一交易日**的未复权收盘价（含权价 P_cum）为基准，前复权因子::

    f = (P_cum - fenhong + peigujia × peigu) / (P_cum × (1 + songzhuangu + peigu))

该因子乘到「除权日前一交易日及之前」的所有 OHLC；最新价不动。
fenhong/songzhuangu/peigu 为每股单位（协议解码层已归一化），peigujia 为元/股。

边界（按计划显式处理）：
- cum_close 缺失或 <= 0 → 事件非法（缺前收盘/非法价），跳过并上报
- 分母为 0、结果非有限 → 事件非法，跳过并上报
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime

#: 前复权同比缩放的字段（vol/amount 保持原值）。
OHLC_FIELDS = ("open", "high", "low", "close")


@dataclass(frozen=True)
class AdjustResult:
    """前复权应用结果。

    Attributes:
        bars: 调整后的 bar 列表（新对象；vol/amount 保持原值）。
        skipped_event_dates: 因非法而被跳过的事件日期（升序去重）。
    """

    bars: list[dict]
    skipped_event_dates: list[date] = field(default_factory=list)


def compute_forward_factor(
    cum_close: float,
    fenhong: float,
    peigujia: float,
    songzhuangu: float,
    peigu: float,
) -> float | None:
    """单次除权除息事件的前复权乘子；非法输入返回 None。"""
    if not math.isfinite(cum_close) or cum_close <= 0:
        return None
    denom = cum_close * (1.0 + songzhuangu + peigu)
    if denom == 0:
        return None
    factor = (cum_close - fenhong + peigujia * peigu) / denom
    if not math.isfinite(factor):
        return None
    return factor


def _as_date(value: object) -> date | None:
    """bar/事件日期归一化为 date。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def to_float(value: object) -> float | None:
    """安全转 float；None/NaN/inf 返回 None。"""
    if value is None:
        return None
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def has_bad_prices(bars: list[dict]) -> bool:
    """检测 QFQ 结果是否含非法价格（OHLC 任一字段 <=0 或非有限值）。

    对应参考实现 ``has_bad_prices``（服务端 QFQ 对深度历史可能返回负价）。
    """
    for bar in bars:
        for f in OHLC_FIELDS:
            v = to_float(bar.get(f))
            if v is None or v <= 0:
                return True
    return False


def extract_dividend_events(records: list[dict]) -> list[dict]:
    """从 XDXR 记录中提取 category==1 除权除息事件（按日期升序）。

    事件字段：date/fenhong/peigujia/songzhuangu/peigu（每股口径）。
    四个数值字段全缺失或日期不可解析的事件跳过；单字段缺失按 0 处理。
    """
    events: list[dict] = []
    for rec in records:
        if rec.get("category") != 1:
            continue
        event_date = _as_date(rec.get("date"))
        if event_date is None:
            continue
        fh = to_float(rec.get("fenhong"))
        pjk = to_float(rec.get("peigujia"))
        sz = to_float(rec.get("songzhuangu"))
        pg = to_float(rec.get("peigu"))
        if fh is None and pjk is None and sz is None and pg is None:
            continue
        events.append(
            {
                "date": event_date,
                "fenhong": fh if fh is not None else 0.0,
                "peigujia": pjk if pjk is not None else 0.0,
                "songzhuangu": sz if sz is not None else 0.0,
                "peigu": pg if pg is not None else 0.0,
            }
        )
    events.sort(key=lambda e: e["date"])
    return events


def build_factor_chain(
    daily_bars: list[dict],
    events: list[dict],
) -> tuple[list[tuple[date, float]], list[date]]:
    """从原始日线收盘构建每个事件的因子链。

    Args:
        daily_bars: 含 datetime/close 的原始日线（顺序不限，须覆盖到最新锚点）。
        events: ``extract_dividend_events`` 输出（升序）。

    Returns:
        (chain, skipped)：chain 为 ``[(event_date, factor)]``（升序，仅合法事件），
        skipped 为因子非法的事件日期。因子始终由**原始**含权收盘计算
        （与参考实现一致：事件之间互不影响基准）。

    位置约定：除权日前一交易日的原始收盘为含权基准；若全部 bar 早于除权日
    （事件晚于请求末日，锚定最新），以最后一根 bar 为基准。
    """
    dated = [(_as_date(bar.get("datetime")), to_float(bar.get("close"))) for bar in daily_bars]
    # 日期不可解析的 bar 无法定位事件边界，仅丢弃日期；缺失收盘的 bar
    # 必须保留在序列中，否则事件基准会静默错位。
    dated = [(d, c) for d, c in dated if d is not None]
    dated.sort(key=lambda pair: pair[0])
    dates = [d for d, _ in dated]
    closes = [c for _, c in dated]

    chain: list[tuple[date, float]] = []
    skipped: list[date] = []
    for event in events:
        event_date: date = event["date"]
        # 第一个 >= 除权日 的位置；其前一根为含权收盘。默认全部 bar 早于
        # 除权日（事件晚于请求末日）：用最后一根 bar。
        cum_pos = len(dates) - 1
        for pos, bar_date in enumerate(dates):
            if bar_date >= event_date:
                cum_pos = pos - 1
                break
        if cum_pos < 0:
            # 全部 bar 晚于等于除权日：事件早于区间，不影响区间。
            continue
        cum_close = closes[cum_pos]
        factor = (
            compute_forward_factor(
                cum_close,
                event["fenhong"],
                event["peigujia"],
                event["songzhuangu"],
                event["peigu"],
            )
            if cum_close is not None
            else None  # 缺前收盘：显式上报，禁默默错位
        )
        if factor is None:
            skipped.append(event_date)
            continue
        chain.append((event_date, factor))
    return chain, skipped


def apply_factor_chain(bars: list[dict], chain: list[tuple[date, float]]) -> list[dict]:
    """对 bars（任意顺序、任意周期）应用因子链。

    bar 日期严格早于某事件日期时，该 bar 的 OHLC 乘以该事件因子（多事件连乘）。
    vol/amount 保持原值。返回新的 bar 列表。
    """
    if not chain:
        return [dict(bar) for bar in bars]
    out: list[dict] = []
    for bar in bars:
        bar_date = _as_date(bar.get("datetime"))
        new_bar = dict(bar)
        if bar_date is not None:
            product = 1.0
            for event_date, factor in chain:
                if bar_date < event_date:
                    product *= factor
            if product != 1.0:
                for f in OHLC_FIELDS:
                    v = to_float(new_bar.get(f))
                    if v is not None:
                        new_bar[f] = v * product
        out.append(new_bar)
    return out


def apply_forward_adjust(bars: list[dict], events: list[dict]) -> AdjustResult:
    """对未复权 K 线应用前复权（chain 组合入口）。

    bars 需含 ``datetime``（date/datetime/ISO 字符串）与 OHLC 字段，须覆盖到
    最新锚点（事件晚于末日时以最后一根 bar 为含权基准）。返回
    ``AdjustResult``；因子非法且影响区间的事件日期在 ``skipped_event_dates``
    上报，调用方可据此判 ``adjustment_unavailable``。
    """
    if not bars:
        return AdjustResult(bars=[])
    if not events:
        return AdjustResult(bars=[dict(bar) for bar in bars])
    chain, skipped = build_factor_chain(bars, events)
    adjusted = apply_factor_chain(bars, chain)
    return AdjustResult(bars=adjusted, skipped_event_dates=skipped)
