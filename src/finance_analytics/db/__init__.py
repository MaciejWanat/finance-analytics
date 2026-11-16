"""SQLite access: plain sqlite3 plus numbered SQL migrations (D-003)."""

from finance_analytics.db.connection import connect
from finance_analytics.db.migrate import migrate

__all__ = ["connect", "migrate"]
