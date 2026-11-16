"""Online/offline mode (D-021): offline is the default and makes no network calls."""

from __future__ import annotations

import socket
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone

import pytest
from conftest import go_online
from test_valuation import FX, PRICES, D, lot, make_inputs

from finance_analytics.config import Settings
from finance_analytics.market import auto, live
from finance_analytics.market.network import OfflineError
from finance_analytics.market.update import update_market
from finance_analytics.mock.xtb_export import write_mock_export
from finance_analytics.portfolio.valuation import load_inputs, value_portfolio
from finance_analytics.preferences import Preferences, PreferencesError, load_preferences, save_preferences
from finance_analytics.sources.sync import import_xtb, sync

MONDAY_NOON = datetime(2026, 11, 16, 11, 0, tzinfo=UTC)


@pytest.fixture
def imported(tmp_path):
    settings = Settings(data_dir=tmp_path / "data")
    write_mock_export(tmp_path / "export")
    import_xtb(tmp_path / "export", settings)
    sync(settings)
    return settings


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def test_preferences_default_offline_and_roundtrip(tmp_path):
    settings = Settings(data_dir=tmp_path)
    assert load_preferences(settings) == Preferences(network="offline", refresh_minutes=5)
    save_preferences(settings, Preferences(network="online", refresh_minutes=15))
    assert load_preferences(settings).online and load_preferences(settings).refresh_minutes == 15
    settings.preferences_file.write_text("network: sometimes\n", encoding="utf-8")
    with pytest.raises(PreferencesError):
        load_preferences(settings)


def test_offline_makes_no_network_calls(imported, no_network):
    with pytest.raises(OfflineError):
        update_market(imported)
    with pytest.raises(OfflineError):
        live.update_live(imported)
    assert auto.maybe_update_market(imported) is None
    # The rest of the app keeps working on cached data.
    valuation = value_portfolio(load_inputs(imported.db_path), MONDAY_NOON.date())
    assert not valuation.daily.empty


class FakeQuotes:
    def __init__(self):
        self.calls = []

    def last_prices(self, tickers):
        tickers = list(tickers)
        self.calls.append(tickers)
        return {t: (4.0 if t.endswith("PLN=X") else 123.0, "PLN" if t.endswith("PLN=X") else "USD")
                for t in tickers if t != "AMD"}


def _seed_ticker_info(settings):
    with closing(sqlite3.connect(settings.db_path)) as conn:
        from finance_analytics.db import migrate

        migrate(conn)
        conn.execute("INSERT INTO ticker_info (ticker, currency, fetched_at) VALUES ('NVDA', 'USD', 'x')")
        conn.commit()


def test_update_live_polls_held_tickers_and_fx_with_throttle(imported):
    go_online(imported)
    _seed_ticker_info(imported)
    client = FakeQuotes()
    report = live.update_live(imported, now=MONDAY_NOON, client=client)
    assert report.updated and "USDPLN=X" in client.calls[0] and "EURPLN=X" in client.calls[0]
    assert "AMD" in report.missing  # reported, not fatal
    # Within the refresh interval nothing is fetched again; after it, it is.
    assert not live.update_live(imported, now=MONDAY_NOON + timedelta(minutes=2), client=client).updated
    assert live.update_live(imported, now=MONDAY_NOON + timedelta(minutes=6), client=client).updated
    assert live.update_live(imported, now=datetime(2026, 11, 21, 12, tzinfo=UTC), client=client).reason == "weekend"

    prices, fx, at = live.read_live(imported.db_path, timedelta(hours=1), now=MONDAY_NOON + timedelta(minutes=10))
    assert prices["NVDA"] == 123.0 and fx["USD"] == 4.0 and at is not None
    stale = live.read_live(imported.db_path, timedelta(minutes=1), now=MONDAY_NOON + timedelta(hours=2))
    assert stale == ({}, {}, None)


def test_live_quotes_change_only_todays_value():
    inputs = make_inputs(lots=[lot()], prices=PRICES, fx=FX)
    base = value_portfolio(inputs, D("2026-01-07").date())
    live_v = value_portfolio(inputs, D("2026-01-07").date(), live_prices={"NVDA": 120.0}, live_fx={"USD": 4.2})
    day = D("2026-01-07")
    assert live_v.total[day] == pytest.approx(10 * 120 * 4.2)
    assert live_v.total[D("2026-01-06")] == base.total[D("2026-01-06")]  # history untouched
    assert live_v.lots["cost_pln"].item() == base.lots["cost_pln"].item()  # cost stays on NBP


def test_daily_update_schedule(imported, monkeypatch):
    warsaw = timezone(timedelta(hours=1))

    def last(value):
        monkeypatch.setattr(auto, "last_update", lambda db_path: value)

    last(None)
    assert auto.daily_update_due(imported.db_path, datetime(2026, 11, 16, 9, tzinfo=warsaw))
    last(datetime(2026, 11, 16, 9, tzinfo=warsaw))
    assert not auto.daily_update_due(imported.db_path, datetime(2026, 11, 16, 11, tzinfo=warsaw))
    assert auto.daily_update_due(imported.db_path, datetime(2026, 11, 16, 12, 30, tzinfo=warsaw))  # NBP published
    assert auto.daily_update_due(imported.db_path, datetime(2026, 11, 16, 15, 1, tzinfo=warsaw))  # 6 h passed
    last(datetime(2026, 11, 21, 9, tzinfo=warsaw))  # Saturday: no NBP table
    assert not auto.daily_update_due(imported.db_path, datetime(2026, 11, 21, 12, 30, tzinfo=warsaw))
