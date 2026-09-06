"""Lazy ``schwabdev.Client`` singleton.

The client is only constructed once tokens exist in the store, because
``schwabdev.Client`` triggers its interactive browser+stdin authorization flow
when the database has no tokens — fatal in a headless container. Interactive auth
is additionally blocked via ``call_on_auth`` so any unexpected expiry surfaces as
an exception instead of a hang.
"""

from __future__ import annotations

import logging
import threading

import schwabdev

from .config import Config
from .store import TokenStore

logger = logging.getLogger(__name__)

#:schwabdev default is 10s; option chains can be large/slow, so allow more.
SCHWAB_HTTP_TIMEOUT_SECONDS = 30


class NotAuthenticatedError(Exception):
    """No tokens in the store yet; the UI authorization flow must run first."""


class ClientBuildError(Exception):
    """Tokens exist but constructing the schwabdev client failed."""


def _forbid_interactive_auth(auth_url: str) -> str:
    raise RuntimeError(
        "interactive re-authorization is disabled in this service; "
        "use POST /api/v1/auth/start and POST /api/v1/auth/callback"
    )


class ClientManager:
    """Thread-safe lazy holder of the shared ``schwabdev.Client``."""

    def __init__(self, config: Config, store: TokenStore) -> None:
        self._config = config
        self._store = store
        self._lock = threading.Lock()
        self._client: schwabdev.Client | None = None

    def get(self) -> schwabdev.Client:
        """Return the shared client, building it on first use.

        Raises:
            NotAuthenticatedError: the store has no tokens yet.
            ClientBuildError: client construction failed despite tokens present.
        """
        with self._lock:
            if self._client is None:
                if self._store.read() is None:
                    raise NotAuthenticatedError("no Schwab tokens stored; authorize via POST /api/v1/auth/start")
                self._client = self._build()
            return self._client

    def reset(self) -> None:
        """Drop the cached client (after re-authorization); next get() rebuilds."""
        with self._lock:
            client, self._client = self._client, None
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001 - close() must never break the caller
                logger.warning("closing previous schwabdev client failed", exc_info=True)

    def _build(self) -> schwabdev.Client:
        try:
            return schwabdev.Client(
                app_key=self._config.app_key,
                app_secret=self._config.app_secret,
                callback_url=self._config.callback_url,
                tokens_db=self._config.tokens_db,
                encryption=self._config.tokens_encryption,
                timeout=SCHWAB_HTTP_TIMEOUT_SECONDS,
                call_on_auth=_forbid_interactive_auth,
                open_browser_for_auth=False,
            )
        except Exception as e:
            raise ClientBuildError(f"failed to build schwabdev client: {e}") from e
