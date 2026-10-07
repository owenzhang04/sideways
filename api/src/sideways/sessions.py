"""Spotify login sessions and pending OAuth states, in SQLite.

The browser holds a random opaque token; the database stores only its SHA-256, so a
copy of the database can't be replayed as a cookie.
"""

import hashlib
import secrets
import sqlite3
import threading
import time
from pathlib import Path

from sideways.sources.spotify import Token

SESSION_TTL = 30 * 86_400
OAUTH_STATE_TTL = 600


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class Sessions:
    def __init__(self, path: Path | str) -> None:
        if isinstance(path, Path):
            path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, access TEXT NOT NULL, refresh TEXT NOT NULL,
                    expires_at REAL NOT NULL, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oauth_states (
                    state TEXT PRIMARY KEY, verifier TEXT NOT NULL, created REAL NOT NULL
                );
                """
            )

    def create(self, token: Token) -> str:
        raw = secrets.token_urlsafe(32)
        with self._lock:
            self._db.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                (_digest(raw), token.access, token.refresh, token.expires_at, time.time()),
            )
            self._db.commit()
        return raw

    def get(self, raw: str | None) -> Token | None:
        if not raw:
            return None
        with self._lock:
            row = self._db.execute(
                "SELECT access, refresh, expires_at, created FROM sessions WHERE id = ?",
                (_digest(raw),),
            ).fetchone()
        if row is None or row[3] + SESSION_TTL < time.time():
            return None
        return Token(access=row[0], refresh=row[1], expires_at=row[2])

    def update(self, raw: str, token: Token) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE sessions SET access = ?, refresh = ?, expires_at = ? WHERE id = ?",
                (token.access, token.refresh, token.expires_at, _digest(raw)),
            )
            self._db.commit()

    def delete(self, raw: str | None) -> None:
        if not raw:
            return
        with self._lock:
            self._db.execute("DELETE FROM sessions WHERE id = ?", (_digest(raw),))
            self._db.commit()

    def save_state(self, state: str, verifier: str) -> None:
        with self._lock:
            self._db.execute(
                "DELETE FROM oauth_states WHERE created < ?", (time.time() - OAUTH_STATE_TTL,)
            )
            self._db.execute(
                "INSERT INTO oauth_states VALUES (?, ?, ?)", (state, verifier, time.time())
            )
            self._db.commit()

    def pop_state(self, state: str) -> str | None:
        """Single use: the verifier is returned once, then deleted."""
        with self._lock:
            row = self._db.execute(
                "SELECT verifier, created FROM oauth_states WHERE state = ?", (state,)
            ).fetchone()
            self._db.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
            self._db.commit()
        if row is None or row[1] + OAUTH_STATE_TTL < time.time():
            return None
        return row[0]
