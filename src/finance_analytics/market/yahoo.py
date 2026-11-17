"""Daily prices, splits and dividends from Yahoo Finance via yfinance (D-009).

- `auto_adjust=False`: Close is split-adjusted but NOT dividend-adjusted, because
  dividends are booked as cash from the broker data.
- London quotes in pence (GBp/GBX) are converted to GBP.
- Yahoo rate-limits per IP; requests back off and give up politely. Once a ticker gives up,
  the rest of the run is skipped instead of backing off again for every ticker.
- A closed instrument is fetched only up to the last day it is needed (D-042), so later
  updates send no request for it.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable, Mapping
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


NO_QUOTES_PREFIX = "Brak notowań w Yahoo dla"
NO_QUOTES_RETRY_DAYS = 7  # a ticker Yahoo does not know is not asked again for this long (D-039)
_NO_QUOTES_MARKERS = ("possibly delisted", "no timezone found", "no data found", "no price data found")


def no_quotes_message(ticker: str) -> str:
    return (f"{NO_QUOTES_PREFIX} {ticker} — Yahoo nie zna tego symbolu. Wpisz właściwy ticker w "
            "config/yahoo_tickers.yaml (np. ABC.DE: ABC.L) i zsynchronizuj dane.")


def _is_no_quotes(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _NO_QUOTES_MARKERS)


class YahooRateLimitError(YahooError):
    """Yahoo kept refusing requests after the retries; the rest of the run is skipped."""


Progress = Callable[[str, int, int], None]  # (ticker, done so far, total)


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
                    raise YahooRateLimitError(f"{ticker}: Yahoo rate limit, try again later") from exc
                self.sleep(5 * 2**attempt)
            except Exception as exc:  # unknown ticker, no data in range, network error
                if _is_no_quotes(exc):
                    raise YahooError(no_quotes_message(ticker)) from exc
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


def _recent_no_quotes(conn: sqlite3.Connection, ticker: str) -> str | None:
    """The stored "no quotes" error, while it is fresh and the ticker has never had a price."""
    row = conn.execute(
        "SELECT last_error, fetched_at, date_from > date_to FROM fetch_log WHERE source = 'yahoo' AND key = ?",
        (ticker,),
    ).fetchone()
    if not row or not row[0] or not row[0].startswith(NO_QUOTES_PREFIX) or not row[2]:
        return None
    age = datetime.now(UTC) - datetime.fromisoformat(row[1])
    return row[0] if age < timedelta(days=NO_QUOTES_RETRY_DAYS) else None


def update_prices(
    conn: sqlite3.Connection,
    needed: dict[str, date],
    today: date,
    *,
    client: PriceClient | None = None,
    until: Mapping[str, date] | None = None,
    progress: Progress | None = None,
) -> PriceReport:
    """Bring cached prices up to date for each ticker from its first needed day to today.

    `until` holds the last needed day of instruments no longer held (D-042); they are not
    fetched past it. `progress` is called before each ticker.
    """
    client = client or YahooClient()
    until = until or {}
    report = PriceReport()
    final_until = today - timedelta(days=1)
    rate_limited: str | None = None
    for done, (ticker, first_needed) in enumerate(sorted(needed.items())):
        if progress:
            progress(ticker, done, len(needed))
        start = first_needed - timedelta(days=7)
        known_bad = _recent_no_quotes(conn, ticker)
        if known_bad:
            report.errors[ticker] = known_bad
            continue
        end = min(today, until.get(ticker, today))
        covered = cache.coverage(conn, "yahoo", ticker)
        # Late corrections are re-read only while the range still grows; a closed ticker is then left alone.
        overlap = REFETCH_DAYS if covered is None or end > covered[1] else 0
        ranges = cache.missing_ranges(covered, start, end, overlap_days=overlap)
        written = 0
        try:
            if ranges and rate_limited:
                raise YahooError(f"{ticker}: skipped, {rate_limited} gave up on the Yahoo rate limit; try again later")
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
            if isinstance(exc, YahooRateLimitError):
                rate_limited = ticker
            conn.commit()
            cache.record_error(conn, "yahoo", ticker, str(exc))
            conn.commit()
            report.errors[ticker] = str(exc)
        report.fetched[ticker] = written
        row = conn.execute("SELECT currency FROM ticker_info WHERE ticker = ?", (ticker,)).fetchone()
        if row and row[0]:
            report.currencies[ticker] = row[0]
    return report
