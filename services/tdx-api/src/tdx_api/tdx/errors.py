"""协议层错误类型。

边界约定：
- ``TdxConnectionError``：连接/读写/握手失败，属可重试的主机级故障（触发换主机）。
- ``TdxTimeoutError``：单个 IO 操作超出剩余预算，与连接错误同等对待但语义更明确。
- ``TdxDecodeError``：响应字节畸形/截断/校验失败，属确定性故障（直接失败，不换主机）。
- ``TdxProtocolError``：服务器返回不可用的响应标识（如登录失败），按确定性故障处理。
"""

from __future__ import annotations


class TdxError(Exception):
    """协议层错误基类。"""


class TdxConnectionError(TdxError):
    """TCP 连接建立/收发失败。"""


class TdxTimeoutError(TdxError):
    """IO 操作超时（受请求总预算约束）。"""


class TdxDecodeError(TdxError):
    """响应帧或字段解码失败（截断、长度不符、非法值）。"""


class TdxProtocolError(TdxError):
    """服务器拒绝或返回不可用响应（如 MAC EX 登录失败）。"""
