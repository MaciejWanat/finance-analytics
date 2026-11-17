"""Decide what market data the portfolio needs and bring the cache up to date."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date

from finance_analytics.config import Settings
from finance_analytics.db import connect, migrate
from finance_analytics.market.gus import CpiFetch, CpiReport, fetch_cpi, update_cpi
from finance_analytics.market.nbp import Fetch, FxReport, fetch_rates, update_fx
from finance_analytics.market.network import require_online
from finance_analytics.market.yahoo import PriceClient, PriceReport, update_prices

Progress = Callable[[str, str, int, int], None]  # (source: yahoo/nbp/gus, item, steps done, total steps)


@dataclass
class MarketReport:
    prices: PriceReport
    fx: FxReport
    unresolved: list[str] = field(default_factory=list)  # broker symbols without a Yahoo ticker
    cpi: CpiReport = field(default_factory=CpiReport)

    @property
    def errors(self) -> dict[str, str]:
        errors = {**self.prices.errors, **self.fx.errors}
        if self.cpi.error:
            errors["GUS CPI"] = self.cpi.error
        return errors


def needed_tickers(conn: sqlite3.Connection) -> tuple[dict[str, date], list[str]]:
    """Yahoo ticker -> first day it is needed (first trade or cash event); plus unresolved symbols."""
    rows = conn.execute(
        """
        SELECT i.xtb_symbol, i.yahoo_ticker, MIN(x.day) FROM instruments i
        JOIN (
            SELECT instrument_id, substr(open_time, 1, 10) AS day FROM positions
            UNION ALL
            SELECT instrument_id, substr(ts, 1, 10) FROM cash_ledger WHERE instrument_id IS NOT NULL
        ) x ON x.instrument_id = i.id
        GROUP BY i.id
        """
    ).fetchall()
    tickers: dict[str, date] = {}
    unresolved = []
    for symbol, ticker, first in rows:
        if ticker is None:
            unresolved.append(symbol)
            continue
        day = date.fromisoformat(first)
        tickers[ticker] = min(day, tickers.get(ticker, day))
    return tickers, sorted(unresolved)


def closed_until(conn: sqlite3.Connection) -> dict[str, date]:
    """Yahoo ticker -> last day it is needed, for tickers with no open position (D-042).

    That is the last close or cash event (e.g. a dividend paid after the sale). Prices
    after it are never used: a closed lot has no quantity to value.
    """
    rows = conn.execute(
        """
        SELECT i.yahoo_ticker, MAX(x.open), MAX(x.day) FROM instruments i
        JOIN (
            SELECT instrument_id, close_time IS NULL AS open, substr(COALESCE(close_time, open_time), 1, 10) AS day
            FROM positions
            UNION ALL
            SELECT instrument_id, 0, substr(ts, 1, 10) FROM cash_ledger WHERE instrument_id IS NOT NULL
        ) x ON x.instrument_id = i.id
        WHERE i.yahoo_ticker IS NOT NULL
        GROUP BY i.yahoo_ticker
        """
    ).fetchall()
    return {ticker: date.fromisoformat(last) for ticker, still_open, last in rows if not still_open}


def needed_currencies(conn: sqlite3.Connection, tickers: dict[str, date]) -> dict[str, date]:
    """Currency -> first day it is needed: currencies of accounts with operations or bank balances, and of prices."""
    needed: dict[str, date] = {}

    def need(currency: str | None, day: date) -> None:
        if currency and currency != "PLN":
            needed[currency] = min(day, needed.get(currency, day))

    for currency, first in conn.execute(
        "SELECT a.currency, MIN(substr(c.ts, 1, 10)) FROM accounts a JOIN cash_ledger c ON c.account_id = a.id "
        "GROUP BY a.currency "
        "UNION ALL "  # bank balances (D-027) are valued at NBP rates too
        "SELECT a.currency, MIN(s.date) FROM accounts a JOIN cash_snapshots s ON s.account_id = a.id "
        "GROUP BY a.currency"
    ):
        need(currency, date.fromisoformat(first))
    info = dict(conn.execute("SELECT ticker, currency FROM ticker_info"))
    for ticker, first in tickers.items():
        need(info.get(ticker), first)
    return needed


def update_market(
    settings: Settings,
    *,
    today: date | None = None,
    price_client: PriceClient | None = None,
    fx_fetch: Fetch = fetch_rates,
    cpi_fetch: CpiFetch = fetch_cpi,
    manual: bool = False,
    progress: Progress | None = None,
) -> MarketReport:
    """Bring the market cache up to date.

    `manual=True` marks an explicit request by the user (the button on "Dane rynkowe",
    `fa update-market`); it is allowed in offline mode too, because offline means "never
    on its own" (D-031). Automatic callers leave it False and are refused offline.
    `progress` is called before each step: every Yahoo ticker, then NBP, then GUS.
    """
    if not manual:
        require_online(settings)
    today = today or date.today()
    with closing(connect(settings.db_path)) as conn:
        migrate(conn)
        tickers, unresolved = needed_tickers(conn)
        total = len(tickers) + 2

        def step(source: str, item: str, done: int) -> None:
            if progress:
                progress(source, item, done, total)

        prices = update_prices(
            conn, tickers, today, client=price_client, until=closed_until(conn),
            progress=lambda ticker, done, _: step("yahoo", ticker, done),
        )
        # Price currencies are known only after the first price download.
        step("nbp", "", len(tickers))
        fx = update_fx(conn, needed_currencies(conn, tickers), today, fetch=fx_fetch)
        step("gus", "", len(tickers) + 1)
        cpi = update_cpi(conn, today, fetch=cpi_fetch)  # monthly data, fetched at most once a day (D-025)
    return MarketReport(prices=prices, fx=fx, unresolved=unresolved, cpi=cpi)
