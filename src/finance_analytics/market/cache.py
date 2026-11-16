"""Bookkeeping of which date ranges are already cached (table fetch_log)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta


def coverage(conn: sqlite3.Connection, source: str, key: str) -> tuple[date, date] | None:
    row = conn.execute(
        "SELECT date_from, date_to FROM fetch_log WHERE source = ? AND key = ?", (source, key)
    ).fetchone()
    if row is None or row[0] > row[1]:  # no row, or an error-only placeholder
        return None
    return date.fromisoformat(row[0]), date.fromisoformat(row[1])


def missing_ranges(
    covered: tuple[date, date] | None, start: date, end: date, *, overlap_days: int = 0
) -> list[tuple[date, date]]:
    """Date ranges within [start, end] not yet covered.

    `overlap_days` re-fetches the last few covered days, so late corrections at the
    source replace what was cached.
    """
    if start > end:
        return []
    if covered is None:
        return [(start, end)]
    first, last = covered
    ranges = []
    if start < first:
        ranges.append((start, min(end, first - timedelta(days=1))))
    tail_from = max(start, last + timedelta(days=1) - timedelta(days=overlap_days))
    if tail_from <= end:
        ranges.append((tail_from, end))
    return ranges


def record(
    conn: sqlite3.Connection,
    source: str,
    key: str,
    start: date,
    end: date,
    *,
    error: str | None = None,
) -> None:
    """Extend the covered range of (source, key) with [start, end]."""
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    covered = coverage(conn, source, key)
    if covered is not None:
        start, end = min(start, covered[0]), max(end, covered[1])
    conn.execute(
        "INSERT INTO fetch_log (source, key, date_from, date_to, fetched_at, last_error) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (source, key) DO UPDATE SET date_from = excluded.date_from, date_to = excluded.date_to, "
        "fetched_at = excluded.fetched_at, last_error = excluded.last_error",
        (source, key, start.isoformat(), end.isoformat(), now, error),
    )


def record_error(conn: sqlite3.Connection, source: str, key: str, error: str) -> None:
    """Remember a failure without extending the covered range."""
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    updated = conn.execute(
        "UPDATE fetch_log SET last_error = ?, fetched_at = ? WHERE source = ? AND key = ?",
        (error, now, source, key),
    ).rowcount
    if not updated:
        # Placeholder row with an empty range (from > to) that marks the error only.
        conn.execute(
            "INSERT INTO fetch_log (source, key, date_from, date_to, fetched_at, last_error) "
            "VALUES (?, ?, '9999-12-31', '0001-01-01', ?, ?)",
            (source, key, now, error),
        )
