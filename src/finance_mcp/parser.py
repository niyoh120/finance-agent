import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional


@dataclass
class OptionsFlowData:
    message_id: str
    timestamp: datetime
    interval_type: str
    side: str
    symbol: str
    strike: float
    option_type: str
    expiry: date
    dte: int
    interval_volume: int
    open_interest: int
    vol_oi: float
    otm_percent: float
    bid_percent: int
    ask_percent: int
    premium: float
    avg_fill: float
    multileg_percent: float
    raw_message: str


# 🕑 Interval (5 Min) - Bid Side
HEADER_PATTERN = re.compile(
    r"(?:🕑|:clock2:)?\s*Interval\s*\((\d+\s*Min)\)\s*-\s*(Bid|Ask)\s*Side", re.IGNORECASE
)

# 🔥 Hot Contract - Ask Side
HOT_CONTRACT_PATTERN = re.compile(
    r"(?:🔥|:fire:)?\s*Hot Contract\s*-\s*(Bid|Ask)\s*Side", re.IGNORECASE
)

# **[MSTR 145 P 04/17/2026 (92 DTE)](...
# Pattern matches Markdown links in embed description. Essential for parsing Unusual Whales format.
CONTRACT_PATTERN = re.compile(
    r"\*\*\[([A-Z]+)\s+([\d.]+)\s+(P|C)\s+(\d{2}/\d{2}/\d{4})\s+\((\d+)\s*DTE\)", re.MULTILINE
)

# Key: Value patterns
INTERVAL_VOLUME_PATTERN = re.compile(r"Interval Volume:\s*([\d,]+)")
OVERALL_VOLUME_PATTERN = re.compile(r"Overall Volume:\s*([\d,]+)")
OPEN_INTEREST_PATTERN = re.compile(r"Open Interest:\s*([\d,]+)")
VOL_OI_PATTERN = re.compile(r"Vol/OI:\s*([\d.]+)")
OTM_PATTERN = re.compile(r"OTM:\s*([\d.]+)%")
BID_ASK_PATTERN = re.compile(r"Bid/Ask %:\s*(\d+)/(\d+)")
PREMIUM_PATTERN = re.compile(r"Premium:\s*\$?([\d,]+)")
AVG_FILL_PATTERN = re.compile(r"Average Fill:\s*\$?([\d.]+)")
MULTILEG_PATTERN = re.compile(r"Multi-leg Volume:\s*([\d.]+)%")


def parse_number(s: str) -> float:
    return float(s.replace(",", ""))


def parse_message(message_id: str, content: str, timestamp: datetime) -> Optional[OptionsFlowData]:
    interval_match = HEADER_PATTERN.search(content)
    hot_match = HOT_CONTRACT_PATTERN.search(content)

    if interval_match:
        interval_type = interval_match.group(1).replace(" ", "")
        side = interval_match.group(2).capitalize()
    elif hot_match:
        interval_type = "Hot"
        side = hot_match.group(1).capitalize()
    else:
        return None

    contract_match = CONTRACT_PATTERN.search(content)
    if not contract_match:
        return None

    symbol = contract_match.group(1)
    strike = float(contract_match.group(2))
    option_type = contract_match.group(3)
    expiry_str = contract_match.group(4)
    dte = int(contract_match.group(5))

    expiry = datetime.strptime(expiry_str, "%m/%d/%Y").date()

    def extract_or_zero(pattern: re.Pattern, default: str = "0") -> str:
        m = pattern.search(content)
        return m.group(1) if m else default

    interval_volume_str = extract_or_zero(INTERVAL_VOLUME_PATTERN)
    if interval_volume_str == "0":
        interval_volume_str = extract_or_zero(OVERALL_VOLUME_PATTERN)

    interval_volume = int(parse_number(interval_volume_str))
    open_interest = int(parse_number(extract_or_zero(OPEN_INTEREST_PATTERN)))
    vol_oi = float(extract_or_zero(VOL_OI_PATTERN))
    otm_percent = float(extract_or_zero(OTM_PATTERN)) / 100

    bid_ask_match = BID_ASK_PATTERN.search(content)
    bid_percent = int(bid_ask_match.group(1)) if bid_ask_match else 0
    ask_percent = int(bid_ask_match.group(2)) if bid_ask_match else 0

    premium = parse_number(extract_or_zero(PREMIUM_PATTERN))
    avg_fill = float(extract_or_zero(AVG_FILL_PATTERN))
    multileg_percent = float(extract_or_zero(MULTILEG_PATTERN)) / 100

    return OptionsFlowData(
        message_id=message_id,
        timestamp=timestamp,
        interval_type=interval_type,
        side=side,
        symbol=symbol,
        strike=strike,
        option_type=option_type,
        expiry=expiry,
        dte=dte,
        interval_volume=interval_volume,
        open_interest=open_interest,
        vol_oi=vol_oi,
        otm_percent=otm_percent,
        bid_percent=bid_percent,
        ask_percent=ask_percent,
        premium=premium,
        avg_fill=avg_fill,
        multileg_percent=multileg_percent,
        raw_message=content,
    )
