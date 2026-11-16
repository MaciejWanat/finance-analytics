"""Online mode: live quotes polled every few minutes (D-021).

One pass fetches the latest price of every held ticker plus market FX rates
(`USDPLN=X` etc.). They are stored in `live_quotes` and used only to value the
current day; history keeps using daily closes and NBP rates.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from finance_analytics.config import Settings
from finance_analytics.db import connect, migrate
from finance_analytics.market.network import require_online
from finance_analytics.market.yahoo import MINOR_UNITS
from finance_analytics.preferences import load_preferences

FX_TICKER = "{currency}PLN=X"

Quote = tuple[float, str | None]  # (price, currency)


class QuoteClient(Protocol):
    def last_prices(self, tickers: Iterable[str]) -> dict[str, Quote]: ...


class YahooQuoteClient:
    """Latest price per ticker via yfinance `fast_info` (one small request per ticker)."""

    def last_prices(self, tickers: Iterable[str]) -> dict[str, Quote]:
        import yfinance as yf

        quotes: dict[str, Quote] = {}
        for ticker in tickers:
            try:
                info = yf.Ticker(ticker).fast_info
                price, currency = info.last_price, info.currency
            except Exception:  # one bad ticker must not stop the others
                continue
            if price is None or price != price:  # None or NaN
                continue
            if currency in MINOR_UNITS:
                currency, divisor = MINOR_UNITS[currency]
                price = price / divisor
            quotes[ticker] = (float(price), currency)
        return quotes


@dataclass
class LiveReport:
    updated: bool
    quotes: int = 0
    missing: list[str] = field(default_factory=list)
    reason: str | None = None  # why nothing was fetched


def held_tickers(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT i.yahoo_ticker FROM positions p JOIN instruments i ON i.id = p.instrument_id "
        "WHERE p.close_time IS NULL AND i.yahoo_ticker IS NOT NULL ORDER BY 1"
    ).fetchall()
    return [r[0] for r in rows]


def needed_fx(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT currency FROM ticker_info WHERE currency IS NOT NULL UNION SELECT currency FROM accounts"
    ).fetchall()
    return sorted({r[0] for r in rows} - {"PLN"})


def last_fetch(conn: sqlite3.Connection) -> datetime | None:
    value = conn.execute("SELECT MAX(fetched_at) FROM live_quotes").fetchone()[0]
    return datetime.fromisoformat(value) if value else None


def update_live(
    settings: Settings,
    *,
    now: datetime | None = None,
    client: QuoteClient | None = None,
    force: bool = False,
) -> LiveReport:
    """Poll live quotes if online and the refresh interval has passed (weekdays only)."""
    require_online(settings)
    now = now or datetime.now(UTC)
    interval = timedelta(minutes=load_preferences(settings).refresh_minutes)
    with closing(connect(settings.db_path)) as conn:
        migrate(conn)
        previous = last_fetch(conn)
        if not force and previous and now - previous < interval:
            return LiveReport(updated=False, reason="fresh")
        if not force and now.weekday() >= 5:
            return LiveReport(updated=False, reason="weekend")
        tickers = held_tickers(conn)
        fx = [FX_TICKER.format(currency=c) for c in needed_fx(conn)]
        if not tickers and not fx:
            return LiveReport(updated=False, reason="nothing held")
        quotes = (client or YahooQuoteClient()).last_prices([*tickers, *fx])
        stamp = now.replace(microsecond=0).isoformat()
        conn.executemany(
            "INSERT OR REPLACE INTO live_quotes (ticker, price, currency, fetched_at) VALUES (?, ?, ?, ?)",
            [(t, price, currency, stamp) for t, (price, currency) in quotes.items()],
        )
        conn.commit()
    return LiveReport(updated=True, quotes=len(quotes), missing=sorted(set(tickers + fx) - set(quotes)))


def read_live(db_path, max_age: timedelta, now: datetime | None = None) -> tuple[dict, dict, datetime | None]:
    """Fresh live quotes as ({ticker: price}, {currency: PLN per unit}, fetched_at)."""
    now = now or datetime.now(UTC)
    with closing(sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)) as conn:
        try:
            rows = conn.execute("SELECT ticker, price, fetched_at FROM live_quotes").fetchall()
        except sqlite3.OperationalError:  # table not there yet
            return {}, {}, None
    prices, fx, newest = {}, {}, None
    for ticker, price, fetched_at in rows:
        moment = datetime.fromisoformat(fetched_at)
        if now - moment > max_age:
            continue
        newest = max(newest, moment) if newest else moment
        if ticker.endswith("PLN=X"):
            fx[ticker.removesuffix("PLN=X")] = price
        else:
            prices[ticker] = price
    return prices, fx, newest
