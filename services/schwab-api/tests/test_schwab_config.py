"""Config validation for the keepalive interval — the idle-window regression.

实测（2026-09）：Schwab 拒绝空闲超过 ~30min（access_token TTL）的 refresh token，
保活周期配置成长值会在运行时首次轮换即 invalid_grant（链死亡）。这类错误配置必须
在启动时炸掉，留到运行时就是静默死亡。
"""

from __future__ import annotations

import pytest
from schwab_api.config import MAX_KEEPALIVE_INTERVAL_HOURS, Config


def make_env(interval: str | None = None) -> dict[str, str]:
    env = {"FA_SCHWAB_APP_KEY": "k", "FA_SCHWAB_APP_SECRET": "s"}
    if interval is not None:
        env["FA_SCHWAB_KEEPALIVE_INTERVAL_HOURS"] = interval
    return env


def test_default_interval_is_verified_value():
    """默认即实测验证过的 0.4h（< 30min 空闲窗口，留抖动余量）。"""
    config = Config.from_env(make_env())
    assert config.keepalive_interval_hours == MAX_KEEPALIVE_INTERVAL_HOURS == 0.4


def test_custom_interval_within_cap_accepted():
    assert Config.from_env(make_env("0.25")).keepalive_interval_hours == 0.25


def test_interval_above_cap_rejected():
    """12h 是生产事故配置：必须启动即失败，而非运行时链死亡。"""
    with pytest.raises(ValueError, match="must be in \\(0, 0.4\\]"):
        Config.from_env(make_env("12"))


def test_zero_interval_rejected():
    with pytest.raises(ValueError, match="must be in"):
        Config.from_env(make_env("0"))


def test_negative_interval_rejected():
    with pytest.raises(ValueError, match="must be in"):
        Config.from_env(make_env("-0.5"))


def test_non_numeric_interval_rejected():
    with pytest.raises(ValueError, match="must be a number"):
        Config.from_env(make_env("abc"))
