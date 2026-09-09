"""schwab-api 可导入测试助手。

独立成模块的原因：pytest prepend 导入模式下，测试代码里的
``from conftest import`` 会以顶层模块名 ``conftest`` 解析，多目录
一起收集时（如 ``pytest services/schwab-api/tests services/tdx-api/tests``）
会命中其它服务 conftest 的 ``sys.modules`` 缓存或 sys.path 靠前目录。
``schwab_fakes`` 名字全局唯一，任何收集顺序下都能无歧义解析。
"""

from __future__ import annotations

import datetime

from schwab_api.config import Config
from schwab_api.store import TokenRow

APP_KEY = "A" * 32
APP_SECRET = "S" * 32
CALLBACK_URL = "https://127.0.0.1"


def make_config(**overrides) -> Config:
    kwargs = dict(
        app_key=APP_KEY,
        app_secret=APP_SECRET,
        callback_url=CALLBACK_URL,
        tokens_db="~/.schwabdev-test-unreachable/tokens.db",
        tokens_encryption=None,
        host="127.0.0.1",
        port=8010,
        api_key=None,
        keepalive_interval_hours=12.0,
    )
    kwargs.update(overrides)
    return Config(**kwargs)


def make_row(issued: datetime.datetime | None = None, **overrides) -> TokenRow:
    issued = issued or datetime.datetime.now(datetime.timezone.utc)
    kwargs = dict(
        access_token_issued=issued,
        refresh_token_issued=issued,
        access_token="access-123",
        refresh_token="refresh-456",
        id_token="id-789",
        expires_in=1800,
        token_type="Bearer",
        scope="api",
    )
    kwargs.update(overrides)
    return TokenRow(**kwargs)
