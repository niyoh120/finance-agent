"""Shared fixtures for schwab-api tests."""

from __future__ import annotations

import datetime

import pytest
from fastapi.testclient import TestClient
from schwab_api.config import Config
from schwab_api.main import create_app
from schwab_api.store import TokenRow, TokenStore

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


@pytest.fixture()
def store(tmp_path):
    return TokenStore(str(tmp_path / "tokens.db"))


@pytest.fixture()
def config():
    return make_config()


@pytest.fixture()
def client(config, store):
    return TestClient(create_app(config=config, store=store))
