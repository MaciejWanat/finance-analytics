"""Shared page data: guard states and the cached valuation used by analysis pages."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from finance_analytics import reports
from finance_analytics.config import Settings
from finance_analytics.market.live import read_live
from finance_analytics.portfolio.valuation import (
    MODEL_VERSION,
    NO_RATES,
    Valuation,
    data_version,
    load_inputs,
    value_portfolio,
)
from finance_analytics.preferences import load_preferences
from ui.components import empty_state

RANGES = ["1M", "3M", "YTD", "1R", "3L", "Maks."]


def period_start(period: str, first: pd.Timestamp, end: pd.Timestamp) -> pd.Timestamp:
    """First day of a period ending at `end`, never before the data starts."""
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
            "Do wyceny w PLN potrzebne są notowania instrumentów i kursy NBP. "
            + ("Pobierz je jednym kliknięciem." if online else
               "Aplikacja jest w trybie offline, więc ich nie pobiera. Włącz tryb online w Ustawieniach."),
            icon=":material/candlestick_chart:",
        )
        if online:
            st.page_link("views/market.py", label="Przejdź do danych rynkowych", icon=":material/arrow_forward:")
        else:
            st.page_link("views/settings.py", label="Przejdź do ustawień", icon=":material/arrow_forward:")
        st.stop()


@st.cache_data(show_spinner="Liczę wycenę portfela…")
def _valuation(db_path: str, version: tuple, today: date, live: tuple, model: int) -> Valuation:
    live_prices, live_fx = (dict(part) for part in live)
    return value_portfolio(load_inputs(Path(db_path)), today, live_prices=live_prices, live_fx=live_fx)


def load_valuation(settings: Settings, *, stop_if_empty: bool = True) -> tuple[Valuation, datetime | None]:
    """The daily valuation (cached per data version), with live quotes in online mode (D-021).

    An empty valuation stops the page with a note, unless the page handles it (`stop_if_empty=False`).
    """
    live_prices, live_fx, live_at = {}, {}, None
    if load_preferences(settings).online:
        live_prices, live_fx, live_at = read_live(settings.db_path, timedelta(hours=12))
    live_key = (tuple(sorted(live_prices.items())), tuple(sorted(live_fx.items())))
    valuation = _valuation(
        str(settings.db_path), data_version(settings.db_path), date.today(), live_key, MODEL_VERSION
    )
    if valuation.total.empty and stop_if_empty:
        if any(w.startswith(NO_RATES) for w in valuation.warnings):
            st.info("Nie da się jeszcze nic wycenić: brakuje kursów NBP dla walut Twoich kont. Pobierz je na "
                    "stronie Dane rynkowe (tryb online).", icon=":material/currency_exchange:")
        else:
            st.info("Brak pozycji i operacji do wyceny.")
        st.stop()
    return valuation, live_at
