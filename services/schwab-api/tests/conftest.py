"""Shared fixtures for schwab-api tests.

可导入的测试助手（``make_config`` / ``make_row`` / 认证常量）位于
``schwab_fakes``：模块名全局唯一，避免 pytest prepend 导入模式下
``from conftest import`` 在多目录收集时命中其它服务 conftest 的
``sys.modules`` 缓存。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from schwab_api.main import create_app
from schwab_api.store import TokenStore
from schwab_fakes import make_config


@pytest.fixture()
def store(tmp_path):
    return TokenStore(str(tmp_path / "tokens.db"))


@pytest.fixture()
def config():
    return make_config()


@pytest.fixture()
def client(config, store):
    return TestClient(create_app(config=config, store=store))
