"""NBP exchange rates, table A (average/mid rates), D-008.

API: https://api.nbp.pl/api/exchangerates/rates/a/{code}/{from}/{to}/?format=json
- at most 93 days per request;
- 404 means "no quotes in this range" (weekends, holidays), not an error;
- data from 2002-01-02.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

import requests

from finance_analytics.market import cache

URL = "https://api.nbp.pl/api/exchangerates/rates/a/{code}/{start}/{end}/?format=json"
MAX_DAYS = 93
FIRST_DAY = date(2002, 1, 2)
HEADERS = {"Accept": "application/json", "User-Agent": "finance-analytics"}  # generic, no personal data

Rate = tuple[date, float, str]  # (effective date, PLN per unit, table number)
Fetch = Callable[[str, date, date], list[Rate]]


class NbpError(RuntimeError):
    pass


def fetch_rates(currency: str, start: date, end: date, *, get=requests.get) -> list[Rate]:
    """Mid rates for one currency in [start, end], split into <=93-day requests."""
    rates: list[Rate] = []
    chunk_start = max(start, FIRST_DAY)
    while chunk_start <= end:
        chunk_end = min(end, chunk_start + timedelta(days=MAX_DAYS - 1))
        url = URL.format(code=currency.lower(), start=chunk_start.isoformat(), end=chunk_end.isoformat())
        try:
            response = get(url, headers=HEADERS, timeout=20)
        except requests.RequestException as exc:
            raise NbpError(f"NBP {currency}: {exc}") from exc
        if response.status_code == 404:
            pass  # no quotes in this range
        elif response.status_code != 200:
            raise NbpError(f"NBP {currency} {chunk_start}..{chunk_end}: HTTP {response.status_code}")
        else:
            for item in response.json().get("rates", []):
                rates.append((date.fromisoformat(item["effectiveDate"]), float(item["mid"]), item.get("no")))
        chunk_start = chunk_end + timedelta(days=1)
    return rates


@dataclass
class FxReport:
    fetched: dict[str, int] = field(default_factory=dict)  # currency -> rows written
    errors: dict[str, str] = field(default_factory=dict)


def update_fx(
    conn: sqlite3.Connection,
    needed: dict[str, date],
    today: date,
    *,
    fetch: Fetch = fetch_rates,
) -> FxReport:
    """Bring the cache up to date for each currency from its first needed day to today.

    Today's rate is published around noon, so it is never marked as final: the next
    run asks for it again.
    """
    report = FxReport()
    final_until = today - timedelta(days=1)
    for currency, first_needed in sorted(needed.items()):
        if currency == "PLN":
            continue
        # A few days before the first needed day, so there is always an earlier rate to carry over.
        start = max(FIRST_DAY, first_needed - timedelta(days=7))
        written = 0
        try:
            for range_start, range_end in cache.missing_ranges(cache.coverage(conn, "nbp", currency), start, today):
                rows = fetch(currency, range_start, range_end)
                conn.executemany(
                    "INSERT OR REPLACE INTO fx_rates (currency, date, mid, table_no) VALUES (?, ?, ?, ?)",
                    [(currency, d.isoformat(), mid, no) for d, mid, no in rows],
                )
                written += len(rows)
                if range_start <= final_until:
                    cache.record(conn, "nbp", currency, range_start, min(range_end, final_until))
            conn.commit()
        except NbpError as exc:
            conn.commit()
            cache.record_error(conn, "nbp", currency, str(exc))
            conn.commit()
            report.errors[currency] = str(exc)
        report.fetched[currency] = written
    return report
