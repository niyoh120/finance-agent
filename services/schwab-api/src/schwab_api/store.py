"""Token persistence in sqlite, schema-compatible with schwabdev 4.x.

This store is the single owner of Schwab OAuth tokens. The table layout matches
``schwabdev.tokens.Tokens`` exactly (table ``schwabdev``, 8 columns, one row), so a
``schwabdev.Client`` can be pointed at the same database file and load tokens we
wrote. Optional Fernet encryption mirrors schwabdev's ``enc:`` prefix convention.
"""

from __future__ import annotations

import datetime
import logging
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

_ENC_PREFIX = "enc:"
_UTC = datetime.timezone.utc

#: Matches schwabdev: 30s wait when another connection holds the write lock.
BUSY_TIMEOUT_SECONDS = 30
#: Schwab access tokens live 30 minutes; fallback when the response omits expires_in.
ACCESS_TOKEN_TTL_FALLBACK_SECONDS = 1800

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schwabdev (
    access_token_issued TEXT NOT NULL,
    refresh_token_issued TEXT NOT NULL,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    id_token TEXT NOT NULL,
    expires_in INTEGER,
    token_type TEXT,
    scope TEXT
);
"""

_SELECT_COLUMNS = (
    "access_token_issued, refresh_token_issued, access_token, refresh_token, id_token, expires_in, token_type, scope"
)


@dataclass(frozen=True)
class TokenRow:
    """One row of persisted OAuth tokens with parsed issue timestamps."""

    access_token_issued: datetime.datetime
    refresh_token_issued: datetime.datetime
    access_token: str
    refresh_token: str
    id_token: str
    expires_in: int
    token_type: str
    scope: str

    @classmethod
    def from_token_response(
        cls,
        payload: dict,
        previous: "TokenRow | None",
        issued: datetime.datetime,
    ) -> "TokenRow":
        """Build a row from a Schwab OAuth token response.

        ``issued`` is written to both issue timestamps: for authorization-code
        exchange and for keepalive rotation alike, the new refresh token is valid
        7 days from *now* — carrying over the old ``refresh_token_issued`` is the
        exact schwabdev bug this service exists to fix.

        ``previous`` supplies values absent from the response (Schwab always
        returns all fields, so this is defensive only).
        """
        access_token = payload.get("access_token") or (previous.access_token if previous else None)
        refresh_token = payload.get("refresh_token") or (previous.refresh_token if previous else None)
        if not access_token or not refresh_token:
            raise ValueError("token response is missing access_token/refresh_token")
        id_token = payload.get("id_token") or (previous.id_token if previous else "")
        expires_in = payload.get("expires_in") or ACCESS_TOKEN_TTL_FALLBACK_SECONDS
        return cls(
            access_token_issued=issued,
            refresh_token_issued=issued,
            access_token=access_token,
            refresh_token=refresh_token,
            id_token=id_token,
            expires_in=int(expires_in),
            token_type=payload.get("token_type") or "Bearer",
            scope=payload.get("scope") or "api",
        )


def now_utc() -> datetime.datetime:
    """Shared clock; UTC-aware everywhere."""
    return datetime.datetime.now(datetime.timezone.utc)


def _parse_dt(value: str) -> datetime.datetime:
    """Parse an ISO datetime string, assuming UTC when naive (same as schwabdev)."""
    dt = datetime.datetime.fromisoformat(value)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=_UTC)


class TokenStore:
    """sqlite-backed token store; opens a short-lived connection per operation."""

    def __init__(self, db_path: str, encryption_key: str | None = None) -> None:
        self._db_path = os.path.expanduser(db_path)
        # Mirrors schwabdev: keys up to 16 chars are ignored rather than trusted.
        self._cipher = Fernet(encryption_key) if encryption_key and len(encryption_key) > 16 else None
        db_dir = os.path.dirname(self._db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        with self._connect() as conn:
            conn.execute(_SCHEMA)
            conn.commit()

    @property
    def db_path(self) -> str:
        return self._db_path

    # ---- connection management -------------------------------------------

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path, timeout=BUSY_TIMEOUT_SECONDS)
        try:
            conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_SECONDS * 1000};")
            yield conn
        finally:
            conn.close()

    @contextmanager
    def exclusive(self) -> Iterator[sqlite3.Connection]:
        """Hold an EXCLUSIVE transaction across read + HTTP + write.

        Same pattern as schwabdev: holding the sqlite write lock throughout the
        network round-trip serializes refreshes across all processes sharing the
        token database. Commit happens only if the body completes; any exception
        rolls back and leaves the previous row intact.
        """
        with self._connect() as conn:
            conn.execute("BEGIN EXCLUSIVE")
            try:
                yield conn
            except BaseException:
                conn.rollback()
                raise
            else:
                conn.commit()

    # ---- row IO ----------------------------------------------------------

    def read(self) -> TokenRow | None:
        with self._connect() as conn:
            return self.read_conn(conn)

    def read_conn(self, conn: sqlite3.Connection) -> TokenRow | None:
        """Read inside an existing transaction (for use under ``exclusive()``)."""
        row = conn.execute(f"SELECT {_SELECT_COLUMNS} FROM schwabdev LIMIT 1").fetchone()
        if row is None:
            return None
        (at_issued, rt_issued, access_token, refresh_token, id_token, expires_in, token_type, scope) = row
        return TokenRow(
            access_token_issued=_parse_dt(at_issued),
            refresh_token_issued=_parse_dt(rt_issued),
            access_token=self._dec(access_token),
            refresh_token=self._dec(refresh_token),
            id_token=self._dec(id_token),
            expires_in=expires_in if expires_in is not None else ACCESS_TOKEN_TTL_FALLBACK_SECONDS,
            token_type=token_type,
            scope=scope,
        )

    def write(self, row: TokenRow) -> None:
        with self._connect() as conn:
            self.write_conn(conn, row)
            conn.commit()

    def write_conn(self, conn: sqlite3.Connection, row: TokenRow) -> None:
        """Upsert the single row inside an existing transaction."""
        conn.execute("DELETE FROM schwabdev")
        conn.execute(
            "INSERT INTO schwabdev "
            "(access_token_issued, refresh_token_issued, access_token, refresh_token, "
            "id_token, expires_in, token_type, scope) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row.access_token_issued.isoformat(),
                row.refresh_token_issued.isoformat(),
                self._enc(row.access_token),
                self._enc(row.refresh_token),
                self._enc(row.id_token),
                row.expires_in,
                row.token_type,
                row.scope,
            ),
        )

    # ---- encryption (schwabdev-compatible "enc:" prefix) ------------------

    def _enc(self, value: str) -> str:
        if not self._cipher:
            return value
        return _ENC_PREFIX + self._cipher.encrypt(value.encode()).decode()

    def _dec(self, value: str) -> str:
        if not value:
            return ""
        if not value.startswith(_ENC_PREFIX):
            return value
        if not self._cipher:
            raise RuntimeError("tokens are encrypted but no decryption key is configured")
        return self._cipher.decrypt(value[len(_ENC_PREFIX) :].encode()).decode()
