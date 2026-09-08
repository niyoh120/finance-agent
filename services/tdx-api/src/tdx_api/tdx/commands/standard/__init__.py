"""标准 TDX 协议命令（0x0c 帧族）。

实况验证（2026-09）：部分真实服务器对标准协议分时（0x051d）/逐笔
（0x0fc5）返回与 pytdx 文档不一致的响应体，本服务这两类查询已改走
MAC 族命令（0x122D 分时图 / 0x122F 逐笔）；标准会话仅保留目录、
财务与 XDXR 命令。
"""

from .fundamentals import GetFinanceInfoCmd, GetXdxrInfoCmd
from .securities import GetSecurityCountCmd, GetSecurityListCmd
from .setup import SETUP_COMMANDS

__all__ = [
    "SETUP_COMMANDS",
    "GetFinanceInfoCmd",
    "GetSecurityCountCmd",
    "GetSecurityListCmd",
    "GetXdxrInfoCmd",
]
