"""协议层数值枚举（端口/帧标识/市场码/周期/复权）。

移植自 niyoh120/easy_tdx（固定提交 e374a0da2834119ac695c1083805d1b0a60967c2）
的 ``models/enums.py``、``mac/enums.py``。仅保留本服务用到的取值。

市场码约定（已按参考实现的 CLI 与调用点交叉验证）：
- 标准协议（security_list/quotes/bars 等）与 MAC 族数据命令
  （0x122A/0x122B/0x122E/0x122F）共用标准市场码：0=深、1=沪、2=北。
- MAC EX 扩展行情命令与 MAC 族数据命令在 EX 会话上使用 ExMarket 扩展市场码
  （如 31=港股主板、74=美股、47=中金所）。
"""

from __future__ import annotations

from enum import IntEnum

#: 标准协议端口（标准 TDX 与 MAC 行情服务器）。
STANDARD_PORT = 7709
#: MAC EX 扩展行情服务器端口。
MAC_EX_PORT = 7727


class StdMarket(IntEnum):
    """标准协议市场码（A 股，标准与 MAC 族命令共用）。"""

    SZ = 0
    SH = 1
    BJ = 2


class MacPeriod(IntEnum):
    """MAC 族 K 线周期码（0x122E 命令，标准与扩展市场共用）。"""

    MIN_5 = 0
    MIN_15 = 1
    MIN_30 = 2
    MIN_60 = 3
    DAILY = 4
    WEEKLY = 5
    MONTHLY = 6
    MIN_1 = 7


class Adjust(IntEnum):
    """复权方式（MAC 0x122E 命令的 fq 参数）。"""

    NONE = 0
    QFQ = 1
    HFQ = 2


class ExMarket(IntEnum):
    """MAC EX 扩展市场码（本服务能力矩阵覆盖的子集）。"""

    INTL_INDEX = 12  # 国际指数（SPX/DJI/IXIC/NDX）
    COMEX_FUTURES = 16
    NYMEX_FUTURES = 17
    CBOT_FUTURES = 18
    HK_INDEX = 27  # 香港指数（HSI/HSCEI/HSTECH）
    CZCE_FUTURES = 28
    DCE_FUTURES = 29
    SHFE_FUTURES = 30
    HK_MAIN_BOARD = 31
    SH_GOLD = 46  # 上海黄金交易所（现货递延）
    CFFEX_FUTURES = 47
    HK_GEM = 48
    GFEX_FUTURES = 66
    US_STOCK = 74
