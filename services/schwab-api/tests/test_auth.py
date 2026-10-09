"""Auth endpoint behavior: start/callback/status/healthz."""

from __future__ import annotations

import datetime

import pytest
from fastapi.testclient import TestClient
from schwab_api import auth as auth_module
from schwab_api.main import create_app
from schwab_fakes import APP_KEY, CALLBACK_URL, make_config, make_row

TOKEN_RESPONSE = {
    "access_token": "at-new",
    "refresh_token": "rt-new",
    "id_token": "id-new",
    "expires_in": 1800,
    "token_type": "Bearer",
    "scope": "api",
}


@pytest.fixture()
def exchange_ok(monkeypatch):
    """Stub the token-endpoint POST; records the code that was exchanged."""
    calls: list[str] = []

    def fake(config, code):
        calls.append(code)
        return dict(TOKEN_RESPONSE)

    monkeypatch.setattr(auth_module, "request_tokens_by_authorization_code", fake)
    return calls


@pytest.fixture()
def exchange_fail(monkeypatch):
    def fake(config, code):
        raise auth_module.SchwabTokenError(401, '{"error":"invalid_authorization_code"}')

    monkeypatch.setattr(auth_module, "request_tokens_by_authorization_code", fake)


def test_healthz_ok_even_when_unauthenticated(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/healthz").json() == {"status": "ok"}


def test_status_unauthenticated(client):
    payload = client.get("/api/v1/status").json()
    assert payload["authenticated"] is False
    assert payload["credentials_configured"] is True
    assert payload["keepalive"]["last_error"] is None
    assert payload["keepalive"]["chain_dead"] is False
    assert payload["keepalive"]["seconds_since_refresh"] is None


def test_status_reports_real_expiry_times(client, store):
    """expires_at 字段必须是真实过期时刻（issued + TTL），修复前填的是 issued 本身。"""
    issued = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)
    store.write(make_row(issued=issued))
    payload = client.get("/api/v1/status").json()

    expected_access = (issued + datetime.timedelta(seconds=1800)).isoformat()
    expected_refresh = (issued + datetime.timedelta(days=7)).isoformat()
    assert payload["access_token_expires_at"] == expected_access
    assert payload["refresh_token_expires_at"] == expected_refresh
    assert 1140 <= payload["access_token_ttl_seconds"] <= 1200  # 30min TTL，已过 ~10min
    assert payload["keepalive"]["seconds_since_refresh"] is None  # 尚无成功轮换


# ---- POST /api/v1/auth/start -------------------------------------------------


def test_start_returns_authorize_url(client):
    response = client.post("/api/v1/auth/start")
    assert response.status_code == 200
    body = response.json()
    assert body["authorize_url"].startswith(auth_module.SCHWAB_OAUTH_AUTHORIZE_URL)
    assert f"client_id={APP_KEY}" in body["authorize_url"]
    assert "redirect_uri=https%3A%2F%2F127.0.0.1" in body["authorize_url"]


def test_start_rejects_when_authenticated_with_live_token(client, store):
    store.write(make_row())  # issued now -> alive
    response = client.post("/api/v1/auth/start")
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "already_authenticated"

    assert client.post("/api/v1/auth/start?force=true").status_code == 200


def test_start_allows_expired_tokens(client, store):
    expired = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=8)
    store.write(make_row(issued=expired))
    assert client.post("/api/v1/auth/start").status_code == 200


def test_start_bypasses_409_when_chain_dead(client, store):
    """链死亡时本地时间戳看 token 仍 "活着"，但必须放行重授权路径。"""
    store.write(make_row())  # issued now -> 本地判定 alive
    client.app.state.runtime.chain_dead = True

    response = client.post("/api/v1/auth/start")
    assert response.status_code == 200
    assert response.json()["chain_dead"] is True


def test_callback_resets_chain_dead(client, store, exchange_ok):
    """重新授权拿到全新链：chain_dead 与 last_error 必须复位，保活恢复轮换。"""
    store.write(make_row())
    runtime = client.app.state.runtime
    runtime.chain_dead = True
    runtime.last_error = "refresh token rejected by Schwab (chain dead): ..."

    response = client.post("/api/v1/auth/callback", json={"callback": f"{CALLBACK_URL}?code=FIX"})
    assert response.status_code == 200
    assert runtime.chain_dead is False
    assert runtime.last_error is None
    assert response.json()["keepalive"]["chain_dead"] is False


def test_start_requires_credentials(store):
    config = make_config(app_key=None, app_secret=None)
    with TestClient(create_app(config=config, store=store)) as client:
        response = client.post("/api/v1/auth/start")
    assert response.status_code == 503


# ---- POST /api/v1/auth/callback ----------------------------------------------


def test_callback_exchanges_code_and_persists_tokens(client, store, exchange_ok):
    response = client.post("/api/v1/auth/callback", json={"callback": f"{CALLBACK_URL}?code=ABC123&session=xyz"})
    assert response.status_code == 200
    assert exchange_ok == ["ABC123"]

    assert exchange_ok[0] == "ABC123"
    row = store.read()
    assert row.access_token == "at-new"
    assert row.refresh_token == "rt-new"
    # Core invariant: both issue timestamps reset to now (7-day clock restarted).
    now = datetime.datetime.now(datetime.timezone.utc)
    assert abs((now - row.access_token_issued).total_seconds()) < 30
    assert abs((now - row.refresh_token_issued).total_seconds()) < 30

    status = response.json()
    assert status["authenticated"] is True
    assert status["refresh_token_expired"] is False


def test_callback_accepts_raw_code(client, exchange_ok):
    response = client.post("/api/v1/auth/callback", json={"callback": "RAW456"})
    assert response.status_code == 200
    assert exchange_ok == ["RAW456"]


def test_callback_rejects_unparseable_input(client, exchange_ok):
    response = client.post("/api/v1/auth/callback", json={"callback": f"{CALLBACK_URL}?session=only"})
    assert response.status_code == 422
    assert exchange_ok == []


def test_callback_passes_through_schwab_error(client, exchange_fail):
    response = client.post("/api/v1/auth/callback", json={"callback": "some-code"})
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["error"] == "token_exchange_failed"
    assert detail["schwab_status"] == 401
    assert detail["schwab_body"] == '{"error":"invalid_authorization_code"}'


# ---- GET /api/v1/auth/redirect (browser auto flow) ----------------------------


def test_get_redirect_auto_exchanges_code(client, store, exchange_ok):
    response = client.get("/api/v1/auth/redirect?code=GETCODE")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert exchange_ok == ["GETCODE"]
    assert store.read().access_token == "at-new"
    assert "授权成功" in response.text


def test_get_redirect_missing_code_shows_error_page(client, exchange_ok):
    response = client.get("/api/v1/auth/redirect")
    assert response.status_code == 200
    assert "授权失败" in response.text
    assert "code" in response.text
    assert exchange_ok == []


def test_get_redirect_exchange_failure_shows_schwab_error(client, exchange_fail):
    response = client.get("/api/v1/auth/redirect?code=BAD")
    assert "授权失败" in response.text
    assert "invalid_authorization_code" in response.text


def test_start_reports_auto_redirect_mode(config, store, client):
    config = make_config(callback_url="https://schwab.example.com/api/v1/auth/redirect")
    from fastapi.testclient import TestClient
    from schwab_api.main import create_app

    with TestClient(create_app(config=config, store=store)) as c:
        assert c.post("/api/v1/auth/start").json()["auto_redirect"] is True
    assert client.post("/api/v1/auth/start").json()["auto_redirect"] is False
