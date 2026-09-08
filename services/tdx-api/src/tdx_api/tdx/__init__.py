"""通达信协议层（服务私有）。

移植自 niyoh120/easy_tdx（固定提交 e374a0da2834119ac695c1083805d1b0a60967c2），
纯标准库实现；溯源与修改说明见服务 THIRD_PARTY_NOTICES.md。
"""

from .adjust import AdjustResult, apply_forward_adjust, compute_forward_factor, has_bad_prices
from .errors import TdxConnectionError, TdxDecodeError, TdxError, TdxProtocolError, TdxTimeoutError
from .transport import Budget, Session, make_session_factory

__all__ = [
    "AdjustResult",
    "Budget",
    "Session",
    "TdxConnectionError",
    "TdxDecodeError",
    "TdxError",
    "TdxProtocolError",
    "TdxTimeoutError",
    "apply_forward_adjust",
    "compute_forward_factor",
    "has_bad_prices",
    "make_session_factory",
]
