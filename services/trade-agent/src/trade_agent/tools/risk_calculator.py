import math
from collections.abc import Iterable

import numpy as np

from ..models.risk import RiskLimits


def calculate_risk_limits(
    prices: Iterable[float],
    *,
    max_portfolio_volatility: float,
    var_confidence: float,
    max_position_limit: float,
) -> RiskLimits:
    price_array = np.array(list(prices), dtype="float64")
    if price_array.size < 10:
        return RiskLimits(
            max_position_size=min(0.05, max_position_limit),
            max_loss_per_trade=0.02,
            max_portfolio_volatility=max_portfolio_volatility,
            notes="not_enough_price_data",
        )

    returns = np.diff(np.log(price_array))
    if returns.size == 0:
        return RiskLimits(
            max_position_size=min(0.05, max_position_limit),
            max_loss_per_trade=0.02,
            max_portfolio_volatility=max_portfolio_volatility,
            notes="empty_returns",
        )

    daily_vol = float(np.std(returns, ddof=1))
    annualized_vol = daily_vol * math.sqrt(252)

    var_percentile = np.percentile(returns, (1 - var_confidence) * 100)
    var_value = abs(float(var_percentile))

    if annualized_vol <= 0:
        max_position_size = min(0.05, max_position_limit)
    else:
        max_position_size = min(max_position_limit, 0.1 / annualized_vol)

    return RiskLimits(
        max_position_size=max_position_size,
        max_loss_per_trade=var_value,
        max_portfolio_volatility=max_portfolio_volatility,
    )
