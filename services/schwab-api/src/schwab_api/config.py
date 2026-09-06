"""Service configuration from ``FA_SCHWAB_*`` environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

ENV_PREFIX = "FA_SCHWAB_"

DEFAULT_CALLBACK_URL = "https://127.0.0.1"
DEFAULT_TOKENS_DB = "~/.schwabdev/tokens.db"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8010
DEFAULT_KEEPALIVE_INTERVAL_HOURS = 12.0


@dataclass(frozen=True)
class Config:
    """Immutable service configuration; built once at startup."""

    app_key: str | None
    app_secret: str | None
    callback_url: str
    tokens_db: str
    tokens_encryption: str | None
    host: str
    port: int
    api_key: str | None
    keepalive_interval_hours: float

    @property
    def credentials_configured(self) -> bool:
        return bool(self.app_key and self.app_secret)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        """Build config from environment; raises ``ValueError`` on invalid values."""
        env = os.environ if env is None else env

        def get(name: str) -> str | None:
            return env.get(f"{ENV_PREFIX}{name}") or None

        app_key = get("APP_KEY")
        app_secret = get("APP_SECRET")
        if bool(app_key) != bool(app_secret):
            raise ValueError(f"{ENV_PREFIX}APP_KEY and {ENV_PREFIX}APP_SECRET must be set together")

        callback_url = get("CALLBACK_URL") or DEFAULT_CALLBACK_URL
        if not callback_url.startswith("https"):
            raise ValueError(f"{ENV_PREFIX}CALLBACK_URL must start with https")
        if callback_url.endswith("/"):
            raise ValueError(f"{ENV_PREFIX}CALLBACK_URL must not end with '/'")

        port_raw = get("PORT")
        port = int(port_raw) if port_raw else DEFAULT_PORT

        interval_raw = get("KEEPALIVE_INTERVAL_HOURS")
        try:
            interval = float(interval_raw) if interval_raw else DEFAULT_KEEPALIVE_INTERVAL_HOURS
        except ValueError as e:
            raise ValueError(f"{ENV_PREFIX}KEEPALIVE_INTERVAL_HOURS must be a number") from e
        if interval <= 0:
            raise ValueError(f"{ENV_PREFIX}KEEPALIVE_INTERVAL_HOURS must be > 0")

        return cls(
            app_key=app_key,
            app_secret=app_secret,
            callback_url=callback_url,
            tokens_db=get("TOKENS_DB") or DEFAULT_TOKENS_DB,
            tokens_encryption=get("TOKENS_ENCRYPTION"),
            host=get("HOST") or DEFAULT_HOST,
            port=port,
            api_key=get("API_KEY"),
            keepalive_interval_hours=interval,
        )
