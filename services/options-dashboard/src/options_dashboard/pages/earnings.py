"""Earnings IV Crush scenario support for the strategy calculator."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import streamlit as st

from .. import analytics, data
from ..market_inputs import dividend_yield_from_profile, infer_style, interpolate_rate
from ..strategy import Leg, PricingContext, value_strategy


def _analyze_history(
    symbol: str,
    events_count: int,
    progress: st.delta_generator.DeltaGenerator,
) -> tuple[list[analytics.EarningsCrushSample], list[date]]:
    """Fetch historical crush samples and future earnings dates for one symbol."""
    earnings_rows = data.fetch_earnings_sync(symbol, limit=events_count)
    events = analytics.parse_earnings_rows(earnings_rows)
    today = date.today()
    past_events = [event for event in events if event.date < today]
    future_dates = sorted({event.date for event in events if event.date >= today})
    if not past_events:
        return [], future_dates

    try:
        profile = data.fetch_profile_sync(symbol)
    except (data.DataUnavailableError, data.RateLimitedError):
        profile = {}

    spot = float(profile.get("price", 0.0)) if profile else 0.0
    q, _ = dividend_yield_from_profile(profile, spot=spot)
    style = infer_style(symbol)
    samples: list[analytics.EarningsCrushSample] = []
    for i, event in enumerate(past_events):
        progress.progress(
            (i + 1) / len(past_events),
            text=f"分析 {event.date} 财报（{i + 1}/{len(past_events)}）…",
        )
        sample = _analyze_event(symbol, event, style, q, spot)
        if sample is not None:
            samples.append(sample)
    return samples, future_dates


def value_earnings_crush_scenario(
    legs: list[Leg],
    ctx: PricingContext,
    iv_overrides: dict[str, float],
    *,
    event_date: date,
    gap_pct: float,
    crush_pct: float,
):
    """Value a strategy before and after a hypothetical earnings event.

    The post-event valuation uses the caller's valuation date, which must fall
    after the event. The pre-event baseline is the calendar day before it.
    """
    if ctx.now is None or ctx.now.date() <= event_date:
        raise ValueError("估值日期必须晚于财报日")

    before_now = datetime.combine(
        event_date - timedelta(days=1),
        datetime.min.time(),
        tzinfo=ctx.now.tzinfo,
    )
    before_ctx = PricingContext(
        spot=ctx.spot,
        r=ctx.r,
        q=ctx.q,
        default_iv=None,
        now=before_now,
    )
    post_ctx = PricingContext(
        spot=ctx.spot * (1 + gap_pct),
        r=ctx.r,
        q=ctx.q,
        default_iv=None,
        now=ctx.now,
    )
    post_ivs = {
        contract: max(iv * (1 + crush_pct), 0.0001)
        for contract, iv in iv_overrides.items()
    }
    before = value_strategy(legs, before_ctx, iv_overrides=iv_overrides)
    after = value_strategy(legs, post_ctx, iv_overrides=post_ivs)
    return before, after, post_ctx.spot


def render_earnings_crush_scenario(
    symbol: str,
    legs: list[Leg],
    ctx: PricingContext,
    iv_overrides: dict[str, float],
) -> None:
    """Optionally apply historical IV-crush scenarios to the current strategy."""
    with st.expander("财报 IV Crush 情景", expanded=False):
        st.caption("先分析历史财报样本，再比较策略在财报前与财报后估值日期的模型价格。")
        controls = st.columns([1, 1], gap="small")
        events_count = controls[0].selectbox(
            "历史财报次数",
            options=[4, 8, 12],
            index=1,
            key=f"earnings_count_{symbol}",
        )
        analyze_clicked = controls[1].button(
            "分析历史样本",
            type="primary",
            width="stretch",
            key=f"earnings_analyze_{symbol}",
        )
        cache_key = f"earnings_crush_{symbol}_{events_count}"
        if analyze_clicked:
            progress = st.progress(0.0, text="拉取财报事件…")
            try:
                samples, future_dates = _analyze_history(symbol, events_count, progress)
            except (data.DataUnavailableError, data.RateLimitedError) as exc:
                st.error(f"财报获取失败：{exc}")
            else:
                st.session_state[cache_key] = (samples, future_dates)
            finally:
                progress.empty()

        cached = st.session_state.get(cache_key)
        if not cached:
            st.info("点击“分析历史样本”后生成财报 IV Crush 情景。")
            return

        samples, future_dates = cached
        if not samples:
            st.warning("没有构造出有效样本（可能缺少历史期权数据）。")
            return

        scenarios = analytics.summarize_crush(samples)
        history_cols = st.columns(3, gap="small")
        history_cols[0].metric("中位跳空", f"{scenarios.median_gap_pct:+.2%}")
        history_cols[1].metric("中位 IV Crush", f"{scenarios.median_crush_pct:+.2%}")
        history_cols[2].metric("有效样本", scenarios.sample_count)
        st.caption(scenarios.confidence_note)

        scenario_values = {
            "下分位": (scenarios.pessimistic_gap_pct, scenarios.pessimistic_crush_pct),
            "中位": (scenarios.median_gap_pct, scenarios.median_crush_pct),
            "上分位": (scenarios.optimistic_gap_pct, scenarios.optimistic_crush_pct),
        }
        scenario_col, event_col = st.columns([1, 1], gap="small")
        scenario_name = scenario_col.selectbox(
            "财报情景",
            options=list(scenario_values),
            index=1,
            key=f"earnings_scenario_{symbol}",
        )
        default_event = future_dates[0] if future_dates else ctx.now.date()
        event_date = event_col.date_input(
            "财报日",
            value=default_event,
            key=f"earnings_event_date_{symbol}",
            help="财报后估值日期须晚于此日期。",
        )
        gap_pct, crush_pct = scenario_values[scenario_name]
        try:
            before, after, post_spot = value_earnings_crush_scenario(
                legs,
                ctx,
                iv_overrides,
                event_date=event_date,
                gap_pct=gap_pct,
                crush_pct=crush_pct,
            )
        except ValueError:
            st.warning("将“估值日期”设置到财报日之后，才能计算财报后 IV Crush 情景。")
            return
        price_change = after.net_price - before.net_price

        st.caption(
            f"{scenario_name}：标的跳空 {gap_pct:+.2%} · IV 变化 {crush_pct:+.2%} · "
            f"财报后标的价格 {post_spot:.2f}"
        )
        metrics = st.columns(3, gap="small")
        metrics[0].metric("财报前组合模型价", f"{before.net_price:+.2f}")
        metrics[1].metric("财报后组合模型价", f"{after.net_price:+.2f}")
        metrics[2].metric("财报前后差额", f"{price_change:+.2f}")
        st.caption("价格为每股组合模型价；财报前基准取财报日前一日，财报后使用当前估值日期。")


def _analyze_event(symbol: str, event: analytics.EarningsEvent,
                   style: str, q: float, spot: float):
    # Pick the nearest standard monthly expiration after the event (7-45 DTE).
    expiration = analytics.nearest_option_expiration(event.date + timedelta(days=1))
    dte = (expiration - event.date).days
    if not (7 <= dte <= 45):
        return None

    # Approximate ATM strike from current spot (best-effort; historical spot
    # would be better but adds another fetch per event).
    strike = round(spot) if spot > 0 else 100.0

    # Fetch underlying closes around the event to compute gap.
    try:
        equity = data.fetch_equity_eod_sync(
            symbol,
            (event.date - timedelta(days=5)).isoformat(),
            (event.date + timedelta(days=5)).isoformat(),
        )
    except (data.DataUnavailableError, data.RateLimitedError):
        equity = []
    closes: list[tuple[date, float]] = []
    for row in equity:
        if not isinstance(row, dict):
            continue
        row_date = _parse_row_date(row.get("date"))
        close = _positive_float(row.get("close"))
        if row_date is not None and close is not None:
            closes.append((row_date, close))
    gap = analytics.underlying_gap_pct(closes, event_date=event.date)

    # Reverse-solve IV one day before and one day after the event.
    try:
        treasury = data.fetch_treasury_rates_sync(limit=5)
    except (data.DataUnavailableError, data.RateLimitedError):
        treasury = []
    r, _ = interpolate_rate(treasury, tenor_years=dte / 365)

    iv_before = _solve_iv_at(symbol, strike, "call", expiration, event.date - timedelta(days=1), style, r, q)
    iv_after = _solve_iv_at(symbol, strike, "call", expiration, event.date + timedelta(days=1), style, r, q)
    crush = (iv_after - iv_before) / iv_before if iv_before and iv_after and iv_before > 0 else None
    quality = "good" if iv_before and iv_after else "no_trade"
    return analytics.EarningsCrushSample(
        event=event, iv_before=iv_before, iv_after=iv_after,
        crush_pct=crush, underlying_gap_pct=gap, quality=quality,
    )


def _parse_row_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _positive_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _solve_iv_at(symbol: str, strike: float, side: str, expiration, as_of, style, r, q):
    contract = analytics.build_option_symbol(symbol, expiration, side, strike)
    try:
        rows = data.fetch_option_daily_sync(contract, as_of.isoformat())
    except (data.DataUnavailableError, data.RateLimitedError):
        return None
    close = float(rows.get("close") or 0)
    if close <= 0:
        return None
    # Use the event-time underlying close when available, else skip spot fetch.
    try:
        equity = data.fetch_equity_eod_sync(symbol, as_of.isoformat(), as_of.isoformat())
        first_row = equity[0] if equity else {}
        spot = _positive_float(first_row.get("close")) if isinstance(first_row, dict) else None
        spot = spot if spot is not None else 100.0
    except (data.DataUnavailableError, data.RateLimitedError):
        spot = 100.0
    if spot <= 0:
        return None
    from datetime import datetime as _dt

    from ..pricing import expiry_datetime, solve_iv, years_to_expiry
    t, _ = years_to_expiry(
        expiry_datetime(expiration.isoformat()),
        now=_dt.combine(as_of, _dt.min.time()),
    )
    if t <= 0:
        return None
    res = solve_iv(price=close, spot=spot, strike=strike, t=t, r=r, q=q, side=side, style=style)
    return res.iv if res.status == "ok" else None
