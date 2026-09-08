"""前复权（QFQ）纯函数测试：手工可计算的独立期望。

期望值由公式手工推导（分红/送转/配股/组合事件），
与参考 SDK 无对拍关系。
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from tdx_api.tdx.adjust import (
    apply_factor_chain,
    apply_forward_adjust,
    build_factor_chain,
    compute_forward_factor,
    extract_dividend_events,
    has_bad_prices,
)


def bar(day: str, open_, high, low, close, vol=1000.0, amount=10000.0):
    return {
        "datetime": datetime.fromisoformat(f"{day}T15:00:00"),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "vol": vol,
        "amount": amount,
    }


# --------------------------------------------------------------------- #
# 因子公式
# --------------------------------------------------------------------- #


def test_pure_dividend_factor():
    """每股分红 0.5 元、含权收盘 20 → (20-0.5)/20 = 0.975。"""
    assert compute_forward_factor(20.0, 0.5, 0.0, 0.0, 0.0) == pytest.approx(0.975)


def test_bonus_share_factor():
    """10 送 10（每股送 1.0）→ P/(2P) = 0.5。"""
    assert compute_forward_factor(20.0, 0.0, 0.0, 1.0, 0.0) == pytest.approx(0.5)


def test_rights_issue_factor():
    """配股：含权收盘 10、配股价 5、每股配 0.3 → (10+5×0.3)/(10×1.3)。"""
    assert compute_forward_factor(10.0, 0.0, 5.0, 0.0, 0.3) == pytest.approx(11.5 / 13.0)


def test_combined_event_factor():
    """分红 0.5 + 送转 0.5 + 配股 0.3@5 元，含权收盘 20 → (20-0.5+1.5)/(20×1.8)。"""
    assert compute_forward_factor(20.0, 0.5, 5.0, 0.5, 0.3) == pytest.approx(21.0 / 36.0)


@pytest.mark.parametrize(
    "cum_close,fenhong,peigujia,songzhuangu,peigu",
    [
        (0.0, 1.0, 0.0, 0.0, 0.0),  # 缺前收盘
        (-5.0, 1.0, 0.0, 0.0, 0.0),  # 非法价
        (10.0, 1.0, 0.0, -1.0, 0.0),  # 分母为 0（送转 -100%）
    ],
)
def test_invalid_factor_inputs_return_none(cum_close, fenhong, peigujia, songzhuangu, peigu):
    assert compute_forward_factor(cum_close, fenhong, peigujia, songzhuangu, peigu) is None


# --------------------------------------------------------------------- #
# 事件提取
# --------------------------------------------------------------------- #


def test_extract_events_keeps_only_category_1():
    records = [
        {"date": "2024-05-01", "category": 5, "panqian_liutong": 1.0},
        {"date": "2024-06-10", "category": 1, "fenhong": 0.3},
        {"date": "2024-07-01", "category": 2},
    ]
    events = extract_dividend_events(records)
    assert [e["date"] for e in events] == [date(2024, 6, 10)]


def test_extract_events_skips_all_empty_fields_and_bad_dates():
    records = [
        {"date": "2024-06-10", "category": 1, "fenhong": None, "peigujia": None},
        {"date": "garbage", "category": 1, "fenhong": 0.3},
        {"date": "2024-06-11", "category": 1, "fenhong": 0.3, "peigu": 0.1},
    ]
    events = extract_dividend_events(records)
    assert len(events) == 1
    assert events[0]["fenhong"] == 0.3
    assert events[0]["peigu"] == 0.1


def test_extract_events_sorts_ascending():
    records = [
        {"date": "2025-01-10", "category": 1, "fenhong": 0.1},
        {"date": "2024-01-10", "category": 1, "fenhong": 0.2},
    ]
    events = extract_dividend_events(records)
    assert [e["date"].year for e in events] == [2024, 2025]


# --------------------------------------------------------------------- #
# 复权应用（手工样例）
# --------------------------------------------------------------------- #


def test_single_dividend_adjusts_only_prior_bars():
    """除权日 2024-06-11：此前 bar ×0.975，当日及以后不动。"""
    bars = [bar("2024-06-07", 20, 21, 19, 20), bar("2024-06-10", 20, 21, 19, 20), bar("2024-06-11", 19.6, 20, 19, 19.5)]
    events = [{"date": date(2024, 6, 11), "fenhong": 0.5, "peigujia": 0.0, "songzhuangu": 0.0, "peigu": 0.0}]
    result = apply_forward_adjust(bars, events)
    assert result.bars[0]["close"] == pytest.approx(19.5)
    assert result.bars[1]["close"] == pytest.approx(19.5)
    assert result.bars[2]["close"] == pytest.approx(19.5)  # 原值 19.5 未动
    assert result.skipped_event_dates == []
    # vol/amount 不复权
    assert result.bars[0]["vol"] == 1000.0


def test_event_after_last_bar_adjusts_whole_series():
    """锚定最新：事件晚于请求末日时整段调整（跨页一致性的关键）。

    含权基准 = 区间末根原始收盘 10 → 因子 (10-0.5)/10 = 0.95。
    """
    bars = [bar("2024-01-02", 10, 10, 10, 10), bar("2024-01-03", 10, 10, 10, 10)]
    events = [{"date": date(2024, 6, 11), "fenhong": 0.5, "peigujia": 0.0, "songzhuangu": 0.0, "peigu": 0.0}]
    result = apply_forward_adjust(bars, events)
    assert result.bars[0]["close"] == pytest.approx(9.5)
    assert result.bars[1]["close"] == pytest.approx(9.5)


def test_event_before_first_bar_leaves_series_unchanged():
    bars = [bar("2024-07-01", 10, 10, 10, 10)]
    events = [{"date": date(2024, 1, 10), "fenhong": 0.5, "peigujia": 0.0, "songzhuangu": 0.0, "peigu": 0.0}]
    result = apply_forward_adjust(bars, events)
    assert result.bars[0]["close"] == pytest.approx(10.0)


def test_multiple_events_chain_and_use_raw_close_base():
    """两次分红：因子分别由原始含权收盘计算并连乘（事件间互不影响基准）。"""
    bars = [
        bar("2024-01-02", 20, 20, 20, 20),  # 事件1 前一日（含权基准）
        bar("2024-01-03", 19.5, 19.5, 19.5, 19.5),  # 除权日1
        bar("2024-02-05", 19.5, 19.5, 19.5, 19.5),  # 事件2 前一日（含权基准）
        bar("2024-02-06", 19.0, 19.0, 19.0, 19.0),  # 除权日2
    ]
    events = [
        {"date": date(2024, 1, 3), "fenhong": 0.5, "peigujia": 0.0, "songzhuangu": 0.0, "peigu": 0.0},
        {"date": date(2024, 2, 6), "fenhong": 0.5, "peigujia": 0.0, "songzhuangu": 0.0, "peigu": 0.0},
    ]
    result = apply_forward_adjust(bars, events)
    f1 = 19.5 / 20.0
    f2 = 19.0 / 19.5
    assert result.bars[0]["close"] == pytest.approx(20.0 * f1 * f2)
    assert result.bars[1]["close"] == pytest.approx(19.5 * f2)
    # 02-05 早于事件2（02-06）→ 需乘 f2；晚于事件1 → 不乘 f1。
    assert result.bars[2]["close"] == pytest.approx(19.5 * f2)
    assert result.bars[3]["close"] == pytest.approx(19.0)


def test_bars_input_order_does_not_matter():
    """协议分页返回 newest-first：乱序输入不影响结果。"""
    bars = [bar("2024-06-11", 19.6, 20, 19, 19.5), bar("2024-06-07", 20, 21, 19, 20)]
    events = [{"date": date(2024, 6, 11), "fenhong": 0.5, "peigujia": 0.0, "songzhuangu": 0.0, "peigu": 0.0}]
    result = apply_forward_adjust(bars, events)
    # 06-07（含权）×0.975 → 19.5；06-11（除权日）保持 19.5。
    assert sorted(round(b["close"], 6) for b in result.bars) == [19.5, 19.5]


def test_missing_pre_close_reports_skipped_event():
    """基准 bar 缺收盘价 → 事件跳过并上报（调用方判 adjustment_unavailable）。"""
    bars = [bar("2024-06-07", 20, 21, 19, None), bar("2024-06-11", 19.6, 20, 19, 19.5)]
    events = [{"date": date(2024, 6, 11), "fenhong": 0.5, "peigujia": 0.0, "songzhuangu": 0.0, "peigu": 0.0}]
    result = apply_forward_adjust(bars, events)
    assert result.skipped_event_dates == [date(2024, 6, 11)]
    assert result.bars[0]["close"] is None


def test_zero_divisor_reports_skipped_event():
    bars = [bar("2024-06-07", 20, 20, 20, 20), bar("2024-06-11", 19.6, 20, 19, 19.5)]
    events = [{"date": date(2024, 6, 11), "fenhong": 0.0, "peigujia": 0.0, "songzhuangu": -1.0, "peigu": 0.0}]
    result = apply_forward_adjust(bars, events)
    assert result.skipped_event_dates == [date(2024, 6, 11)]


def test_no_events_returns_copy():
    bars = [bar("2024-06-07", 20, 21, 19, 20)]
    result = apply_forward_adjust(bars, [])
    assert result.bars[0]["close"] == 20.0
    assert result.bars is not bars


def test_build_factor_chain_supports_minute_application():
    """因子链可应用到分钟线：按交易日判断（bar 日期 < 事件日期 → 调整）。"""
    daily = [bar("2024-06-10", 20, 20, 20, 20)]
    events = [{"date": date(2024, 6, 11), "fenhong": 0.5, "peigujia": 0.0, "songzhuangu": 0.0, "peigu": 0.0}]
    chain, skipped = build_factor_chain(daily, events)
    assert skipped == []
    assert chain == [(date(2024, 6, 11), pytest.approx(0.975))]

    minute_bars = [
        {"datetime": datetime(2024, 6, 10, 9, 31), "open": 20, "high": 20, "low": 20, "close": 20},
        {"datetime": datetime(2024, 6, 11, 9, 31), "open": 19.5, "high": 19.5, "low": 19.5, "close": 19.5},
    ]
    adjusted = apply_factor_chain(minute_bars, chain)
    assert adjusted[0]["close"] == pytest.approx(19.5)
    assert adjusted[1]["close"] == pytest.approx(19.5)  # 除权日分钟线不动


def test_has_bad_prices_detects_non_positive_and_nan():
    assert has_bad_prices([bar("2024-06-07", 20, 21, 19, -0.1)])
    assert has_bad_prices([bar("2024-06-07", 20, 21, 19, float("nan"))])
    assert has_bad_prices([bar("2024-06-07", 0, 21, 19, 20)])
    assert has_bad_prices([bar("2024-06-07", None, None, None, None)])  # 全缺失亦视为非法
    assert not has_bad_prices([bar("2024-06-07", 20, 21, 19, 0.5)])
