"""OAuth authorization-code flow and token-state endpoints.

The service performs the authorization-code exchange itself (instead of going
through schwabdev's interactive flow) so a headless container can be authorized
from the single-page UI: open the authorize URL, log in, paste the redirected
callback URL back within Schwab's 30-second code lifetime.
"""

from __future__ import annotations

import base64
import datetime
import logging
import urllib.parse
from datetime import timedelta
from typing import TYPE_CHECKING

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .store import TokenRow, now_utc

if TYPE_CHECKING:
    from .client import ClientManager
    from .config import Config
    from .keepalive import RuntimeState
    from .store import TokenStore

logger = logging.getLogger(__name__)

SCHWAB_OAUTH_TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
SCHWAB_OAUTH_AUTHORIZE_URL = "https://api.schwabapi.com/v1/oauth/authorize"

#: Schwab hard-expires refresh tokens 7 days after issue; rotation renews the window.
REFRESH_TOKEN_TTL = timedelta(days=7)
#: Authorization codes from the authorize redirect live for 30 seconds.
AUTHORIZATION_CODE_TTL_SECONDS = 30
TOKEN_HTTP_TIMEOUT_SECONDS = 30


class SchwabTokenError(Exception):
    """The Schwab OAuth token endpoint rejected a request; body is passed through."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"schwab oauth token endpoint returned {status_code}: {body}")


# ---- OAuth helpers (kept transport-level so tests can stub them) -------------


def _post_token_form(config: "Config", data: dict) -> requests.Response:
    basic = base64.b64encode(f"{config.app_key}:{config.app_secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    return requests.post(SCHWAB_OAUTH_TOKEN_URL, headers=headers, data=data, timeout=TOKEN_HTTP_TIMEOUT_SECONDS)


def build_authorize_url(config: "Config") -> str:
    """Login URL the user opens in a browser; matches schwabdev's URL exactly."""
    query = urllib.parse.urlencode({"client_id": config.app_key, "redirect_uri": config.callback_url})
    return f"{SCHWAB_OAUTH_AUTHORIZE_URL}?{query}"


def extract_authorization_code(callback: str) -> str | None:
    """Accept the full redirected callback URL or a raw authorization code."""
    value = callback.strip()
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme:
        return urllib.parse.parse_qs(parsed.query).get("code", [None])[0]
    code = urllib.parse.unquote(value)
    return code or None


def request_tokens_by_authorization_code(config: "Config", code: str) -> dict:
    response = _post_token_form(
        config,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.callback_url,
        },
    )
    if not response.ok:
        raise SchwabTokenError(response.status_code, response.text)
    return response.json()


def request_tokens_by_refresh_token(config: "Config", refresh_token: str) -> dict:
    """Used by the keepalive loop (run in a worker thread, it blocks)."""
    response = _post_token_form(config, {"grant_type": "refresh_token", "refresh_token": refresh_token})
    if not response.ok:
        raise SchwabTokenError(response.status_code, response.text)
    return response.json()


# ---- shared status payload ---------------------------------------------------


def refresh_token_alive(row: TokenRow, now: datetime.datetime | None = None) -> bool:
    now = now or now_utc()
    return row.refresh_token_issued + REFRESH_TOKEN_TTL > now


def status_payload(config: "Config", store: "TokenStore", runtime: "RuntimeState | None") -> dict:
    """Token/keepalive state for ``GET /api/v1/status`` and the auth UI."""
    now = now_utc()
    payload: dict = {
        "authenticated": False,
        "credentials_configured": config.credentials_configured,
        "callback_url": config.callback_url,
        "keepalive": {
            "interval_hours": config.keepalive_interval_hours,
            "last_refresh": runtime.last_refresh.isoformat() if runtime and runtime.last_refresh else None,
            "last_error": runtime.last_error if runtime else None,
        },
    }
    try:
        row = store.read()
    except Exception as e:  # noqa: BLE001 - status must report, not fail
        payload["store_error"] = str(e)
        return payload
    if row is None:
        return payload
    access_ttl = (row.access_token_issued + timedelta(seconds=row.expires_in)) - now
    refresh_ttl = (row.refresh_token_issued + REFRESH_TOKEN_TTL) - now
    payload.update(
        authenticated=True,
        access_token_expires_at=row.access_token_issued.isoformat(),
        access_token_ttl_seconds=max(0, int(access_ttl.total_seconds())),
        refresh_token_expires_at=row.refresh_token_issued.isoformat(),
        refresh_token_ttl_seconds=max(0, int(refresh_ttl.total_seconds())),
        refresh_token_expired=not refresh_token_alive(row, now),
    )
    return payload


# ---- HTTP router -------------------------------------------------------------


