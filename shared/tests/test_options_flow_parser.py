from datetime import UTC, datetime

from shared.options_flow_parser import parse_message


def test_parse_message_parses_interval_flow() -> None:
    content = """🕑 Interval (5 Min) - Bid Side
**[MSTR 145 P 04/17/2026 (92 DTE)](https://example.com)**
Interval Volume: 1,234
Open Interest: 432
Vol/OI: 2.86
OTM: 10%
Bid/Ask %: 70/30
Premium: $123,000
Average Fill: $4.56
Multi-leg Volume: 12.5%
"""

    parsed = parse_message("123", content, datetime(2026, 1, 5, tzinfo=UTC))

    assert parsed is not None
    assert parsed.message_id == "123"
    assert parsed.interval_type == "5Min"
    assert parsed.side == "Bid"
    assert parsed.symbol == "MSTR"
    assert parsed.strike == 145.0
    assert parsed.option_type == "P"
    assert parsed.dte == 92
    assert parsed.interval_volume == 1234
    assert parsed.open_interest == 432
    assert parsed.vol_oi == 2.86
    assert parsed.otm_percent == 0.10
    assert parsed.bid_percent == 70
    assert parsed.ask_percent == 30
    assert parsed.premium == 123000.0
    assert parsed.avg_fill == 4.56
    assert parsed.multileg_percent == 0.125


def test_parse_message_falls_back_to_overall_volume() -> None:
    content = """🔥 Hot Contract - Ask Side
**[TSLA 300 C 05/16/2026 (20 DTE)](https://example.com)**
Overall Volume: 5,678
Open Interest: 120
Vol/OI: 47.3
OTM: 3.5%
Bid/Ask %: 25/75
Premium: $980,000
Average Fill: $12.34
Multi-leg Volume: 0%
"""

    parsed = parse_message("456", content, datetime(2026, 4, 26, tzinfo=UTC))

    assert parsed is not None
    assert parsed.interval_type == "Hot"
    assert parsed.side == "Ask"
    assert parsed.interval_volume == 5678
    assert parsed.symbol == "TSLA"


def test_parse_message_returns_none_for_unrecognized_content() -> None:
    parsed = parse_message("789", "not an options alert", datetime(2026, 1, 1, tzinfo=UTC))

    assert parsed is None
