"""服务级错误与稳定错误码。

映射约定（按批准计划）：
- ``UnsupportedCapabilityError`` → 422 ``unsupported_capability``：参数合法但
  市场能力矩阵不支持该组合（周期/复权/数据类型）。
- ``UpstreamDataError``        → 502 ``upstream_data_error``：协议或数据质量错误；
  子类 ``AdjustmentUnavailableError`` 使用 ``adjustment_unavailable``。
- ``UpstreamUnavailableError`` → 503 ``upstream_unavailable``：候选上游全部不可用。
- ``BudgetExceededError``      → 504 ``budget_exceeded``：请求总预算耗尽。
- ``ConcurrencySaturationError`` → 429 ``concurrency_saturated``：并发名额占满且排队超限。

错误响应统一 ``{"error": {"code": ..., "message": ...}}``，不携带原始数据包内容。
"""

from __future__ import annotations

CODE_UNSUPPORTED_CAPABILITY = "unsupported_capability"
CODE_UPSTREAM_DATA_ERROR = "upstream_data_error"
CODE_ADJUSTMENT_UNAVAILABLE = "adjustment_unavailable"
CODE_UPSTREAM_UNAVAILABLE = "upstream_unavailable"
CODE_BUDGET_EXCEEDED = "budget_exceeded"
CODE_CONCURRENCY_SATURATED = "concurrency_saturated"


class ServiceError(Exception):
    """带稳定错误码的服务错误基类。"""

    code = "service_error"
    http_status = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UnsupportedCapabilityError(ServiceError):
    """市场能力矩阵不支持的请求组合。"""

    code = CODE_UNSUPPORTED_CAPABILITY
    http_status = 422


class InvalidParameterError(ServiceError):
    """参数值非法（超出服务边界或格式错误）。"""

    code = "invalid_parameter"
    http_status = 422


class UpstreamDataError(ServiceError):
    """上游协议错误或数据质量错误。"""

    code = CODE_UPSTREAM_DATA_ERROR
    http_status = 502


class AdjustmentUnavailableError(UpstreamDataError):
    """无法完成前复权（缺 XDXR/原始数据/可靠锚点）。"""

    code = CODE_ADJUSTMENT_UNAVAILABLE


class UpstreamUnavailableError(ServiceError):
    """全部候选上游不可用。"""

    code = CODE_UPSTREAM_UNAVAILABLE
    http_status = 503


class BudgetExceededError(ServiceError):
    """请求总预算耗尽。"""

    code = CODE_BUDGET_EXCEEDED
    http_status = 504


class ConcurrencySaturationError(ServiceError):
    """并发名额占满且排队等待超限。"""

    code = CODE_CONCURRENCY_SATURATED
    http_status = 429
