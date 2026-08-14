"""Multi-leg strategy modelling, valuation and scenario analysis.

The :class:`Leg` model is the single representation for both stock and option
legs. A :class:`Strategy` is just a list of legs plus a pricing context (spot,
risk-free rate, dividend yield, valuation time). All Greek and P&L math routes
through :mod:`options_dashboard.pricing`; this module is composition only, so
its tests stay deterministic and fast.

Multi-expiry semantics (per the approved plan): there is no single "final"
payoff when legs expire on different dates. Instead we value each leg at a
caller-chosen valuation date; legs already expired settle at intrinsic, legs
still alive are re-priced at the scenario's IV and remaining time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Sequence

from .pricing import (
    SCENARIO_CRR_STEPS,
    OptionResult,
    expiry_datetime,
    intrinsic_value,
    price_option,
    years_to_expiry,
)

AssetKind = Literal["stock", "option"]
Side = Literal["call", "put"]
Direction = Literal["buy", "sell"]
_OPTION_CONTRACT_SHARES = 100.0


@dataclass(frozen=True)
class Leg:
    """One leg of a strategy.

    For stock legs, ``strike``/``expiration``/``option_side`` are ignored and
    the leg is valued at spot. For option legs, ``strike`` and ``expiration``
    are required and ``option_side`` selects call/put.
    """

    kind: AssetKind
    direction: Direction
    quantity: float
    kind_symbol: str  # underlying ticker (e.g. AAPL) or option contract symbol
    # Option-only fields.
    strike: float | None = None
    expiration: date | None = None
    option_side: Side | None = None
    style: Literal["european", "american"] = "american"
    # User-entered fill price (per-share for options, per-share for stock).
    cost: float | None = None

    def signed_quantity(self) -> float:
        return self.quantity if self.direction == "buy" else -self.quantity


@dataclass(frozen=True)
class PricingContext:
    """Scalars shared by every leg in a strategy valuation."""

    spot: float
    r: float
    q: float
    now: datetime | None = None
    # IV override per leg (keyed by kind_symbol). When absent, the caller must
    # supply IV through the leg itself (e.g. from CV chain) via scenario.
    default_iv: float | None = None


@dataclass(frozen=True)
class LegValuation:
    symbol: str
    price: float
    greeks: dict[str, float]
    signed_qty: float
    cost: float | None
    model: str  # "bsm" | "crr" | "stock"
    warning: str | None = None


@dataclass
class StrategyValuation:
    legs: list[LegValuation]
    net_price: float  # signed: positive=credit, negative=debit
    net_greeks: dict[str, float]
    net_cost: float  # what the user paid (signed)
    unrealized: float  # mark-to-model P&L vs net_cost

    def __init__(self, legs: list[LegValuation]) -> None:
        self.legs = legs
        self.net_price = 0.0
        self.net_cost = 0.0
        self.net_greeks = {k: 0.0 for k in ("delta", "gamma", "theta", "vega", "rho")}
        for lv in legs:
            signed = lv.signed_qty
            self.net_price += lv.price * signed
            self.net_cost += (lv.cost if lv.cost is not None else lv.price) * signed
            for g, v in lv.greeks.items():
                if g in self.net_greeks:
                    self.net_greeks[g] += v * signed
        self.unrealized = self.net_price - self.net_cost


def value_leg(leg: Leg, ctx: PricingContext, *, scenario_iv: float | None = None) -> LegValuation:
    """Value a single leg under *ctx*; ``scenario_iv`` overrides per-leg IV."""
    if leg.kind == "stock":
        greeks = {"delta": 1.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
        return LegValuation(
            symbol=leg.kind_symbol,
            price=ctx.spot,
            greeks=greeks,
            signed_qty=leg.signed_quantity(),
            cost=leg.cost,
            model="stock",
        )

    if leg.strike is None or leg.expiration is None or leg.option_side is None:
        return LegValuation(
            symbol=leg.kind_symbol,
            price=0.0,
            greeks={k: 0.0 for k in ("delta", "gamma", "theta", "vega", "rho")},
            signed_qty=leg.signed_quantity(),
            cost=leg.cost,
            model="none",
            warning="期权腿缺少 strike/expiration/option_side",
        )

    iv = scenario_iv if scenario_iv is not None else ctx.default_iv
    if iv is None or iv <= 0:
        return LegValuation(
            symbol=leg.kind_symbol,
            price=intrinsic_value(ctx.spot, leg.strike, leg.option_side),
            greeks={k: 0.0 for k in ("delta", "gamma", "theta", "vega", "rho")},
            signed_qty=leg.signed_quantity(),
            cost=leg.cost,
            model="intrinsic",
            warning="缺少 IV，仅展示内在价值",
        )

    expiry_dt = expiry_datetime(leg.expiration.isoformat())
    t, intraday = years_to_expiry(expiry_dt, now=ctx.now)
    result: OptionResult = price_option(
        spot=ctx.spot,
        strike=leg.strike,
        t=t,
        iv=iv,
        r=ctx.r,
        q=ctx.q,
        side=leg.option_side,
        style=leg.style,
        steps=SCENARIO_CRR_STEPS,
    )
    warning = None
    if intraday:
        warning = "0DTE：高 Gamma、时间敏感，且当前无实时 NBBO，建议价仅供参考。"
    return LegValuation(
        symbol=leg.kind_symbol,
        price=result.price,
        greeks=result.greeks,
        signed_qty=leg.signed_quantity(),
        cost=leg.cost,
        model=result.model,
        warning=warning,
    )


def value_strategy(
    legs: Sequence[Leg], ctx: PricingContext, *, iv_overrides: dict[str, float] | None = None
) -> StrategyValuation:
    overrides = iv_overrides or {}
    leg_vals = [value_leg(leg, ctx, scenario_iv=overrides.get(leg.kind_symbol)) for leg in legs]
    return StrategyValuation(leg_vals)


# --------------------------------------------------------------------------- #
# Single-expiry terminal P&L
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ExpiryPayoff:
    breakevens: list[float]
    max_profit: float | None  # None = unbounded (e.g. naked short call)
    max_loss: float | None  # None = unbounded
    points: list[tuple[float, float]]  # (underlying_price, total_payoff) samples


def terminal_payoff(
    legs: Sequence[Leg], *, spot_range: tuple[float, float] | None = None, samples: int = 401
) -> ExpiryPayoff:
    """Terminal (expiration) payoff for a single-expiry strategy.

    Raises :class:`MixedExpiryError` if legs span more than one expiration —
    there is no single terminal payoff in that case (see module docstring).
    Stock legs settle at the scenario price; option legs settle at intrinsic.
    """
    expirations = {leg.expiration for leg in legs if leg.kind == "option"}
    if len(expirations) > 1:
        raise MixedExpiryError("多到期日组合没有单一最终盈亏；请按关键到期日分别调用 scenario_payoff。")

    # Underlying scan range. Default to strike +/- 3x the total option
    # premium (plus a fixed floor), so common breakevens are captured.
    strikes = [leg.strike for leg in legs if leg.strike is not None]
    total_premium = sum((leg.cost or 0.0) * leg.signed_quantity() for leg in legs if leg.kind == "option")
    if spot_range is None:
        if strikes:
            center = float(sum(strikes) / len(strikes))
            max_strike_span = max(abs(s - center) for s in strikes) if len(strikes) > 1 else 0.0
            # Need enough width to see both breakevens of a straddle: pick the
            # larger of the strike span and ~3x the per-share premium.
            width = max(5.0, max_strike_span * 2.0, abs(total_premium) * 3.0)
        else:
            center = 100.0
            width = 50.0
        lo = max(0.01, center - width)
        hi = center + width
    else:
        lo, hi = spot_range

    step = (hi - lo) / max(1, samples - 1)
    xs = [lo + step * i for i in range(samples)]
    ys = [_total_payoff_at_expiry(legs, x) for x in xs]

    breakevens = _find_zero_crossings(xs, ys)
    max_profit, max_loss = _bounded_extremes(ys, legs)
    return ExpiryPayoff(
        breakevens=breakevens,
        max_profit=max_profit,
        max_loss=max_loss,
        points=list(zip(xs, ys)),
    )


class MixedExpiryError(ValueError):
    """Raised when single-expiry payoff is requested for a multi-expiry strategy."""


@dataclass(frozen=True)
class PayoffCurves:
    """Both expiry and current payoff curves over a price scan.

    ``expiry_points``: (price, pnl) at expiration — intrinsic-only payoff.
    ``current_points``: (price, pnl) at the valuation time — model-priced.
    ``xs``: the shared price axis.
    """

    xs: list[float]
    expiry_points: list[float]
    current_points: list[float]


def current_payoff_curve(
    legs: Sequence[Leg],
    *,
    ctx: PricingContext,
    iv_overrides: dict[str, float] | None = None,
    spot_range: tuple[float, float] | None = None,
    samples: int = 201,
) -> PayoffCurves:
    """Compute both expiry and current payoff across a price scan.

    For each price on the x-axis:
    - expiry PnL = intrinsic payoff at expiration minus cost (per leg).
    - current PnL = model price at that price (with remaining time + IV) minus cost.

    Works for mixed-expiry strategies (unlike terminal_payoff), since each leg
    is priced independently under the scenario price.
    """
    overrides = iv_overrides or {}
    strikes = [leg.strike for leg in legs if leg.strike is not None]
    total_premium = sum((leg.cost or 0.0) * leg.signed_quantity() for leg in legs if leg.kind == "option")
    if spot_range is None:
        if strikes:
            center = float(sum(strikes) / len(strikes))
            max_span = max(abs(s - center) for s in strikes) if len(strikes) > 1 else 0.0
            width = max(5.0, max_span * 2.0, abs(total_premium) * 3.0)
        else:
            center = ctx.spot or 100.0
            width = 50.0
        lo = max(0.01, center - width)
        hi = center + width
    else:
        lo, hi = spot_range

    step = (hi - lo) / max(1, samples - 1)
    xs = [lo + step * i for i in range(samples)]
    expiry_pnl: list[float] = []
    current_pnl: list[float] = []

    for price in xs:
        scenario_ctx = PricingContext(
            spot=price,
            r=ctx.r,
            q=ctx.q,
            default_iv=ctx.default_iv,
            now=ctx.now,
        )
        exp_total = 0.0
        cur_total = 0.0
        for leg in legs:
            signed = leg.signed_quantity()
            cost = leg.cost if leg.cost is not None else 0.0
            if leg.kind == "stock":
                exp_total += (price - cost) * signed
                cur_total += (price - cost) * signed
                continue
            if leg.strike is None or leg.option_side is None:
                continue
            # Expiry: intrinsic minus cost.
            intrinsic = intrinsic_value(price, leg.strike, leg.option_side)
            exp_total += (intrinsic - cost) * signed
            # Current: reprice with remaining time and the leg's current IV.
            lv = value_leg(
                leg,
                scenario_ctx,
                scenario_iv=overrides.get(leg.kind_symbol),
            )
            cur_total += (lv.price - cost) * signed
        expiry_pnl.append(exp_total)
        current_pnl.append(cur_total)

    return PayoffCurves(xs=xs, expiry_points=expiry_pnl, current_points=current_pnl)


def _total_payoff_at_expiry(legs: Sequence[Leg], underlying: float) -> float:
    total = 0.0
    for leg in legs:
        signed = leg.signed_quantity()
        if leg.kind == "stock":
            cost = leg.cost if leg.cost is not None else 0.0
            total += (underlying - cost) * signed
            continue
        if leg.strike is None or leg.option_side is None:
            continue
        cost = leg.cost if leg.cost is not None else 0.0
        intrinsic = intrinsic_value(underlying, leg.strike, leg.option_side)
        total += (intrinsic - cost) * signed
    return total


def _find_zero_crossings(xs: list[float], ys: list[float]) -> list[float]:
    out: list[float] = []
    for i in range(len(ys) - 1):
        y0, y1 = ys[i], ys[i + 1]
        if y0 == 0:
            out.append(xs[i])
            continue
        if (y0 < 0) != (y1 < 0):
            # Linear interpolation for the root.
            x0, x1 = xs[i], xs[i + 1]
            frac = -y0 / (y1 - y0)
            out.append(x0 + frac * (x1 - x0))
    if ys and ys[-1] == 0:
        out.append(xs[-1])
    return out


def _bounded_extremes(ys: list[float], legs: Sequence[Leg]) -> tuple[float | None, float | None]:
    """Estimate max profit/loss from sampled payoff.

    Returns ``(max_profit, max_loss)``; ``None`` marks an unbounded direction.
    A *naked* short call has bounded premium income and unbounded loss as the
    underlying rises. Other strategies are bounded within the sampled range.
    """
    short_calls = [
        leg for leg in legs if leg.kind == "option" and leg.option_side == "call" and leg.direction == "sell"
    ]
    long_call_contracts = sum(
        leg.quantity for leg in legs if leg.kind == "option" and leg.option_side == "call" and leg.direction == "buy"
    )
    long_stock_contracts = sum(
        leg.quantity / _OPTION_CONTRACT_SHARES for leg in legs if leg.kind == "stock" and leg.direction == "buy"
    )
    short_call_contracts = sum(leg.quantity for leg in short_calls)
    # One listed equity option contract represents 100 shares. A residual short
    # call quantity has unbounded upside loss even when part of the position is
    # covered by stock or long calls.
    naked_short_call = short_call_contracts > (long_call_contracts + long_stock_contracts)
    max_y = max(ys) if ys else 0.0
    min_y = min(ys) if ys else 0.0
    max_profit = max_y
    max_loss = None if naked_short_call else (-min_y if min_y < 0 else 0.0)
    return max_profit, max_loss


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #


def template_long_call(symbol: str, strike: float, expiration: date, *, cost: float, qty: float = 1.0) -> Leg:
    return Leg("option", "buy", qty, symbol, strike, expiration, "call", cost=cost)


def template_long_put(symbol: str, strike: float, expiration: date, *, cost: float, qty: float = 1.0) -> Leg:
    return Leg("option", "buy", qty, symbol, strike, expiration, "put", cost=cost)


def template_bull_call_spread(
    symbol: str,
    long_strike: float,
    short_strike: float,
    expiration: date,
    *,
    long_cost: float,
    short_cost: float,
    qty: float = 1.0,
) -> list[Leg]:
    return [
        template_long_call(symbol, long_strike, expiration, cost=long_cost, qty=qty),
        Leg("option", "sell", qty, symbol, short_strike, expiration, "call", cost=short_cost),
    ]


def template_straddle(
    symbol: str, strike: float, expiration: date, *, call_cost: float, put_cost: float, qty: float = 1.0
) -> list[Leg]:
    return [
        template_long_call(symbol, strike, expiration, cost=call_cost, qty=qty),
        template_long_put(symbol, strike, expiration, cost=put_cost, qty=qty),
    ]


def template_iron_condor(
    symbol: str,
    expiration: date,
    *,
    put_short: float,
    put_long: float,
    call_short: float,
    call_long: float,
    put_short_cost: float,
    put_long_cost: float,
    call_short_cost: float,
    call_long_cost: float,
    qty: float = 1.0,
) -> list[Leg]:
    return [
        Leg("option", "buy", qty, symbol, put_long, expiration, "put", cost=put_long_cost),
        Leg("option", "sell", qty, symbol, put_short, expiration, "put", cost=put_short_cost),
        Leg("option", "sell", qty, symbol, call_short, expiration, "call", cost=call_short_cost),
        Leg("option", "buy", qty, symbol, call_long, expiration, "call", cost=call_long_cost),
    ]


# --------------------------------------------------------------------------- #
# Suggested limit price (three tiers + confidence)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LimitPriceSuggestion:
    conservative: float | None
    neutral: float | None
    aggressive: float | None
    confidence: str  # "high" | "medium" | "low"
    anchors: dict[str, float]
    note: str = ""

    def as_directional(self, direction: Direction) -> dict[str, float | None]:
        """Return tiers ordered low->high for buys, high->low for sells."""
        tiers = {
            "conservative": self.conservative,
            "neutral": self.neutral,
            "aggressive": self.aggressive,
        }
        if direction == "sell":
            # Reverse: aggressive (highest) first for sellers.
            return {k: tiers[k] for k in ("aggressive", "neutral", "conservative")}
        return tiers


def suggest_limit_price(
    *,
    fmv: float | None,
    model_price: float | None,
    day_vwap: float | None,
    day_close: float | None,
    open_interest: float | None,
    volume: float | None,
    is_0dte: bool = False,
    model_confidence_note: str = "",
) -> LimitPriceSuggestion:
    """Build a three-tier suggested limit price from available valuation anchors.

    No NBBO -> this is an estimate, never called "best price". When anchors are
    too sparse or too dispersed, tiers are returned as None and the caller must
    show the raw anchors instead (per the plan's "low confidence -> no tiers"
    rule).
    """
    anchors: dict[str, float] = {}
    for name, value in (("fmv", fmv), ("model", model_price), ("vwap", day_vwap), ("close", day_close)):
        if value is not None and math.isfinite(value) and value > 0:
            anchors[name] = value

    if len(anchors) < 2:
        return LimitPriceSuggestion(
            conservative=None,
            neutral=None,
            aggressive=None,
            confidence="low",
            anchors=anchors,
            note="锚点不足，仅展示原始值。" + model_confidence_note,
        )

    values = sorted(anchors.values())
    neutral = values[len(values) // 2]
    low = values[0]
    high = values[-1]
    # Spread width relative to neutral drives confidence.
    spread_pct = (high - low) / neutral if neutral > 0 else 1.0

    if is_0dte:
        confidence = "low"
        note = "0DTE 且无实时 NBBO；建议价仅供参考。"
    elif spread_pct > 0.25 or volume is None or (open_interest or 0) < 100:
        confidence = "medium"
        note = "锚点分散或流动性偏低，置信度中等。"
    else:
        confidence = "high"
        note = ""

    # Conservative/neutral/aggressive are narrowbands around the median.
    # ponytail: fixed 25% half-width of the anchor spread; tighten when we
    # have real NBBO and can use actual half-spread.
    half = (high - low) * 0.25
    return LimitPriceSuggestion(
        conservative=max(0.01, neutral - half),
        neutral=neutral,
        aggressive=neutral + half,
        confidence=confidence,
        anchors=anchors,
        note=note,
    )


# --------------------------------------------------------------------------- #
# Effective leverage (lambda)
# --------------------------------------------------------------------------- #


def effective_leverage(valuation: "StrategyValuation", spot: float) -> float | None:
    """Portfolio effective leverage: % change in portfolio value per 1% move in spot.

    Equals (net_delta * spot) / |net_price|, where net_delta and net_price share
    the same unit basis (per-share * contracts), so the 100 shares/contract
    factor cancels. The absolute value keeps the sign coming only from delta so
    that long and short positions get correct directional leverage. Returns
    None when net_price is ~0 (zero-cost structures such as at-money iron
    condors have no well-defined leverage) or spot <= 0.
    """
    if spot <= 0:
        return None
    net_price = valuation.net_price
    # ponytail: |net_price| < 1 cent per contract-basis -> treat as zero;
    # threshold absorbs float noise near flat structures.
    if abs(net_price) < 1e-6:
        return None
    return valuation.net_greeks["delta"] * spot / abs(net_price)


__all__ = [
    "Leg",
    "PricingContext",
    "LegValuation",
    "StrategyValuation",
    "ExpiryPayoff",
    "MixedExpiryError",
    "LimitPriceSuggestion",
    "value_leg",
    "value_strategy",
    "terminal_payoff",
    "template_long_call",
    "template_long_put",
    "template_bull_call_spread",
    "template_straddle",
    "template_iron_condor",
    "suggest_limit_price",
    "effective_leverage",
]
