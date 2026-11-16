"""Daily prices, splits and dividends from Yahoo Finance via yfinance (D-009).

- `auto_adjust=False`: Close is split-adjusted but NOT dividend-adjusted, because
  dividends are booked as cash from the broker data.
- London quotes in pence (GBp/GBX) are converted to GBP.
- Yahoo rate-limits per IP; requests back off and give up politely.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from finance_analytics.market import cache

MINOR_UNITS = {"GBp": ("GBP", 100.0), "GBX": ("GBP", 100.0), "ILA": ("ILS", 100.0), "ZAc": ("ZAR", 100.0)}
REFETCH_DAYS = 5  # re-read the last days on each update to pick up late corrections


@dataclass
class History:
    prices: list[tuple[date, float]] = field(default_factory=list)
    splits: list[tuple[date, float]] = field(default_factory=list)
    dividends: list[tuple[date, float]] = field(default_factory=list)
    currency: str | None = None
    name: str | None = None
    exchange: str | None = None


class PriceClient(Protocol):
    def history(self, ticker: str, start: date, end: date) -> History: ...


class YahooError(RuntimeError):
    pass


class YahooClient:
    """Thin wrapper around yfinance; the only place that imports it."""

    def __init__(self, retries: int = 3, sleep: Callable[[float], None] = time.sleep) -> None:
        self.retries, self.sleep = retries, sleep

    def history(self, ticker: str, start: date, end: date) -> History:
        import yfinance as yf
        from yfinance.exceptions import YFPricesMissingError, YFRateLimitError

        for attempt in range(self.retries + 1):
            try:
                handle = yf.Ticker(ticker)
                frame = handle.history(
                    start=start.isoformat(),
                    end=(end + timedelta(days=1)).isoformat(),  # yfinance end is exclusive
                    interval="1d",
                    auto_adjust=False,
                    actions=True,
                    raise_errors=True,
                )
                meta = handle.history_metadata or {}
                break
            except YFPricesMissingError:
                return History()  # no trading days in the range (weekend, holiday)
            except YFRateLimitError as exc:
                if attempt == self.retries:
                    raise YahooError(f"{ticker}: Yahoo rate limit, try again later") from exc
                self.sleep(5 * 2**attempt)
            except Exception as exc:  # unknown ticker, no data in range, network error
                raise YahooError(f"{ticker}: {exc}") from exc

        currency, divisor = meta.get("currency"), 1.0
        if currency in MINOR_UNITS:
            currency, divisor = MINOR_UNITS[currency]
        history = History(
            currency=currency,
            name=meta.get("longName") or meta.get("shortName"),
            exchange=meta.get("fullExchangeName") or meta.get("exchangeName"),
        )
        for moment, row in frame.iterrows():
            day = moment.date()
            if row.get("Close") == row.get("Close"):  # skip NaN
                history.prices.append((day, round(float(row["Close"]) / divisor, 6)))
            if row.get("Stock Splits"):
                history.splits.append((day, float(row["Stock Splits"])))
            if row.get("Dividends"):
                history.dividends.append((day, round(float(row["Dividends"]) / divisor, 6)))
        return history


@dataclass
class PriceReport:
    fetched: dict[str, int] = field(default_factory=dict)  # ticker -> price rows written
    errors: dict[str, str] = field(default_factory=dict)
    currencies: dict[str, str] = field(default_factory=dict)  # ticker -> price currency


def update_prices(
    conn: sqlite3.Connection,
    needed: dict[str, date],
    today: date,
    *,
    client: PriceClient | None = None,
) -> PriceReport:
    """Bring cached prices up to date for each ticker from its first needed day to today."""
    client = client or YahooClient()
    report = PriceReport()
    final_until = today - timedelta(days=1)
    for ticker, first_needed in sorted(needed.items()):
        start = first_needed - timedelta(days=7)
        ranges = cache.missing_ranges(cache.coverage(conn, "yahoo", ticker), start, today, overlap_days=REFETCH_DAYS)
        written = 0
        try:
            for range_start, range_end in ranges:
                history = client.history(ticker, range_start, range_end)
                if not history.prices:
                    cached = conn.execute("SELECT 1 FROM prices WHERE ticker = ? LIMIT 1", (ticker,)).fetchone()
                    if cached is None:
                        raise YahooError(f"{ticker}: no prices between {range_start} and {range_end}")
                    if range_start <= final_until:  # e.g. a weekend: nothing to add, but checked
                        cache.record(conn, "yahoo", ticker, range_start, min(range_end, final_until))
                    continue
                if history.currency is None:
                    raise YahooError(f"{ticker}: no currency in the response")
                conn.executemany(
                    "INSERT OR REPLACE INTO prices (ticker, date, close, currency) VALUES (?, ?, ?, ?)",
                    [(ticker, d.isoformat(), close, history.currency) for d, close in history.prices],
                )
                conn.executemany(
                    "INSERT OR REPLACE INTO corporate_actions (ticker, date, kind, value) VALUES (?, ?, 'SPLIT', ?)",
                    [(ticker, d.isoformat(), ratio) for d, ratio in history.splits],
                )
                conn.executemany(
                    "INSERT OR REPLACE INTO corporate_actions (ticker, date, kind, value) VALUES (?, ?, 'DIVIDEND', ?)",
                    [(ticker, d.isoformat(), value) for d, value in history.dividends],
                )
                conn.execute(
                    "INSERT OR REPLACE INTO ticker_info (ticker, currency, name, exchange, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (ticker, history.currency, history.name, history.exchange,
                     datetime.now(UTC).replace(microsecond=0).isoformat()),
                )
                written += len(history.prices)
                if range_start <= final_until:
                    cache.record(conn, "yahoo", ticker, range_start, min(range_end, final_until))
                conn.commit()
        except YahooError as exc:
            conn.commit()
            cache.record_error(conn, "yahoo", ticker, str(exc))
            conn.commit()
            report.errors[ticker] = str(exc)
        report.fetched[ticker] = written
        row = conn.execute("SELECT currency FROM ticker_info WHERE ticker = ?", (ticker,)).fetchone()
        if row and row[0]:
            report.currencies[ticker] = row[0]
    return report
