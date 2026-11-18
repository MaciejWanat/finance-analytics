"""Intraday quotes for the "1D" range (D-070).

Two sources fill `intraday_quotes`:
- 5-minute bars from Yahoo for the held tickers and FX pairs, pre-market and post-market included, over the last
  5 days (so Monday morning still has Friday's last price). Online, the live feed (`market.feed`) fetches them
  when it starts and every 15 minutes while some market trades; offline only on an explicit request (the
  "Pobierz notowania z dziś" button, D-031);
- every live quote (`live.store_quotes`), at most one row per ticker and minute, so the chart reaches "now".

Rows older than 10 days are dropped.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

import pandas as pd

from finance_analytics.config import Settings
from finance_analytics.db import connect, migrate
from finance_analytics.market.network import require_online
from finance_analytics.market.yahoo import MINOR_UNITS, YahooRateLimitError

KEEP = timedelta(days=10)
WORKERS = 4

Bar = tuple[datetime, float]  # (moment in UTC, price in the main currency unit)


class BarClient(Protocol):
    def bars(self, ticker: str) -> list[Bar]: ...


class YahooBarClient:
    """5-minute bars of the last 5 days, pre-market and post-market included."""

    def bars(self, ticker: str) -> list[Bar]:
        import yfinance as yf
        from yfinance.exceptions import YFRateLimitError

        try:
            handle = yf.Ticker(ticker)
            frame = handle.history(period="5d", interval="5m", prepost=True, auto_adjust=False)
            meta = handle.history_metadata or {}
        except YFRateLimitError as exc:
            raise YahooRateLimitError(f"{ticker}: Yahoo rate limit") from exc
        if frame is None or frame.empty or "Close" not in frame:
            return []
        divisor = MINOR_UNITS.get(meta.get("currency"), (None, 1.0))[1]
        closes = frame["Close"].dropna()
        return [(moment.to_pydatetime().astimezone(UTC), float(price) / divisor) for moment, price in closes.items()]


@dataclass
class IntradayReport:
    tickers: int = 0
    rows: int = 0
    missing: list[str] = field(default_factory=list)


def _minute(moment: datetime) -> str:
    return moment.astimezone(UTC).replace(second=0, microsecond=0).isoformat()


def store_bars(conn: sqlite3.Connection, rows: Iterable[tuple[str, datetime, float]], now: datetime) -> int:
    """Save (ticker, moment, price) rows; the newest price wins within a minute. Drops rows older than 10 days."""
    data = [(ticker, _minute(moment), price) for ticker, moment, price in rows if price == price and price > 0]
    conn.executemany("INSERT OR REPLACE INTO intraday_quotes (ticker, ts, price) VALUES (?, ?, ?)", data)
    conn.execute("DELETE FROM intraday_quotes WHERE ts < ?", (_minute(now - KEEP),))
    conn.commit()
    return len(data)


def update_intraday(
    settings: Settings,
    symbols: list[str],
    *,
    manual: bool = False,
    client: BarClient | None = None,
    now: datetime | None = None,
) -> IntradayReport:
    """Fetch the 5-minute bars of `symbols`. Automatic callers need online mode; `manual=True` is the user's
    explicit request and works offline too (D-031). Raises `YahooRateLimitError` when Yahoo refuses."""
    if not manual:
        require_online(settings)
    now = now or datetime.now(UTC)
    client = client or YahooBarClient()
    if not symbols:
        return IntradayReport()

    def one(ticker: str) -> tuple[str, list[Bar] | None, Exception | None]:
        try:
            return ticker, client.bars(ticker), None
        except Exception as exc:  # one bad ticker must not stop the others
            return ticker, None, exc

    with ThreadPoolExecutor(max_workers=min(WORKERS, len(symbols))) as pool:
        results = list(pool.map(one, symbols))
    limited = next((exc for _, _, exc in results if isinstance(exc, YahooRateLimitError)), None)
    rows = [(ticker, moment, price) for ticker, bars, _ in results for moment, price in bars or []]
    with closing(connect(settings.db_path)) as conn:
        migrate(conn)
        stored = store_bars(conn, rows, now)
    if limited is not None:
        raise limited
    missing = sorted(ticker for ticker, bars, _ in results if not bars)
    return IntradayReport(tickers=len(symbols) - len(missing), rows=stored, missing=missing)


def read_intraday(db_path, start: datetime, end: datetime) -> pd.DataFrame:
    """Quotes from 5 days before `start` (the last price before a market opens) to `end`, as a wide frame:
    UTC moments x tickers. Empty when nothing is saved."""
    with closing(sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)) as conn:
        try:
            frame = pd.read_sql_query(
                "SELECT ticker, ts, price FROM intraday_quotes WHERE ts >= ? AND ts <= ?", conn,
                params=(_minute(start - timedelta(days=5)), end.astimezone(UTC).isoformat()),
            )
        except (sqlite3.OperationalError, pd.errors.DatabaseError):  # table not there yet
            return pd.DataFrame()
    if frame.empty:
        return pd.DataFrame()
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    return frame.pivot_table(index="ts", columns="ticker", values="price", aggfunc="last").sort_index()


def coverage(db_path, start: datetime, end: datetime) -> datetime | None:
    """The newest saved quote within [start, end], or None: tells the page whether 1D has data."""
    with closing(sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)) as conn:
        try:
            value = conn.execute(
                "SELECT MAX(ts) FROM intraday_quotes WHERE ts >= ? AND ts <= ?",
                (_minute(start), end.astimezone(UTC).isoformat()),
            ).fetchone()[0]
        except sqlite3.OperationalError:
            return None
    return datetime.fromisoformat(value) if value else None
