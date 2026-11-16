"""Market data: what is cached locally, and a button to fetch what is missing."""

from __future__ import annotations

import sqlite3
from contextlib import closing

import streamlit as st
from ui.charts import current_mode, line_chart, show
from ui.components import empty_state, page_header, section, table
from ui.glossary import G

from finance_analytics import reports
from finance_analytics.config import get_settings
from finance_analytics.market.update import update_market
from finance_analytics.preferences import load_preferences

page_header("Dane rynkowe", "Ceny instrumentów z Yahoo i kursy walut NBP, zapisane w lokalnej bazie.")
settings = get_settings()


def _has_instruments() -> bool:
    if not settings.db_path.exists():
        return False
    with closing(sqlite3.connect(settings.db_path)) as conn:
        return conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0] > 0


if not _has_instruments():
    empty_state(
        "Najpierw zaimportuj eksport",
        "Aplikacja pobiera ceny tylko dla instrumentów, które masz w zaimportowanych rachunkach.",
        icon=":material/upload_file:",
    )
    st.page_link("views/imports.py", label="Przejdź do importu", icon=":material/arrow_forward:")
    st.stop()

with st.container(border=True):
    st.markdown("#### :material/cloud_download: Aktualizacja")
    st.caption(
        "Do Yahoo i NBP trafiają wyłącznie tickery, kody walut i daty, nic o Twoich rachunkach. "
        "Pobierane są tylko brakujące dni; reszta jest już w lokalnej bazie."
    )
    offline = not load_preferences(settings).online
    if offline:
        st.info(
            "Tryb offline: aplikacja nie łączy się z internetem i korzysta tylko z danych zapisanych poniżej.",
            icon=":material/cloud_off:",
        )
        st.page_link("views/settings.py", label="Włącz tryb online w Ustawieniach", icon=":material/settings:")
    # Two runs: the click only flips a flag, so the button can redraw itself as a disabled
    # spinner before the download starts; the next run does the work and redraws it back.
    updating = st.session_state.get("market_updating", False) and not offline
    st.button(
        "Pobieram ceny i kursy…" if updating else "Pobierz brakujące dane",
        type="primary",
        icon="spinner" if updating else ":material/sync:",
        disabled=updating or offline,
        key="market_update",
        on_click=lambda: st.session_state.update(market_updating=True),
    )
    if updating:
        try:
            st.session_state["market_report"] = update_market(settings)
        finally:
            st.session_state["market_updating"] = False
        st.rerun()

    report = st.session_state.pop("market_report", None)
    if report is not None:
        prices, fx = sum(report.prices.fetched.values()), sum(report.fx.fetched.values())
        st.success(
            f"Zapisano {prices} notowań dla {len(report.prices.fetched)} instrumentów "
            f"i {fx} kursów dla {len(report.fx.fetched)} walut.",
            icon=":material/check_circle:",
        )
        for key, message in report.errors.items():
            st.warning(f"{key}: {message}", icon=":material/warning:")

coverage = reports.price_coverage(settings.db_path)
section("Instrumenty", "Ticker w Yahoo powstaje z tickera XTB (.US → bez sufiksu, .UK → .L).")
table(
    coverage[["symbol", "ticker", "name", "currency", "exchange", "first", "last", "days", "splits", "error"]],
    numbers={"days": 0, "splits": 0},
    labels={
        "symbol": "XTB", "ticker": "Yahoo", "name": "Instrument", "currency": "Waluta", "exchange": "Giełda",
        "first": "Od", "last": "Do", "days": "Notowania", "splits": "Splity", "error": "Ostatni błąd",
    },
    helps={"symbol": G["ticker"], "ticker": G["yahoo_ticker"], "days": G["quotes"], "splits": G["split"],
           "error": G["last_error"]},
)

fx = reports.fx_coverage(settings.db_path)
section("Kursy walut NBP", "Kurs średni (tabela A): ile złotych za jednostkę waluty.", help=G["nbp_rate"])
if fx.empty:
    st.caption("Brak kursów. Użyj przycisku „Pobierz brakujące dane”.")
else:
    table(
        fx,
        numbers={"days": 0, "latest": 4},
        labels={"currency": "Waluta", "first": "Od", "last": "Do", "days": "Notowania", "latest": "Ostatni kurs",
                "error": "Ostatni błąd"},
        helps={"days": G["quotes"], "latest": G["nbp_rate"], "error": G["last_error"]},
    )

priced = coverage[coverage["days"] > 0]
if not priced.empty or not fx.empty:
    section("Podgląd")
    mode = current_mode()
    left, right = st.columns(2)
    with left:
        if not priced.empty:
            labels = dict(zip(priced["ticker"], priced["symbol"] + " · " + priced["name"].fillna(""), strict=True))
            ticker = st.selectbox("Instrument", list(labels), format_func=labels.get)
            currency = priced.set_index("ticker").loc[ticker, "currency"]
            series = reports.price_series(settings.db_path, ticker).to_frame("Cena")
            show(line_chart(series, mode=mode, height=300, hover=f"%{{y:,.2f}} {currency}", y_tickformat=",.2f"),
                 key="price")
    with right:
        if not fx.empty:
            currency = st.selectbox("Waluta", list(fx["currency"]))
            series = reports.fx_series(settings.db_path, currency).to_frame("Kurs")
            show(line_chart(series, mode=mode, height=300, hover="%{y:,.4f} zł", y_tickformat=",.2f"), key="fx")
