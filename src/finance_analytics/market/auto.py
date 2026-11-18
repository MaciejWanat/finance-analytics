"""Online mode: decide when the daily market update (D-017) should run by itself (D-021).

It runs when the last update is older than 6 hours, once more after NBP publishes
the day's table (business days, 11:45-12:15 Polish time), and once more shortly after each
US session closes, so the day's closing prices are final for the "Dzisiaj" tile (D-067).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, time, timedelta

from finance_analytics.config import Settings
from finance_analytics.market.hours import last_close
from finance_analytics.market.network import is_online
from finance_analytics.market.update import MarketReport, update_market

MAX_AGE = timedelta(hours=6)
NBP_READY = time(12, 20)  # local time, after the publication window
US_CLOSE_DELAY = timedelta(minutes=15)  # Yahoo's daily bar is final a few minutes after the close


def last_update(db_path) -> datetime | None:
    with closing(sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)) as conn:
        try:
            value = conn.execute("SELECT MAX(fetched_at) FROM fetch_log").fetchone()[0]
        except sqlite3.OperationalError:
            return None
    return datetime.fromisoformat(value) if value else None


def daily_update_due(db_path, now_local: datetime) -> bool:
    """`now_local` must be timezone-aware (local time); fetch_log stores UTC."""
    previous = last_update(db_path)
    if previous is None:
        return True
    if now_local - previous >= MAX_AGE:
        return True
    if previous < last_close(now_local - US_CLOSE_DELAY) + US_CLOSE_DELAY:
        return True
    nbp_time = datetime.combine(now_local.date(), NBP_READY, tzinfo=now_local.tzinfo)
    return now_local.weekday() < 5 and now_local >= nbp_time > previous


def maybe_update_market(settings: Settings, *, now_local: datetime | None = None) -> MarketReport | None:
    """Run the incremental market update if online and due; otherwise do nothing."""
    if not is_online(settings) or not settings.db_path.exists():
        return None
    now_local = now_local or datetime.now(UTC).astimezone()
    if not daily_update_due(settings.db_path, now_local):
        return None
    return update_market(settings)
