"""Shared page data: guard states and the cached valuation used by analysis pages."""

from __future__ import annotations

import sqlite3
from contextlib import closing, nullcontext
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from finance_analytics import reports
from finance_analytics.config import Settings
from finance_analytics.market.intraday import read_intraday
from finance_analytics.market.live import read_live
from finance_analytics.portfolio.intraday import DayWindow, Intraday, day_window, intraday_values
from finance_analytics.portfolio.today import today_result
from finance_analytics.portfolio.valuation import (
    MODEL_VERSION,
    NO_RATES,
    Valuation,
    data_version,
    load_inputs,
    market_days,
    value_portfolio,
)
from finance_analytics.preferences import PreferencesError, load_preferences
from ui.components import empty_state

RANGES = ["1D", "1M", "3M", "YTD", "1R", "3L", "Maks."]
ONE_DAY = "1D"  # the day of the "Dzisiaj" tile, every 5 minutes (D-070)
# True while the whole app script runs (main.py); a fragment's own timer run sees False (D-069).
FULL_RUN = "full_app_run"


def period_start(
    period: str, first: pd.Timestamp, end: pd.Timestamp, *, day_base: pd.Timestamp | None = None
) -> pd.Timestamp:
    """First day of a period ending at `end`, never before the data starts. "1D" starts at `day_base`, the close
    the "Dzisiaj" tile is measured from (`one_day`), or the day before `end`."""
    if period == ONE_DAY:
        return max(day_base if day_base is not None else end - pd.Timedelta(days=1), first)
    start = {
        "1M": end - pd.DateOffset(months=1),
        "3M": end - pd.DateOffset(months=3),
        "YTD": pd.Timestamp(end.year, 1, 1) - pd.Timedelta(days=1),  # measured from last year's close
        "1R": end - pd.DateOffset(years=1),
        "3L": end - pd.DateOffset(years=3),
        "Maks.": first,
    }[period]
    return max(start, first)


def require_database(settings: Settings) -> None:
    """Stop the page with instructions when the local database does not exist yet."""
    if not settings.db_path.exists():
        empty_state(
            "Brak lokalnej bazy danych",
            f"Aplikacja nie znalazła bazy w katalogu danych `{settings.data_dir}`. Utwórz ją jednym poleceniem:",
            icon=":material/database:",
            steps=["W terminalu, w katalogu projektu, uruchom `fa init`.", "Odśwież tę stronę."],
        )
        st.stop()


def require_valued_data(settings: Settings, purpose: str) -> None:
    """Show the right empty state and stop the page if there is nothing to value yet."""
    require_database(settings)
    if reports.accounts_overview(settings.db_path).empty:
        empty_state(
            "Nie ma jeszcze danych do pokazania",
            f"Po zaimportowaniu historii konta z XTB albo dodaniu obligacji zobaczysz tu {purpose}.",
            icon=":material/upload_file:",
            steps=[
                "W xStation wyeksportuj historię konta: powstanie folder z podfolderami kont.",
                "Zaimportuj go na stronie **Importy** albo poleceniem `fa import xtb <folder>`.",
                "Obligacje skarbowe dodasz na stronie **Obligacje**.",
            ],
        )
        st.page_link("views/imports.py", label="Przejdź do importu", icon=":material/arrow_forward:")
        st.stop()
    with closing(sqlite3.connect(settings.db_path)) as conn:
        has_prices = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0] > 0
        # Bonds are valued without market data (D-026); prices matter only once there are positions.
        has_positions = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0] > 0
    if has_positions and not has_prices:
        online = load_preferences(settings).online
        empty_state(
            "Brakuje cen i kursów walut",
            "Do wyceny w PLN potrzebne są notowania instrumentów i kursy NBP. Pobierz je jednym kliknięciem "
            "na stronie Dane rynkowe"
            + ("." if online else " (w trybie offline to jednorazowe pobranie; aplikacja sama nic nie pobiera)."),
            icon=":material/candlestick_chart:",
        )
        st.page_link("views/market.py", label="Przejdź do danych rynkowych", icon=":material/arrow_forward:")
        st.stop()


# Live quotes change the key every few seconds (D-069): keep only the latest few valuations in memory.
@st.cache_data(show_spinner=False, max_entries=6)
def _valuation(db_path: str, version: tuple, today: date, live: tuple, model: int) -> Valuation:
    live_prices, live_fx = (dict(part) for part in live)
    return value_portfolio(load_inputs(Path(db_path)), today, live_prices=live_prices, live_fx=live_fx)


def load_valuation(
    settings: Settings, *, stop_if_empty: bool = True, live_run: bool = False
) -> tuple[Valuation, datetime | None]:
    """The daily valuation (cached per data version), with live quotes in online mode (D-021).

    An empty valuation stops the page with a note, unless the page handles it (`stop_if_empty=False`).
    `live_run`: called from a live fragment's timer run (D-069), so no spinner flashes every few seconds.
    """
    live_prices, live_fx, live_at = {}, {}, None
    if load_preferences(settings).online:
        live_prices, live_fx, live_at = read_live(settings.db_path)
    live_key = (tuple(sorted(live_prices.items())), tuple(sorted(live_fx.items())))
    with st.spinner("Liczę wycenę portfela…") if not live_run else nullcontext():
        valuation = _valuation(
            str(settings.db_path), data_version(settings.db_path), date.today(), live_key, MODEL_VERSION
        )
    if valuation.total.empty and stop_if_empty:
        if any(w.startswith(NO_RATES) for w in valuation.warnings):
            st.info("Nie da się jeszcze nic wycenić: brakuje kursów NBP dla walut Twoich kont. Pobierz je na "
                    "stronie Dane rynkowe.", icon=":material/currency_exchange:")
        else:
            st.info("Brak pozycji i operacji do wyceny.")
        st.stop()
    return valuation, live_at


def one_day(settings: Settings, v: Valuation, now: datetime | None = None) -> DayWindow:
    """The "1D" window: the day of the "Dzisiaj" tile, counted from midnight or by US sessions (D-067, D-070)."""
    try:
        today_tile = load_preferences(settings).today_tile
    except PreferencesError:  # the sidebar reports a broken settings file
        today_tile = "calendar_day"
    by_us_session = today_tile == "us_session" and reports.holds_us_listed(settings.db_path)
    now = now or datetime.now(UTC)
    flows = v.flows.set_index("date")["amount_pln"].sort_index()
    tile = today_result(v.total, flows, market_days(v), by_us_session=by_us_session, now=now)
    return day_window(tile.day, by_us_session=by_us_session, now=now)


def load_intraday(settings: Settings, v: Valuation, window: DayWindow) -> Intraday:
    """The portfolio every 5 minutes within `window`, from the saved intraday quotes (D-070)."""
    quotes = read_intraday(settings.db_path, window.start, window.end)
    return intraday_values(v, window, quotes)
