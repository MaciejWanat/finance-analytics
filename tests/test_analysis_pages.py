"""Smoke tests of Portfel, Zwroty and Dywidendy with every period, "1D" included (D-070).

A synthetic data directory: the mock XTB export, made-up daily prices and NBP rates, and made-up 5-minute quotes
for today. Offline (the default), so no page starts the live feed or touches the network.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from finance_analytics.config import APP_DIR, DATA_DIR_ENV, Settings
from finance_analytics.db import connect, migrate
from finance_analytics.market.intraday import store_bars
from finance_analytics.mock.xtb_export import write_mock_export
from finance_analytics.sources.sync import import_xtb, sync

PAGES = {name: str(APP_DIR / "views" / f"{name}.py") for name in ("portfolio", "returns", "dividends")}
PERIOD_KEYS = {"portfolio": "period", "returns": "returns_period", "dividends": "dividends_period"}
RATES = {"USD": 4.0, "EUR": 4.3, "GBP": 5.0}


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    root = tmp_path_factory.mktemp("analysis")
    settings = Settings(data_dir=root / "data")
    write_mock_export(root / "export")
    import_xtb(root / "export", settings)
    sync(settings)
    now = datetime.now(UTC)
    days = pd.date_range("2024-10-01", date.today(), freq="D")
    with closing(connect(settings.db_path)) as conn:
        migrate(conn)
        tickers = [r[0] for r in conn.execute("SELECT DISTINCT yahoo_ticker FROM instruments "
                                              "WHERE yahoo_ticker IS NOT NULL")]
        currency = {t: "GBP" if t == "SGLN.L" else "USD" for t in tickers}
        conn.executemany("INSERT OR REPLACE INTO ticker_info (ticker, currency, fetched_at) VALUES (?, ?, 'x')",
                         list(currency.items()))
        conn.executemany(
            "INSERT OR REPLACE INTO prices (ticker, date, close, currency) VALUES (?, ?, ?, ?)",
            [(t, f"{d:%Y-%m-%d}", 50.0 + i * 0.05 + n, currency[t]) for n, t in enumerate(tickers)
             for i, d in enumerate(days)],
        )
        conn.executemany(
            "INSERT OR REPLACE INTO fx_rates (currency, date, mid) VALUES (?, ?, ?)",
            [(c, f"{d:%Y-%m-%d}", mid) for c, mid in RATES.items() for d in days],
        )
        conn.executemany(  # 0.3 % a month, 3.7 % a year
            "INSERT OR REPLACE INTO cpi_monthly (year, month, mom, yoy) VALUES (?, ?, 100.3, 103.7)",
            [(d.year, d.month) for d in pd.date_range("2024-01-01", date.today(), freq="MS")],
        )
        bars = [(t, now - timedelta(minutes=m), 60.0 + m / 100) for t in tickers for m in (5, 30, 90)]
        bars += [(f"{c}PLN=X", now - timedelta(minutes=m), mid) for c, mid in RATES.items() for m in (5, 90)]
        store_bars(conn, bars, now)
        conn.commit()
    return settings


@pytest.mark.parametrize("page", list(PAGES))
@pytest.mark.parametrize("period", ["1D", "1M", "Maks."])
def test_analysis_pages_render_every_period(data_dir, monkeypatch, page, period):
    monkeypatch.setenv(DATA_DIR_ENV, str(data_dir.data_dir))
    at = AppTest.from_file(PAGES[page], default_timeout=90)
    at.session_state[PERIOD_KEYS[page]] = period
    at.run()
    assert not at.exception, at.exception
    assert not at.error


def test_one_day_on_portfel_shows_hours_and_the_previous_close(data_dir, monkeypatch):
    monkeypatch.setenv(DATA_DIR_ENV, str(data_dir.data_dir))
    at = AppTest.from_file(PAGES["portfolio"], default_timeout=90)
    at.session_state["period"] = "1D"
    at.run()
    captions = " ".join(c.value for c in at.caption)
    assert "co 5 minut" in captions and "względem zamknięcia" in captions
    assert "Wartość na koniec każdej godziny" in captions


def test_one_day_offline_without_quotes_offers_a_fetch(tmp_path, monkeypatch, data_dir):
    """Offline, the 1D quotes come only on request (D-031): no quotes for the day means a button, not a fetch."""
    monkeypatch.setenv(DATA_DIR_ENV, str(data_dir.data_dir))
    with closing(sqlite3.connect(data_dir.db_path)) as conn:
        saved = conn.execute("SELECT ticker, ts, price FROM intraday_quotes").fetchall()
        conn.execute("DELETE FROM intraday_quotes")
        conn.commit()
    try:
        at = AppTest.from_file(PAGES["portfolio"], default_timeout=90)
        at.session_state["period"] = "1D"
        at.run()
        assert not at.exception
        assert any(b.label == "Pobierz notowania z dziś" for b in at.button)
    finally:
        with closing(sqlite3.connect(data_dir.db_path)) as conn:
            conn.executemany("INSERT INTO intraday_quotes (ticker, ts, price) VALUES (?, ?, ?)", saved)
            conn.commit()


def test_live_charts_use_the_in_place_component_when_static_serving_is_on(data_dir, monkeypatch):
    """D-072: with the app's static folder served, the value chart and the sparklines are the in-place component;
    without it (the AppTest default) they fall back to st.plotly_chart (the tests above)."""
    from streamlit import config

    monkeypatch.setenv(DATA_DIR_ENV, str(data_dir.data_dir))
    previous = config.get_option("server.enableStaticServing")
    config.set_option("server.enableStaticServing", True)
    try:
        at = AppTest.from_file(PAGES["portfolio"], default_timeout=90)
        at.run()
    finally:
        config.set_option("server.enableStaticServing", previous)
    assert not at.exception, at.exception
    assert len(at.get("bidi_component")) >= 7  # six sparklines and the value chart
    assert len(at.get("plotly_chart")) == 2  # composition and allocation stay Streamlit's own
