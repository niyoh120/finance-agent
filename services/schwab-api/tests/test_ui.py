"""Authorization UI page rendering and its integration with the auth endpoints."""

from __future__ import annotations

import datetime

from fastapi.testclient import TestClient
from schwab_api.main import create_app
from schwab_fakes import make_config, make_row


def test_index_renders_single_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    html = response.text
    # All functional pieces of the zero-build page are present.
    assert "Schwab API 授权管理" in html
    assert 'fetch("/api/v1/status")' in html
    assert 'fetch("/api/v1/auth/start"' in html
    assert 'fetch("/api/v1/auth/callback"' in html
    assert "Ready For Use" in html  # schwabdev-style troubleshooting hints
    assert "30 秒内有效" in html


def test_index_excluded_from_api_key_gate(tmp_path):
    from schwab_api.store import TokenStore

    config = make_config(api_key="sekrit")
    store = TokenStore(str(tmp_path / "tokens.db"))
    with TestClient(create_app(config=config, store=store)) as c:
        assert c.get("/").status_code == 200  # UI must load without a key


def test_ui_flow_status_then_auth_endpoints(client, store):
    """The exact sequence the page's JS performs works against the real routers."""
    # 1. initial status: unauthenticated
    status = client.get("/api/v1/status").json()
    assert status["authenticated"] is False

    # 2. start -> authorize URL (the page would open it in a new tab)
    start = client.post("/api/v1/auth/start").json()
    assert start["authorize_url"].startswith("https://api.schwabapi.com/v1/oauth/authorize")

    # 3. after pasting the callback URL, the page re-fetches status
    store.write(make_row(issued=datetime.datetime.now(datetime.timezone.utc)))
    status = client.get("/api/v1/status").json()
    assert status["authenticated"] is True
    assert status["access_token_ttl_seconds"] > 0
