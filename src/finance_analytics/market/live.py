"""Online mode: live quotes for the current day (D-021, D-069).

Quotes come either from polling (`update_live`, run by `market.feed` every few seconds or minutes) or from
Yahoo's streaming connection (`market.feed`). Both store the latest price of every held ticker and market FX
rates (`USDPLN=X` etc.) in `live_quotes`. They are used only to value the current day; history keeps using
daily closes and NBP rates. US pre-market and post-market prices count too (D-069).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from finance_analytics.config import Settings
from finance_analytics.db import connect, migrate
from finance_analytics.market.intraday import store_bars
from finance_analytics.market.network import require_online
from finance_analytics.market.yahoo import MINOR_UNITS, YahooRateLimitError

FX_TICKER = "{currency}PLN=X"
POLL_WINDOW = timedelta(minutes=60)  # minute bars asked for: the last trade is in there while a market trades
POLL_WORKERS = 4  # parallel requests per poll; Yahoo rate-limits per IP, so not more

Quote = tuple[float, str | None]  # (price, currency)


class QuoteClient(Protocol):
    def last_prices(self, tickers: Iterable[str]) -> dict[str, Quote]: ...


def to_major_unit(price: float, currency: str | None) -> Quote:
    """London pence (GBp) and other minor units -> the main currency."""
    if currency in MINOR_UNITS:
        currency, divisor = MINOR_UNITS[currency]
        price = price / divisor
    return float(price), currency


def stream_quote(price: float, currency: str | None, reference: tuple[str | None, float | None]) -> Quote:
    """A streamed price in the main currency unit.

    The stream does not always say the currency: London quotes may come in pence without "GBp". `reference` is
    the symbol's (currency, last known price) in main units; a price about 100 times above it is in the minor unit.
    """
    if currency is not None:
        return to_major_unit(price, currency)
    known, last = reference
    divisor = next((d for minor, (major, d) in MINOR_UNITS.items() if major == known), None)
    if divisor and last and price / last > divisor / 3:
        return float(price) / divisor, known
    return float(price), known


def reference_prices(settings: Settings, symbols: Iterable[str]) -> dict[str, tuple[str | None, float | None]]:
    """(currency, last known price) per symbol, in main units: the last daily close (or a polled live quote)."""
    references: dict[str, tuple[str | None, float | None]] = {}
    with closing(connect(settings.db_path)) as conn:
        for symbol in symbols:
            currency = conn.execute("SELECT currency FROM ticker_info WHERE ticker = ?", (symbol,)).fetchone()
            last = conn.execute(
                "SELECT close FROM (SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1) "
                "UNION ALL SELECT price FROM live_quotes WHERE ticker = ? AND currency IS NOT NULL",
                (symbol, symbol),
            ).fetchone()
            references[symbol] = (currency[0] if currency else None, float(last[0]) if last else None)
    return references


class YahooQuoteClient:
    """Latest trade per ticker from Yahoo's minute bars, pre-market and post-market included (D-069).

    One small request per ticker (the last hour of minute bars), a few in parallel. A ticker without a trade in
    that hour (its market is closed) is left out, so its last stored quote or daily close stays in use.
    """

    def __init__(self, now: datetime | None = None) -> None:
        self.now = now

    def _one(self, ticker: str) -> tuple[str, Quote | None, bool]:
        import yfinance as yf
        from yfinance.exceptions import YFRateLimitError

        now = self.now or datetime.now(UTC)
        try:
            handle = yf.Ticker(ticker)
            # raise_errors: a ticker without bars in the window (its market is closed, or Yahoo answered empty)
            # lands in the `except` below instead of yfinance logging "possibly delisted" to the console
            frame = handle.history(start=now - POLL_WINDOW, end=now + timedelta(minutes=1), interval="1m",
                                   prepost=True, auto_adjust=False, raise_errors=True)
            meta = handle.history_metadata or {}
        except YFRateLimitError:
            return ticker, None, True
        except Exception:  # one bad ticker must not stop the others
            return ticker, None, False
        closes = frame["Close"].dropna() if "Close" in frame else []
        if len(closes) == 0:
            return ticker, None, False
        return ticker, to_major_unit(float(closes.iloc[-1]), meta.get("currency")), False

    def last_prices(self, tickers: Iterable[str]) -> dict[str, Quote]:
        tickers = list(tickers)
        if not tickers:
            return {}
        with ThreadPoolExecutor(max_workers=min(POLL_WORKERS, len(tickers))) as pool:
            results = list(pool.map(self._one, tickers))
        if any(limited for _, _, limited in results):
            raise YahooRateLimitError("Yahoo ogranicza liczbę zapytań")
        return {ticker: quote for ticker, quote, _ in results if quote is not None}


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


def live_symbols(settings: Settings) -> list[str]:
    """Every symbol that values the current day: held tickers, then FX pairs (`USDPLN=X`)."""
    with closing(connect(settings.db_path)) as conn:
        migrate(conn)
        return [*held_tickers(conn), *(FX_TICKER.format(currency=c) for c in needed_fx(conn))]


def last_fetch(conn: sqlite3.Connection) -> datetime | None:
    value = conn.execute("SELECT MAX(fetched_at) FROM live_quotes").fetchone()[0]
    return datetime.fromisoformat(value) if value else None


def store_quotes(settings: Settings, quotes: Mapping[str, Quote], now: datetime) -> None:
    """Save the latest quotes; `now` (UTC) is when they were received. Each one is also a point of the 1D
    chart (`intraday_quotes`, one per ticker and minute, D-070)."""
    if not quotes:
        return
    stamp = now.astimezone(UTC).replace(microsecond=0).isoformat()
    with closing(connect(settings.db_path)) as conn:
        migrate(conn)
        conn.executemany(
            "INSERT OR REPLACE INTO live_quotes (ticker, price, currency, fetched_at) VALUES (?, ?, ?, ?)",
            [(ticker, price, currency, stamp) for ticker, (price, currency) in quotes.items()],
        )
        store_bars(conn, ((ticker, now, price) for ticker, (price, _) in quotes.items()), now)


def update_live(
    settings: Settings,
    *,
    now: datetime | None = None,
    client: QuoteClient | None = None,
    tickers: list[str] | None = None,
) -> LiveReport:
    """Poll the latest quotes of every held ticker and FX pair now (online only).

    How often is up to the caller (`market.feed`). `tickers` limits the poll, e.g. to the tickers a stream
    is silent about. Raises `YahooRateLimitError` when Yahoo refuses.
    """
    require_online(settings)
    now = now or datetime.now(UTC)
    symbols = tickers if tickers is not None else live_symbols(settings)
    if not symbols:
        return LiveReport(updated=False, reason="nothing held")
    quotes = (client or YahooQuoteClient()).last_prices(symbols)
    store_quotes(settings, quotes, now)
    return LiveReport(updated=bool(quotes), quotes=len(quotes), missing=sorted(set(symbols) - set(quotes)))


def read_live(db_path, now: datetime | None = None) -> tuple[dict, dict, datetime | None]:
    """Today's live quotes as ({ticker: price}, {currency: PLN per unit}, newest fetched_at).

    Only quotes received on today's local date count (D-069): yesterday's evening quotes (post-market until
    2:00) do not move the new day, which starts from the daily closes.
    """
    now = now or datetime.now(UTC)
    today = now.astimezone().date()
    with closing(sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)) as conn:
        try:
            rows = conn.execute("SELECT ticker, price, fetched_at FROM live_quotes").fetchall()
        except sqlite3.OperationalError:  # table not there yet
            return {}, {}, None
    prices, fx, newest = {}, {}, None
    for ticker, price, fetched_at in rows:
        moment = datetime.fromisoformat(fetched_at)
        if moment.astimezone().date() != today or moment > now + timedelta(minutes=1):
            continue
        newest = max(newest, moment) if newest else moment
        if ticker.endswith("PLN=X"):
            fx[ticker.removesuffix("PLN=X")] = price
        else:
            prices[ticker] = price
    return prices, fx, newest
