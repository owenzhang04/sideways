"""SQLite key-value cache with per-entry TTL, for upstream API responses.

Upstreams are free community services (MusicBrainz asks for 1 req/s), so every
response is cached. Values are JSON.
"""

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

DAY = 86_400


class Cache:
    def __init__(self, path: Path | str) -> None:
        if isinstance(path, Path):
            path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS kv "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL, expires REAL NOT NULL)"
            )
            self._db.commit()

    def get(self, key: str) -> Any | None:
        with self._lock:
            row = self._db.execute("SELECT value, expires FROM kv WHERE key = ?", (key,)).fetchone()
        if row is None or row[1] < time.time():
            return None
        return json.loads(row[0])

    def set(self, key: str, value: Any, ttl: float) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO kv (key, value, expires) VALUES (?, ?, ?)",
                (key, json.dumps(value), time.time() + ttl),
            )
            self._db.commit()

    def purge_expired(self) -> int:
        with self._lock:
            cur = self._db.execute("DELETE FROM kv WHERE expires < ?", (time.time(),))
            self._db.commit()
            return cur.rowcount

    def close(self) -> None:
        with self._lock:
            self._db.close()
