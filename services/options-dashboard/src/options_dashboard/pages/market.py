"""Option chain + multi-leg strategy page.

Layout:
  [标的 | 拉取 | 到期日 | ATM± | 全部 | 侧]   ← control bar
  [期权链表格 — 每行“+”按钮添加策略腿]
  [估值参数: 标的价格 利率 股息 估值日期 — 每项独立恢复]
  [策略组合卡片 — 可编辑方向/张数/建仓价/IV，显示双模型估值]

No separate calculator: contract params come from the chain row the user
selects; pricing context (spot/r/q) is shared across legs; IV is per-leg.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .. import data
from ..market_inputs import (
    dividend_yield_from_profile,
    infer_style,
    interpolate_rate,
)
from ..state import STRATEGY_LEGS_KEY, SYMBOL_KEY, get_strategy_legs
from ..strategy import (
    Leg,
    PricingContext,
    current_payoff_curve,
    effective_leverage,
    value_leg,
    value_strategy,
)
from .earnings import render_earnings_crush_scenario

_CHAIN_TTL_SECONDS = 60.0
_PROFILE_TTL_SECONDS = 3600.0
_QUOTE_TTL_SECONDS = 10.0
_DEFAULT_STRIKE_WINDOW = 10


@st.cache_data(ttl=_CHAIN_TTL_SECONDS, show_spinner="拉取期权链…")
def _load_chain(symbol: str) -> list[dict[str, Any]]:
    return data.fetch_option_chain_sync(symbol)


@st.cache_data(ttl=_PROFILE_TTL_SECONDS, show_spinner="拉取标的概况…")
def _load_profile(symbol: str) -> dict[str, Any]:
    try:
        return data.fetch_profile_sync(symbol)
    except data.DataUnavailableError:
        return {}


@st.cache_data(ttl=_PROFILE_TTL_SECONDS, show_spinner="拉取国债利率…")
def _load_treasury(limit: int = 10) -> list[dict[str, Any]]:
    try:
        return data.fetch_treasury_rates_sync(limit=limit)
    except data.DataUnavailableError:
        return []


@st.cache_data(ttl=_QUOTE_TTL_SECONDS, show_spinner=False)
def _load_quote(symbol: str) -> dict[str, Any]:
    """实时报价短 TTL 缓存：页面重渲染不打上游，重置按钮仍绕过缓存取最新。"""
    try:
        return data.fetch_equity_quote_sync(symbol)
    except (data.DataUnavailableError, data.RateLimitedError):
        return {}


# --------------------------------------------------------------------------- #
# Contract symbol formatting: O:AAPL260918C00100000 -> AAPL 260918 100C
# --------------------------------------------------------------------------- #

_OCC_RE = re.compile(r"^O:([A-Z]+)(\d{6})([CP])\d+$")


def fmt_contract(occ: str) -> str:
    m = _OCC_RE.match(occ or "")
    if not m:
        return occ or ""
    underlying, yymmdd, cp = m.group(1), m.group(2), m.group(3)
    tail = (occ or "").split(cp)[-1]
    try:
        strike = int(tail) / 1000.0
        strike_str = f"{strike:g}"
    except (ValueError, TypeError):
        strike_str = "?"
    side = "C" if cp == "C" else "P"
    return f"{underlying} {yymmdd} {strike_str}{side}"


def fmt_leg_label(leg: dict[str, Any]) -> str:
    if leg.get("kind") == "stock":
        return leg.get("kind_symbol", "")
    return fmt_contract(leg.get("kind_symbol", ""))


def _days_to_expiry(expiration_str: str, *, now: date | None = None) -> int | None:
    """Calendar days from *now* (default today) to expiration; None if unparseable."""
    try:
        exp = date.fromisoformat(str(expiration_str)[:10])
    except (ValueError, TypeError):
        return None
    ref = now or date.today()
    return max((exp - ref).days, 0)


# --------------------------------------------------------------------------- #
# Main render
# --------------------------------------------------------------------------- #


def render_chain_strategy() -> None:
    st.title("期权策略")
    st.caption("当前 Research Plan 不提供实时 NBBO bid/ask；价格与风险指标来自 ConvexValue 估值快照。")

    symbol = st.session_state.get(SYMBOL_KEY, "").strip().upper()
    if not symbol:
        chain_col, calculator_col = st.columns(
            [1, 1.35],
            gap="medium",
            vertical_alignment="top",
        )
        with chain_col:
            st.markdown("#### 期权链")
            symbol_col, query_col = st.columns([3, 1], gap="small")
            typed = symbol_col.text_input(
                "标的",
                placeholder="AAPL / SPY",
                key="symbol_text_input",
                label_visibility="collapsed",
            )
            if query_col.button("查询", type="primary", width="stretch") and typed.strip():
                st.session_state[SYMBOL_KEY] = typed.strip().upper()
                st.rerun()
            st.info("输入标的后查询期权链。")
        with calculator_col:
            st.subheader("价格计算器")
            st.info("查询期权链后，可编辑估值参数并构建策略组合。")
        return

    try:
        records = _load_chain(symbol)
    except data.RateLimitedError as exc:
        st.error(f"上游限频（429）中，稍后重试：{exc}")
        stats = data.throttle.stats()
        st.caption(f"冷却剩余 {stats['cooldown_remaining']:.1f}s；累计失败 {stats['failure_count']} 次。")
        return
    except data.DataUnavailableError as exc:
        st.error(f"暂无数据：{exc}")
        return

    # --- Market context defaults from data sources ---
    chain_spot = float(records[0].get("underlying_price") or 0.0) if records else 0.0
    profile = _load_profile(symbol)
    default_spot = chain_spot
    quote = _load_quote(symbol)
    lp = quote.get("last_price")
    if lp:
        default_spot = float(lp)
    if default_spot <= 0:
        default_spot = float(profile.get("price") or 0.0)

    default_q, dividend_note = dividend_yield_from_profile(profile, spot=default_spot)
    treasury = _load_treasury()
    default_r, _ = interpolate_rate(treasury, tenor_years=30 / 365)
    style = infer_style(symbol)

    prev_symbol = st.session_state.get("_ctx_symbol")
    if prev_symbol != symbol:
        st.session_state["_ctx_symbol"] = symbol
        st.session_state["_ctx_defaults"] = {
            "spot": default_spot,
            "r": default_r,
            "q": default_q,
        }
    defaults = st.session_state.get("_ctx_defaults", {"spot": default_spot, "r": default_r, "q": default_q})

    df = pd.DataFrame(records)
    if df.empty:
        st.warning("期权链为空。")
        return

    # Streamlit stacks columns on narrow screens. This keeps the chain compact
    # beside the calculator on desktop without introducing horizontal scrolling.
    chain_col, calculator_col = st.columns(
        [1, 1.35],
        gap="medium",
        vertical_alignment="top",
    )
    with chain_col:
        _render_chain(df, symbol, defaults["spot"], style)
    with calculator_col:
        st.subheader("价格计算器")
        st.caption("调整估值参数、组合腿与财报情景，查看策略模型价格和风险变化。")
        spot, r, q, val_now = _render_market_params(symbol, defaults, dividend_note)
        _render_strategy(symbol, spot, r, q, style, val_now)

    # --- 5-second auto-refresh fragment ---
    _render_auto_refresh(symbol)


# --------------------------------------------------------------------------- #
# 5-second auto-refresh fragment
# --------------------------------------------------------------------------- #


@st.fragment(run_every=5.0)
def _render_auto_refresh(symbol: str) -> None:
    """Refresh ConvexValue valuations (CV 估值) on a 5-second timer.

    Pulls a fresh chain snapshot, updates each strategy leg's ``fmv`` from the
    latest chain record, and reruns the page so the strategy table shows the
    refreshed CV 估值. User-set values (direction/张数/建仓价/IV) are left intact.
    Rerun only when something actually changed; otherwise the fragment is a
    no-op, which also keeps AppTest deterministic.
    """
    _load_chain.clear()
    try:
        records = _load_chain(symbol)
    except data.RateLimitedError as exc:
        st.toast(f"CV 估值刷新被限频：{exc}", icon="⏳")
        return
    except data.DataUnavailableError as exc:
        st.toast(f"CV 估值刷新无数据：{exc}", icon="⚠️")
        return
    except Exception as exc:  # noqa: BLE001 - keep the auto-refresh timer alive
        # Unexpected upstream error (timeout / decode / connection). Without
        # this guard the fragment raises and its run_every timer stops until a
        # full page rerun; surface it and skip this tick instead.
        st.toast(f"CV 估值刷新出错：{exc}", icon="⚠️")
        return
    if _refresh_leg_fmvs(records):
        st.rerun()


def _refresh_leg_fmvs(records: list[dict[str, Any]]) -> bool:
    """Update each strategy option leg's ``fmv`` from the latest chain records.

    Returns True if any leg was updated.
    """
    legs = get_strategy_legs()
    if not legs:
        return False
    by_symbol = {str(r.get("contract_symbol")): r for r in records}
    changed = False
    for leg in legs:
        if leg.get("kind") != "option":
            continue
        row = by_symbol.get(leg.get("kind_symbol", ""))
        if not row:
            continue
        # CV returns float | None here, but guard against malformed upstream
        # payloads so a single bad row never crashes the auto-refresh loop.
        try:
            new_fmv = float(row.get("theoretical_price") or 0.0)
            cur_fmv = float(leg.get("fmv") or 0.0)
        except (TypeError, ValueError):
            continue
        if abs(new_fmv - cur_fmv) > 1e-9:
            # Match the codebase convention (fmv > 0 == "has valuation"):
            # a CV drop to 0/None clears a stale positive FMV to None so the
            # strategy table shows "—" instead of a stale price.
            leg["fmv"] = new_fmv if new_fmv > 0 else None
            changed = True
    if changed:
        st.session_state[STRATEGY_LEGS_KEY] = legs
    return changed


# --------------------------------------------------------------------------- #
# Chain — control bar + table; selecting a row auto-adds the leg
# --------------------------------------------------------------------------- #


def _render_chain(df: pd.DataFrame, symbol: str, spot: float, style: str) -> None:
    st.markdown("#### 期权链")

    symbol_col, fetch_col = st.columns([3, 1], gap="small")
    typed = symbol_col.text_input(
        "标的",
        value=symbol,
        key="symbol_text_input",
        label_visibility="collapsed",
        placeholder="AAPL / SPY",
    )
    if fetch_col.button("查询", type="primary", width="stretch"):
        new_sym = (typed or "").strip().upper()
        if new_sym and new_sym != symbol:
            st.session_state[SYMBOL_KEY] = new_sym
            st.rerun()

    expirations = sorted(df["expiration"].astype(str).unique())
    filters = st.columns([2.2, 1, 1, 0.8], gap="small")
    sel_exp = filters[0].selectbox(
        "到期日",
        options=expirations,
        key="chain_expiry_sel",
        label_visibility="collapsed",
    )
    side_filter = filters[1].selectbox(
        "侧",
        options=["全部", "call", "put"],
        key="chain_side_filter",
        format_func={"全部": "全部", "call": "C", "put": "P"}.__getitem__,
        label_visibility="collapsed",
    )
    window = int(
        filters[2].number_input(
            "ATM 窗口",
            min_value=1,
            value=_DEFAULT_STRIKE_WINDOW,
            step=1,
            key="chain_strike_window",
            label_visibility="collapsed",
            help="显示 ATM 附近的行权价数量。",
        )
    )
    show_all = filters[3].checkbox(
        "全",
        value=False,
        key="chain_show_all",
        help="显示所有行权价。",
    )

    exp_view = df[df["expiration"].astype(str) == sel_exp]
    view = exp_view.copy()
    if side_filter != "全部":
        view = view[view["option_type"] == side_filter]
    strikes = sorted(view["strike"].astype(float).unique())
    if not show_all and spot > 0 and strikes:
        atm = min(strikes, key=lambda s: abs(s - spot))
        view = view[(view["strike"].astype(float) >= atm - window) & (view["strike"].astype(float) <= atm + window)]
    if view.empty:
        st.warning("该筛选下无合约。")
        return

    st.caption("按 + 添加策略腿 · 当前到期日：" + sel_exp)

    def _num(row, col, spec):
        v = row.get(col)
        if v is None or v == "" or (isinstance(v, float) and pd.isna(v)):
            return "—"
        try:
            return format(float(v), spec)
        except (TypeError, ValueError):
            return "—"

    def _int(row, col):
        v = row.get(col)
        if v is None or v == "":
            return "—"
        try:
            n = float(v)
            return f"{n / 1000:.1f}k" if n >= 1000 else f"{int(n)}"
        except (TypeError, ValueError):
            return "—"

    # Keep the chain independently scrollable. Contract code is deliberately
    # omitted here; the selected expiration is shown above and full codes stay
    # visible in the strategy panel after a leg is added.
    column_widths = [0.85, 0.45, 0.75, 0.55, 0.75, 0.6, 0.55]
    with st.container(height=560, border=True):
        hdr = st.columns(column_widths, gap="small", vertical_alignment="center")
        for col, label in zip(hdr, ["K", "C/P", "IV", "Δ", "FMV", "OI", ""]):
            col.caption(label)

        for _, row in view.iterrows():
            rc = st.columns(column_widths, gap="small", vertical_alignment="center")
            contract = str(row["contract_symbol"])
            rc[0].markdown(f"**{_num(row, 'strike', '.2f')}**")
            rc[1].markdown("C" if row["option_type"] == "call" else "P")
            rc[2].markdown(_num(row, "implied_volatility", ".3f"))
            rc[3].markdown(_num(row, "delta", ".2f"))
            rc[4].markdown(_num(row, "theoretical_price", ".2f"))
            rc[5].markdown(_int(row, "open_interest"))
            if rc[6].button(
                "+",
                key=f"add_{contract}",
                use_container_width=True,
                help=f"加入 {fmt_contract(contract)}",
            ):
                picked = {
                    "symbol": contract,
                    "strike": float(row["strike"]),
                    "expiration": str(row["expiration"]),
                    "side": str(row["option_type"]),
                    "iv": float(row.get("implied_volatility") or 0),
                    "fmv": float(row.get("theoretical_price") or 0),
                }
                _auto_add_leg(picked, style)


def _auto_add_leg(picked: dict[str, Any], style: str) -> None:
    """Add a leg for the picked contract if not already present.

    Uses the picked IV and FMV as the leg's IV and cost defaults. Dedup by
    contract symbol so re-selecting the same row doesn't pile up duplicates.
    """
    legs = get_strategy_legs()
    contract = picked["symbol"]
    if any(leg.get("kind_symbol") == contract for leg in legs):
        return
    legs.append(
        {
            "kind": "option",
            "direction": "buy",
            "quantity": 1.0,
            "kind_symbol": contract,
            "underlying": _underlying_from_occ(contract),
            "strike": picked["strike"],
            "expiration": picked["expiration"],
            "option_side": picked["side"],
            "style": style,
            "iv": picked["iv"] if picked["iv"] > 0 else None,
            "iv_default": picked["iv"] if picked["iv"] > 0 else None,
            "cost": picked["fmv"] if picked["fmv"] > 0 else None,
            "cost_default": picked["fmv"] if picked["fmv"] > 0 else None,
            "fmv": picked["fmv"] if picked["fmv"] > 0 else None,
        }
    )
    st.session_state[STRATEGY_LEGS_KEY] = legs
    st.toast(f"已加入 {fmt_contract(contract)}", icon="✅")
    st.rerun()


def _underlying_from_occ(occ: str) -> str:
    m = _OCC_RE.match(occ)
    return m.group(1) if m else ""


# --------------------------------------------------------------------------- #
# Market parameters (spot/r/q) — each with independent reset
# --------------------------------------------------------------------------- #


def _reset_spot_to_latest(symbol: str) -> None:
    """Refresh the spot input from the quote source before the next render."""
    try:
        quote = data.fetch_equity_quote_sync(symbol)
        latest = float(quote.get("last_price") or 0.0)
        if latest <= 0:
            raise ValueError("报价为空")
    except (data.DataUnavailableError, data.RateLimitedError, TypeError, ValueError) as exc:
        st.session_state["_ctx_spot_reset_error"] = f"未能获取 {symbol} 的最新价格：{exc}"
        return

    st.session_state["ctx_spot"] = latest
    st.session_state.pop("_ctx_spot_reset_error", None)


def _render_market_params(
    symbol: str,
    defaults: dict[str, float],
    dividend_note: str,
) -> tuple[float, float, float, datetime]:
    """Render spot/r/q inputs + a valuation-time input (defaults to now).

    Returns (spot, r, q, val_now). val_now lets the strategy section compute
    each leg's remaining days from the leg's own expiration date.
    """
    st.markdown("#### 估值参数")
    st.caption("可覆盖市场快照，用于重算每腿模型价格和策略损益。")
    if dividend_note:
        st.caption(dividend_note)

    first_row = st.columns([3, 1, 3, 1], gap="small", vertical_alignment="bottom")
    # widget 默认值只在首次渲染时写入 session_state，重置回调随后覆盖；
    # 同时传 value= 和 key= 且 key 已存在会触发 Streamlit widget 警告。
    st.session_state.setdefault(
        "ctx_spot",
        float(defaults["spot"]) if defaults["spot"] > 0 else 0.0,
    )
    st.session_state.setdefault("ctx_r", float(defaults["r"]))
    st.session_state.setdefault("ctx_q", float(defaults["q"]))
    st.session_state.setdefault("ctx_val_date", date.today())
    spot = first_row[0].number_input(
        "标的价格",
        min_value=0.0,
        step=0.5,
        format="%.2f",
        key="ctx_spot",
    )
    first_row[1].button(
        "重置",
        key="ctx_reset_spot",
        width="stretch",
        help="从报价源查询最新标的价格。",
        on_click=_reset_spot_to_latest,
        args=(symbol,),
    )
    r = first_row[2].number_input(
        "无风险利率",
        min_value=0.0,
        step=0.005,
        format="%.4f",
        key="ctx_r",
        help="使用小数输入，例如 0.04 表示 4%。",
    )
    first_row[3].button(
        "重置",
        key="ctx_reset_r",
        width="stretch",
        on_click=lambda: st.session_state.update(ctx_r=float(defaults["r"])),
    )

    second_row = st.columns([3, 1, 3, 1], gap="small", vertical_alignment="bottom")
    q = second_row[0].number_input(
        "股息率",
        min_value=0.0,
        step=0.005,
        format="%.4f",
        key="ctx_q",
        help="使用连续股息率小数，例如 0.01 表示 1%。",
    )
    second_row[1].button(
        "重置",
        key="ctx_reset_q",
        width="stretch",
        on_click=lambda: st.session_state.update(ctx_q=float(defaults["q"])),
    )
    val_date = second_row[2].date_input(
        "估值日期",
        key="ctx_val_date",
    )
    second_row[3].button(
        "重置",
        key="ctx_reset_date",
        width="stretch",
        on_click=lambda: st.session_state.update(ctx_val_date=date.today()),
    )

    if reset_error := st.session_state.pop("_ctx_spot_reset_error", None):
        st.warning(reset_error)

    from zoneinfo import ZoneInfo

    val_now = datetime.combine(
        val_date,
        datetime.min.time(),
        tzinfo=ZoneInfo("America/New_York"),
    )
    return spot, r, q, val_now


# --------------------------------------------------------------------------- #
# Strategy — editable table with per-leg IV/cost/qty, net Greeks, payoff
# --------------------------------------------------------------------------- #


def _render_strategy(
    symbol: str,
    spot: float,
    r: float,
    q: float,
    style: str,
    val_now: datetime,
) -> None:
    st.divider()
    legs_state = get_strategy_legs()

    title_col, action_col = st.columns([5, 1], vertical_alignment="center")
    title_col.subheader("策略组合")
    title_col.caption("编辑每腿方向、张数、建仓价和 IV；价格列会随估值参数更新。")
    if legs_state and action_col.button(
        "清空策略",
        key="summary_clear",
        width="stretch",
        help="删除当前策略中的全部腿",
    ):
        st.session_state[STRATEGY_LEGS_KEY] = []
        st.rerun()

    if not legs_state:
        st.info("点击期权链右侧的“+”添加策略腿。")
        return

    column_widths = [2.2, 0.9, 0.65, 0.9, 0.8, 0.6, 0.8, 0.8, 0.45]
    headers = ["合约", "方向", "张数", "建仓价", "IV", "DTE", "CV 估值", "模型价", ""]
    hdr = st.columns(column_widths, gap="small", vertical_alignment="center")
    for col, label in zip(hdr, headers):
        col.caption(label)

    net_fmv = 0.0
    net_theo = 0.0
    direction_labels = {"buy": "买入", "sell": "卖出"}
    for i, leg in enumerate(legs_state):
        with st.container(border=True):
            rc = st.columns(
                column_widths,
                gap="small",
                vertical_alignment="center",
            )
            rc[0].markdown(f"**{fmt_leg_label(leg)}**")
            leg["direction"] = rc[1].selectbox(
                "方向",
                options=["buy", "sell"],
                index=0 if leg.get("direction", "buy") == "buy" else 1,
                format_func=direction_labels.__getitem__,
                key=f"leg_dir_{i}",
                label_visibility="collapsed",
            )
            leg["quantity"] = float(
                rc[2].number_input(
                    "张数",
                    min_value=1,
                    value=int(leg.get("quantity", 1)),
                    step=1,
                    key=f"leg_qty_{i}",
                    label_visibility="collapsed",
                )
            )
            leg["cost"] = rc[3].number_input(
                "建仓价",
                min_value=0.0,
                value=float(leg.get("cost") or leg.get("cost_default") or 0.0),
                step=0.5,
                format="%.2f",
                key=f"leg_cost_{i}",
                label_visibility="collapsed",
                help="每股建仓价格，用于计算策略损益。",
            )
            leg["iv"] = rc[4].number_input(
                "IV",
                min_value=0.0,
                value=float(leg.get("iv") or leg.get("iv_default") or 0.0),
                step=0.01,
                format="%.3f",
                key=f"leg_iv_{i}",
                label_visibility="collapsed",
            )
            days = _days_to_expiry(leg.get("expiration", ""), now=val_now.date())
            rc[5].markdown(f"**{days}**" if days is not None else "—")

            fmv = float(leg.get("fmv") or 0.0)
            rc[6].markdown(f"**{fmv:.2f}**" if fmv > 0 else "—")

            leg_obj = _dict_to_leg(leg)
            iv_val = float(leg["iv"]) if leg.get("iv") else None
            lv = value_leg(
                leg_obj,
                PricingContext(spot=spot, r=r, q=q, default_iv=None, now=val_now),
                scenario_iv=iv_val,
            )
            rc[7].markdown(f"**{lv.price:.2f}**" if lv.price > 0 else "—")

            signed = leg_obj.signed_quantity()
            net_fmv += fmv * signed if fmv > 0 else 0.0
            net_theo += lv.price * signed

            if rc[8].button(
                "×",
                key=f"rm_leg_{i}",
                width="stretch",
                help=f"删除 {fmt_leg_label(leg)}",
            ):
                legs_state.pop(i)
                st.session_state[STRATEGY_LEGS_KEY] = legs_state
                st.rerun()

    st.session_state[STRATEGY_LEGS_KEY] = legs_state

    st.caption("建仓价用于损益计算；CV 估值来自 ConvexValue，模型价来自本地 CRR/BSM。")

    # Net valuation.
    legs = [_dict_to_leg(d) for d in legs_state]
    iv_overrides = {d["kind_symbol"]: float(d["iv"]) for d in legs_state if d.get("kind") == "option" and d.get("iv")}
    ctx = PricingContext(spot=spot, r=r, q=q, default_iv=None, now=val_now)
    valuation = value_strategy(legs, ctx, iv_overrides=iv_overrides)

    st.markdown("#### 组合估值")
    lev = effective_leverage(valuation, spot=spot)
    m1, m2, m3 = st.columns(3, gap="small")
    m1.metric("组合模型价", f"{net_theo:+.2f}")
    m2.metric("组合 CV 估值", f"{net_fmv:+.2f}")
    m3.metric(
        "有效杠杆",
        f"{lev:+.2f}×" if lev is not None else "—",
        help="标的价格每变动 1%，组合模型价变动约 lev%。零成本组合（如平值 Iron Condor）该值不定义。",
    )

    st.caption("组合 Greeks（按方向与张数汇总）")
    greek_labels = {
        "delta": "Δ",
        "gamma": "Γ",
        "theta": "Θ",
        "vega": "Vega",
        "rho": "Rho",
    }
    greek_cols = st.columns(len(greek_labels), gap="small")
    for col, (greek, label) in zip(greek_cols, greek_labels.items()):
        col.metric(label, f"{valuation.net_greeks[greek]:+.3f}")

    _render_payoff_chart(legs, spot, r, q, val_now, iv_overrides)
    render_earnings_crush_scenario(symbol, legs, ctx, iv_overrides)


def _render_payoff_chart(
    legs: list[Leg],
    spot: float,
    r: float,
    q: float,
    val_now: datetime,
    iv_overrides: dict[str, float],
) -> None:
    """Interactive payoff chart with unified price/PnL hover details."""
    st.markdown("#### 策略盈亏")
    st.caption("悬停查看同一标的价格下的当前损益与到期损益。")
    ctx = PricingContext(spot=spot, r=r, q=q, default_iv=None, now=val_now)
    try:
        curves = current_payoff_curve(legs, ctx=ctx, iv_overrides=iv_overrides)
    except Exception as exc:
        st.caption(f"无法计算盈亏曲线：{exc}")
        return

    fig = go.Figure()
    # Expiry payoff (solid line).
    fig.add_trace(
        go.Scatter(
            x=curves.xs,
            y=curves.expiry_points,
            mode="lines",
            name="到期损益",
            line={"color": "#2196F3", "width": 2},
            hovertemplate="到期损益 %{y:+.2f}<extra></extra>",
        )
    )
    # Current payoff (dashed line).
    fig.add_trace(
        go.Scatter(
            x=curves.xs,
            y=curves.current_points,
            mode="lines",
            name="当前损益",
            line={"color": "#FF9800", "width": 2, "dash": "dash"},
            hovertemplate="当前损益 %{y:+.2f}<extra></extra>",
        )
    )
    # Zero line.
    fig.add_hline(y=0, line_dash="solid", line_color="gray", line_width=1)
    # Current spot marker.
    if spot > 0:
        fig.add_vline(
            x=spot,
            line_dash="dot",
            line_color="green",
            line_width=2,
            annotation_text=f"现价 {spot:.2f}",
            annotation_position="top",
        )
    # Breakeven markers: find zero-crossings on the expiry curve.
    be_list: list[float] = []
    exp = curves.expiry_points
    xs = curves.xs
    for i in range(len(exp) - 1):
        if (exp[i] < 0) != (exp[i + 1] < 0):
            frac = -exp[i] / (exp[i + 1] - exp[i]) if exp[i + 1] != exp[i] else 0
            be_list.append(xs[i] + frac * (xs[i + 1] - xs[i]))
    for be in be_list:
        fig.add_vline(
            x=be,
            line_dash="dash",
            line_color="red",
            line_width=1,
            annotation_text=f"平衡 {be:.2f}",
            annotation_position="bottom",
        )

    fig.update_layout(
        xaxis_title="标的价格",
        yaxis_title="损益",
        height=400,
        margin={"l": 50, "r": 20, "t": 20, "b": 40},
        legend={"orientation": "h", "y": 1.12},
        hovermode="x unified",
    )
    fig.update_xaxes(
        hoverformat=".2f",
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikethickness=1,
        zeroline=True,
        zerolinewidth=1,
        zerolinecolor="lightgray",
    )

    st.plotly_chart(
        fig,
        width="stretch",
        config={"displaylogo": False, "scrollZoom": True},
    )

    if be_list:
        be_str = ", ".join(f"{b:.2f}" for b in be_list)
        st.caption(f"到期盈亏平衡点：{be_str}")


def _dict_to_leg(d: dict[str, Any]) -> Leg:
    exp = d.get("expiration")
    return Leg(
        kind=d["kind"],
        direction=d["direction"],
        quantity=float(d["quantity"]),
        kind_symbol=d["kind_symbol"],
        strike=float(d["strike"]) if d.get("strike") is not None else None,
        expiration=date.fromisoformat(str(exp)) if exp else None,
        option_side=d.get("option_side"),
        style=d.get("style", "american"),
        cost=d.get("cost"),
    )
