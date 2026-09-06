"""TokenStore tests, including the schwabdev 4.x schema-compatibility sentinel."""

from __future__ import annotations

import datetime
import sqlite3

import pytest
from cryptography.fernet import Fernet
from schwab_api.store import TokenRow, TokenStore
from schwabdev.tokens import Tokens

APP_KEY = "A" * 32  # schwabdev requires even length, combined >= 32 chars
APP_SECRET = "S" * 32
CALLBACK_URL = "https://127.0.0.1"


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


class AuthSpy:
    """Stands in for schwabdev's interactive auth flow; records calls, never hangs."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, auth_url: str) -> str:
        self.calls.append(auth_url)
        raise RuntimeError("interactive auth must not run in tests")


# ---- roundtrip / persistence -------------------------------------------------


def test_write_read_roundtrip(tmp_path):
    store = TokenStore(str(tmp_path / "tokens.db"))
    issued = datetime.datetime(2025, 1, 15, 12, 30, 0, tzinfo=datetime.timezone.utc)
    row = make_row(issued)
    store.write(row)

    loaded = store.read()
    assert loaded == row


def test_write_upserts_single_row(tmp_path):
    store = TokenStore(str(tmp_path / "tokens.db"))
    store.write(make_row(access_token="first"))
    store.write(make_row(access_token="second"))

    with sqlite3.connect(tmp_path / "tokens.db") as conn:
        count = conn.execute("SELECT COUNT(*) FROM schwabdev").fetchone()[0]
    assert count == 1
    assert store.read().access_token == "second"


def test_read_returns_none_for_empty_db(tmp_path):
    store = TokenStore(str(tmp_path / "tokens.db"))
    assert store.read() is None


# ---- encryption --------------------------------------------------------------


def test_encryption_roundtrip_and_at_rest(tmp_path):
    key = Fernet.generate_key().decode()
    store = TokenStore(str(tmp_path / "tokens.db"), encryption_key=key)
    store.write(make_row(access_token="plain-access", refresh_token="plain-refresh"))

    with sqlite3.connect(tmp_path / "tokens.db") as conn:
        raw_access, raw_refresh = conn.execute("SELECT access_token, refresh_token FROM schwabdev").fetchone()
    assert raw_access.startswith("enc:") and "plain-access" not in raw_access
    assert raw_refresh.startswith("enc:")

    loaded = store.read()
    assert loaded.access_token == "plain-access"
    assert loaded.refresh_token == "plain-refresh"


def test_encrypted_db_without_key_raises(tmp_path):
    store = TokenStore(str(tmp_path / "tokens.db"), encryption_key=Fernet.generate_key().decode())
    store.write(make_row())

    plaintext_store = TokenStore(str(tmp_path / "tokens.db"))
    with pytest.raises(RuntimeError, match="no decryption key"):
        plaintext_store.read()


# ---- schwabdev compatibility sentinels ---------------------------------------


def test_schwabdev_tokens_loads_tokens_written_by_store(tmp_path):
    """Sentinel: schwabdev 4.x must transparently load what this store writes.

    Locked to schwabdev >=4,<5 via pyproject; if a future major changes the
    schema, this test fails before production does.
    """
    db = tmp_path / "tokens.db"
    store = TokenStore(str(db))
    issued = datetime.datetime.now(datetime.timezone.utc)
    store.write(make_row(issued, access_token="at-sentinel", refresh_token="rt-sentinel"))

    spy = AuthSpy()
    tokens = Tokens(
        app_key=APP_KEY,
        app_secret=APP_SECRET,
        callback_url=CALLBACK_URL,
        tokens_db=str(db),
        call_for_auth=spy,
        open_browser_for_auth=False,
    )
    assert tokens.access_token == "at-sentinel"
    assert tokens.refresh_token == "rt-sentinel"
    # Both issue timestamps parsed back, no interactive auth attempted.
    assert tokens._access_token_issued == issued
    assert tokens._refresh_token_issued == issued
    assert spy.calls == []


def test_schwabdev_tokens_on_empty_db_uses_injected_auth_callback(tmp_path):
    """Sentinel: with no row, schwabdev defers to call_for_auth instead of hanging
    on browser+stdin — the property this service relies on for lazy client builds."""
    db = tmp_path / "empty.db"
    TokenStore(str(db))  # create schema only

    spy = AuthSpy()
    tokens = Tokens(
        app_key=APP_KEY,
        app_secret=APP_SECRET,
        callback_url=CALLBACK_URL,
        tokens_db=str(db),
        call_for_auth=spy,
        open_browser_for_auth=False,
    )
    assert len(spy.calls) >= 1
    assert tokens.access_token is None
