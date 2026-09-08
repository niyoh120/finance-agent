"""HTTP 契约模型（Pydantic v2）。

统一响应封装 ``{"data": ..., "meta": {...}}``；meta 字段按端点裁剪，
允许额外键（extra=allow）以便能力矩阵演进。数值字段缺失为 null，
零值保留；NaN/Infinity 在查询层编码边界已转 null。
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Meta(BaseModel):
    """响应元数据（按端点裁剪；允许额外键）。"""

    model_config = ConfigDict(extra="allow")

    market: str | None = None
    service_code: int | None = None
    fetched_at: str | None = None
    count: int | None = None
    offset: int | None = None
    limit: int | None = None
    next_offset: int | None = None
    complete: bool | None = None
    timezone: str | None = None
    currency: str | None = None
    adjust: str | None = None
    adjustment_source: str | None = None
    interval: str | None = None


class ErrorBody(BaseModel):
    """错误响应体。"""

    code: str = Field(examples=["unsupported_capability"])
    message: str


class ErrorResponse(BaseModel):
    """统一错误封装 ``{"error": {...}}``。"""

    error: ErrorBody


class Bar(BaseModel):
    """K 线（日线及以上 datetime 为交易日期；分钟线为本地时间戳）。"""

    model_config = ConfigDict(extra="forbid")

    datetime: str = Field(description="日线=YYYY-MM-DD；分钟线=YYYY-MM-DDTHH:MM:SS（区间起点，本地墙钟）")
    trade_date: str = Field(description="交易日 YYYY-MM-DD（夜盘/跨日场景与自然日区分）")
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    amount: float | None = None


class Quote(BaseModel):
    """批量报价行（未返回字段为 null）。"""

    model_config = ConfigDict(extra="allow")

    market: str
    code: str
    name: str | None = None
    price: float | None = None
    pre_close: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None
    amount: float | None = None
    bid: float | None = None
    ask: float | None = None
    bid_volume: int | None = None
    ask_volume: int | None = None


class Instrument(BaseModel):
    """目录条目（CN 含手数/精度，EX 含描述）。"""

    model_config = ConfigDict(extra="allow")

    market: str
    code: str
    name: str | None = None


class MinutePoint(BaseModel):
    """分时点。CN 时间为映射的分钟终点；EX 为协议上报时间。"""

    model_config = ConfigDict(extra="allow")

    time: str
    price: float | None = None
    volume: float | None = None
    avg_price: float | None = None


class TransactionRow(BaseModel):
    """逐笔成交（协议原生倒序：最新在前）。"""

    model_config = ConfigDict(extra="forbid")

    time: str
    price: float | None = None
    volume: float | None = None
    direction: int = Field(description="0=buy 1=sell 2=neutral 5=after_hours")
    direction_label: str | None = None
    trade_count: int | None = None
    open_interest: int | None = None


class XdxrItem(BaseModel):
    """除权除息记录（category=1 字段为每股口径）。"""

    model_config = ConfigDict(extra="allow")

    date: str
    category: int
    category_name: str | None = None
    dividend_per_share: float | None = None
    rights_issue_price: float | None = None
    bonus_per_share: float | None = None
    rights_issue_ratio: float | None = None


class MarketEntry(BaseModel):
    """/markets 条目（能力矩阵）。"""

    model_config = ConfigDict(extra="allow")

    market: str
    service_code: int
    label: str
    protocol: str
    timezone: str | None
    currency: str
    intervals: list[str]
    adjust: list[str]
    capabilities: dict[str, bool]
    units: dict[str, object]


class Envelope(BaseModel, Generic[T]):
    """统一响应封装。data 为列表（列表型端点）或对象/null（单对象端点）。"""

    model_config = ConfigDict(extra="forbid")

    data: list[T] | T | None
    meta: Meta