class AuthCallbackRequest(BaseModel):
    callback: str = Field(
        min_length=1,
        description="Schwab 授权后浏览器跳转的完整回调 URL，或其中的原始 authorization code",
    )


def _deps(request: Request) -> tuple["Config", "TokenStore", "ClientManager", "RuntimeState | None"]:
    state = request.app.state
    return state.config, state.store, state.clients, getattr(state, "runtime", None)


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/start")
def start_authorization(request: Request, force: bool = False) -> dict:
    """Return the authorize URL; 409 when valid tokens already exist."""
    config, store, _, runtime = _deps(request)
    if not config.credentials_configured:
        raise HTTPException(status_code=503, detail="FA_SCHWAB_APP_KEY/APP_SECRET are not configured")
    row = store.read()
    if row is not None and not force and refresh_token_alive(row):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "already_authenticated",
                "hint": "tokens are valid; pass force=true to re-authorize",
                "status": status_payload(config, store, runtime),
            },
        )
    return {
        "authorize_url": build_authorize_url(config),
        "callback_url": config.callback_url,
        "auto_redirect": config.callback_url.rstrip("/").endswith("/api/v1/auth/redirect"),
        "code_ttl_seconds": AUTHORIZATION_CODE_TTL_SECONDS,
        "next": "POST /api/v1/auth/callback with the redirected URL",
    }


def exchange_and_store(config: "Config", store: "TokenStore", clients: "ClientManager", code: str) -> dict:
    """Exchange an authorization code for tokens and persist them.

    Shared by the manual paste flow (POST /api/v1/auth/callback) and the
    browser-redirect flow (GET /api/v1/auth/redirect).

    Raises:
        HTTPException: 422 unparseable, 502 when Schwab rejects the exchange.
    """
    if not code:
        raise HTTPException(status_code=422, detail="could not parse authorization code from callback")
    try:
        tokens = request_tokens_by_authorization_code(config, code)
    except SchwabTokenError as e:
        # Surface Schwab's own error body so the UI can show the real cause.
        raise HTTPException(
            status_code=502,
            detail={"error": "token_exchange_failed", "schwab_status": e.status_code, "schwab_body": e.body},
        ) from e
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail={"error": f"token exchange request failed: {e}"}) from e

    row = TokenRow.from_token_response(tokens, previous=store.read(), issued=now_utc())
    store.write(row)
    clients.reset()
    logger.info("authorization code exchanged; tokens stored")
    return {"access_token_expires_in": row.expires_in}


@router.post("/callback")
def complete_authorization(request: Request, body: AuthCallbackRequest) -> dict:
    """Manual flow: exchange a pasted callback URL / raw code, report status."""
    config, store, clients, runtime = _deps(request)
    code = extract_authorization_code(body.callback)
    exchange_and_store(config, store, clients, code)
    return status_payload(config, store, runtime)


@router.get("/redirect", include_in_schema=False)
def oauth_redirect(request: Request, code: str | None = None) -> "HTMLResponse":
    """Browser-redirect flow: Schwab lands here with ?code=...; exchange happens
    immediately and the page reports the outcome — no manual copy/paste.

    Point the callback URL registered at Schwab at this route (https, exact
    match, e.g. https://schwab.example.com/api/v1/auth/redirect).
    """
    config, store, clients, _ = _deps(request)
    try:
        exchange_and_store(config, store, clients, code)
        ok, detail = True, "token 已入库，本窗口可以关闭。"
    except HTTPException as e:
        ok, detail = False, _format_exchange_error(e)
    return HTMLResponse(_redirect_result_page(ok, detail))


def _format_exchange_error(e: HTTPException) -> str:
    detail = e.detail
    if isinstance(detail, dict) and detail.get("schwab_body"):
        return f"Schwab HTTP {detail.get('schwab_status', '?')}：{detail['schwab_body']}"
    return str(detail)


def _redirect_result_page(ok: bool, detail: str) -> str:
    title = "授权成功" if ok else "授权失败"
    color = "var(--green)" if ok else "var(--red)"
    detail_escaped = detail.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!DOCTYPE html>
<html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><title>{title}</title>
<style>body{{background:#0f1419;color:#e6edf3;font:15px/1.6 -apple-system,sans-serif;
display:grid;place-items:center;min-height:90vh;margin:0}}
.card{{background:#1a2129;border:1px solid #2c3644;border-radius:10px;padding:2rem;max-width:560px}}
h1{{color:{color};font-size:1.2rem;margin:0 0 .8rem}}pre{{white-space:pre-wrap;word-break:break-all;
color:#8b98a5;font-size:.85rem}}</style></head>
<body><div class=\"card\"><h1>{title}</h1><pre>{detail_escaped}</pre>
<p><a href=\"/\" style=\"color:#4c8dff\">返回授权管理页</a></p></div></body></html>"""
