"""GUS consumer price index (CPI) for Poland, D-025.

Source: the page "Miesięczne wskaźniki cen towarów i usług konsumpcyjnych od 1982 roku" on
stat.gov.pl. The CSV link on it changes with every release (`..._od_1982_roku__102026_2.csv`),
so the page is scraped for the link first.

Layout of the CSV, checked against the real file (2026-11):
- `;` separator, decimal comma, a trailing `;;` on every line (two unnamed empty columns);
- encoding cp1250, not UTF-8;
- columns `Nazwa zmiennej;Jednostka terytorialna;Sposób prezentacji;Rok;Miesiąc;Wartość;Flaga`;
- one variable ("Wskaźnik cen towarów i usług konsumpcyjnych", all items) and one territory
  ("Polska"), in five presentations; the two used here are "Poprzedni miesiąc = 100" (m/m) and
  "Analogiczny miesiąc poprzedniego roku = 100" (y/y);
- months not published yet are present with an empty value;
- `Flaga` is an old footnote marker on 2001-2002 rows and is ignored.
"""

from __future__ import annotations

import io
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urljoin

import pandas as pd
import requests

from finance_analytics.market import cache

PAGE_URL = (
    "https://stat.gov.pl/obszary-tematyczne/ceny-handel/wskazniki-cen/"
    "wskazniki-cen-towarow-i-uslug-konsumpcyjnych-pot-inflacja-/"
    "miesieczne-wskazniki-cen-towarow-i-uslug-konsumpcyjnych-od-1982-roku"
)
HEADERS = {"User-Agent": "finance-analytics"}  # generic, no personal data
SOURCE, KEY = "gus", "CPI"

HEADLINE = "Wskaźnik cen towarów i usług konsumpcyjnych"  # all items
TERRITORY = "Polska"
MOM = "Poprzedni miesiąc = 100"
YOY = "Analogiczny miesiąc poprzedniego roku = 100"
ENCODINGS = ("utf-8-sig", "cp1250")  # the real file is cp1250; UTF-8 is tried first in case it changes

CpiRow = tuple[int, int, float | None, float | None]  # (year, month, m/m, y/y) in index points
CpiFetch = Callable[[], list[CpiRow]]


class GusError(RuntimeError):
    pass


def find_csv_link(html: str, base_url: str = PAGE_URL) -> str:
    """Absolute URL of the monthly CPI CSV on the GUS page."""
    links = re.findall(r"""href\s*=\s*["']([^"']+\.csv)["']""", html, flags=re.IGNORECASE)
    for link in links:
        if "1982" in link:
            return urljoin(base_url, link)
    raise GusError("GUS: no CSV link for the monthly CPI found on the page")


def decode(raw: bytes) -> str:
    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise GusError("GUS: CSV is neither UTF-8 nor cp1250")


def parse_csv(text: str) -> list[CpiRow]:
    """Headline CPI for Poland as (year, month, m/m, y/y), oldest first; unpublished months are left out."""
    frame = pd.read_csv(io.StringIO(text), sep=";", dtype=str, index_col=False)
    needed = {"Nazwa zmiennej", "Jednostka terytorialna", "Sposób prezentacji", "Rok", "Miesiąc", "Wartość"}
    if not needed <= set(frame.columns):
        raise GusError(f"GUS: unexpected CSV columns {list(frame.columns)}")
    frame = frame[(frame["Nazwa zmiennej"] == HEADLINE) & (frame["Jednostka terytorialna"] == TERRITORY)]
    frame = frame[frame["Sposób prezentacji"].isin([MOM, YOY])]
    frame = frame.assign(
        year=pd.to_numeric(frame["Rok"], errors="coerce"),
        month=pd.to_numeric(frame["Miesiąc"], errors="coerce"),
        value=pd.to_numeric(frame["Wartość"].str.replace(",", ".", regex=False), errors="coerce"),
    ).dropna(subset=["year", "month"])
    wide = frame.pivot_table(index=["year", "month"], columns="Sposób prezentacji", values="value", aggfunc="first")
    wide = wide.reindex(columns=[MOM, YOY])
    wide = wide[wide[MOM].notna()].sort_index()  # a month without m/m cannot extend the index
    if wide.empty:
        raise GusError("GUS: no CPI rows found in the CSV")
    return [
        (int(year), int(month), float(row[MOM]), None if pd.isna(row[YOY]) else float(row[YOY]))
        for (year, month), row in wide.iterrows()
    ]


def fetch_cpi(*, get=requests.get) -> list[CpiRow]:
    """Download the current CPI file: page -> CSV link -> CSV. Public data, no parameters sent."""
    try:
        page = get(PAGE_URL, headers=HEADERS, timeout=30)
        if page.status_code != 200:
            raise GusError(f"GUS page: HTTP {page.status_code}")
        csv_url = find_csv_link(page.text)
        response = get(csv_url, headers=HEADERS, timeout=60)
        if response.status_code != 200:
            raise GusError(f"GUS CSV: HTTP {response.status_code}")
    except requests.RequestException as exc:
        raise GusError(f"GUS: {exc}") from exc
    return parse_csv(decode(response.content))


@dataclass
class CpiReport:
    fetched: int = 0  # rows written
    skipped: bool = False  # already fetched today
    error: str | None = None


def fetched_today(conn: sqlite3.Connection, today: date) -> bool:
    """True when the CPI was downloaded successfully on `today` (it changes once a month, so once a day is plenty)."""
    row = conn.execute(
        "SELECT fetched_at, last_error FROM fetch_log WHERE source = ? AND key = ?", (SOURCE, KEY)
    ).fetchone()
    if row is None or row[1] is not None:
        return False
    return datetime.fromisoformat(row[0]).astimezone().date() == today


def update_cpi(conn: sqlite3.Connection, today: date, *, fetch: CpiFetch = fetch_cpi) -> CpiReport:
    """Refresh the CPI table at most once a day; failures are recorded and never raised."""
    report = CpiReport()
    if fetched_today(conn, today):
        report.skipped = True
        return report
    try:
        rows = fetch()
    except GusError as exc:
        cache.record_error(conn, SOURCE, KEY, str(exc))
        conn.commit()
        report.error = str(exc)
        return report
    conn.executemany("INSERT OR REPLACE INTO cpi_monthly (year, month, mom, yoy) VALUES (?, ?, ?, ?)", rows)
    first, last = rows[0], rows[-1]
    cache.record(conn, SOURCE, KEY, date(first[0], first[1], 1), date(last[0], last[1], 1))
    conn.execute("UPDATE fetch_log SET last_error = NULL WHERE source = ? AND key = ?", (SOURCE, KEY))
    conn.commit()
    report.fetched = len(rows)
    return report


