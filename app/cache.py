"""SQLite cache for JARL membership lookups.

One row per callsign. We hit the cache before going to JARL so that repeated
queries (e.g. running the same ADI through again) don't re-hammer the
official site.

Schema mirrors Charter §3.1 #8: callsign / is_jarl_member / qsl_via /
raw_result / queried_at. The ``raw_result`` column stores JARL's exact
returned string so we can re-classify locally if our parser changes.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.jarl_client import JarlResult

DEFAULT_TTL_SECONDS = 30 * 24 * 3600

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jarl_lookups (
    callsign      TEXT PRIMARY KEY,
    is_member     TEXT NOT NULL CHECK (is_member IN ('yes', 'no', 'unknown')),
    qsl_via       TEXT NOT NULL DEFAULT '',
    raw_result    TEXT NOT NULL DEFAULT '',
    queried_at    INTEGER NOT NULL
);
"""


@dataclass(frozen=True)
class CachedEntry:
    callsign: str
    is_member: str
    qsl_via: str
    raw_result: str
    queried_at: int  # unix seconds


class JarlCache:
    """Thin SQLite wrapper. Connection per-call to stay thread-safe."""

    def __init__(self, path: Path | str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self.path = Path(path)
        self.ttl_seconds = ttl_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_fresh(self, callsign: str, now: int | None = None) -> CachedEntry | None:
        now = now if now is not None else int(time.time())
        cutoff = now - self.ttl_seconds
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT callsign, is_member, qsl_via, raw_result, queried_at "
                "FROM jarl_lookups WHERE callsign = ? AND queried_at >= ?",
                (callsign.upper(), cutoff),
            ).fetchone()
        if row is None:
            return None
        return CachedEntry(**dict(row))

    def get_many_fresh(self, callsigns: Iterable[str]) -> dict[str, CachedEntry]:
        cs_list = [c.upper() for c in callsigns]
        if not cs_list:
            return {}
        now = int(time.time())
        cutoff = now - self.ttl_seconds
        placeholders = ",".join("?" for _ in cs_list)
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT callsign, is_member, qsl_via, raw_result, queried_at "
                f"FROM jarl_lookups WHERE queried_at >= ? AND callsign IN ({placeholders})",
                (cutoff, *cs_list),
            ).fetchall()
        return {row["callsign"]: CachedEntry(**dict(row)) for row in rows}

    def put(self, result: JarlResult, now: int | None = None) -> None:
        """Store a real result.

        ⚠️ Per Charter §7.5: do NOT cache 'unknown'. An unknown means we don't
        actually know — caching it would lock in a non-answer for 30 days.
        """
        if result.is_member == "unknown":
            return
        now = now if now is not None else int(time.time())
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO jarl_lookups (callsign, is_member, qsl_via, raw_result, queried_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(callsign) DO UPDATE SET "
                "  is_member = excluded.is_member, "
                "  qsl_via = excluded.qsl_via, "
                "  raw_result = excluded.raw_result, "
                "  queried_at = excluded.queried_at",
                (result.callsign.upper(), result.is_member, result.qsl_via, result.raw_result, now),
            )
            conn.commit()

    def put_many(self, results: Iterable[JarlResult]) -> int:
        now = int(time.time())
        n = 0
        for r in results:
            self.put(r, now=now)
            if r.is_member != "unknown":
                n += 1
        return n

    def stats(self) -> dict[str, int]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT "
                "  COUNT(*) AS total, "
                "  SUM(CASE WHEN is_member = 'yes' THEN 1 ELSE 0 END) AS yes, "
                "  SUM(CASE WHEN is_member = 'no' THEN 1 ELSE 0 END) AS no "
                "FROM jarl_lookups"
            ).fetchone()
        return {"total": row["total"] or 0, "yes": row["yes"] or 0, "no": row["no"] or 0}
