"""Apply numbered SQL migrations (``NNNN_name.sql``) tracked by ``PRAGMA user_version``."""

from __future__ import annotations

import re
import sqlite3
from importlib import resources

_MIGRATION_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def available_migrations() -> list[tuple[int, str, str]]:
    """Return (version, filename, sql) sorted by version."""
    folder = resources.files("finance_analytics.db").joinpath("migrations")
    found = []
    for entry in folder.iterdir():
        match = _MIGRATION_RE.match(entry.name)
        if match:
            found.append((int(match.group(1)), entry.name, entry.read_text(encoding="utf-8")))
    found.sort()
    versions = [v for v, _, _ in found]
    if versions != list(range(1, len(versions) + 1)):
        raise RuntimeError(f"Migration numbers must be 1..N without gaps, got {versions}")
    return found


def current_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply pending migrations, each in its own transaction. Returns applied filenames."""
    applied = []
    version = current_version(conn)
    for number, name, sql in available_migrations():
        if number <= version:
            continue
        try:
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
        except sqlite3.Error as exc:
            if conn.in_transaction:
                conn.rollback()
            raise RuntimeError(f"Migration {name} failed: {exc}") from exc
        applied.append(name)
    return applied
