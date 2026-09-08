"""标准协议握手命令原始字节。

移植自 niyoh120/easy_tdx（固定提交 e374a0da2834119ac695c1083805d1b0a60967c2）
的 ``commands/setup.py``（其本身自 pytdx setup_commands 逐字复制，
已在真实服务器验证）。连接建立后必须按序发送三条握手命令，
每条读取并丢弃响应（部分服务器对个别命令不响应，读取失败按参考
实现容忍并继续）。
"""

from __future__ import annotations

from typing import Final

SETUP_CMD1: Final[bytes] = bytes.fromhex("0c0218930001030003000d0001")
SETUP_CMD2: Final[bytes] = bytes.fromhex("0c0218940001030003000d0002")
SETUP_CMD3: Final[bytes] = bytes.fromhex(
    "0c031899000120002000db0fd5d0c9ccd6a4a8af0000008fc22540130000d500c9ccbdf0d7ea00000002"
)

SETUP_COMMANDS: Final[tuple[bytes, ...]] = (SETUP_CMD1, SETUP_CMD2, SETUP_CMD3)
