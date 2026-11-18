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
    assert load_preferences(settings) == Preferences(network="offline", live_source="poll", poll_seconds=300,
                                                     stream_seconds=5)
    save_preferences(settings, Preferences(network="online", live_source="stream", poll_seconds=600, stream_seconds=15))
    loaded = load_preferences(settings)
    assert loaded.online and loaded.streaming and loaded.redraw_seconds == 15 and loaded.poll_seconds == 600
    assert loaded.model_copy(update={"live_source": "poll"}).redraw_seconds == 30  # polling: redraw every 30 s
    settings.preferences_file.write_text("network: sometimes\n", encoding="utf-8")
    with pytest.raises(PreferencesError):
        load_preferences(settings)


def test_each_source_has_its_own_range(tmp_path):
    """D-069: polling never more often than every 2 minutes (Yahoo); the stream redraws every 5 to 60 seconds."""
    settings = Settings(data_dir=tmp_path)
    settings.preferences_file.parent.mkdir(parents=True)
    for wrong in ("poll_seconds: 60\n", "poll_seconds: 7200\n", "stream_seconds: 2\n", "stream_seconds: 120\n",
                  "live_source: carrier-pigeon\n"):
        settings.preferences_file.write_text(wrong, encoding="utf-8")
        with pytest.raises(PreferencesError):
            load_preferences(settings)


def test_older_settings_keep_their_interval_within_the_polling_range(tmp_path):
    """`refresh_minutes` (before D-069) and the short-lived `refresh_seconds` become `poll_seconds`, at least 2 min."""
    settings = Settings(data_dir=tmp_path)
    settings.preferences_file.parent.mkdir(parents=True)
    for text, seconds in (("refresh_minutes: 7\n", 420), ("refresh_minutes: 1\n", 120),
                          ("refresh_seconds: 5\n", 120), ("refresh_seconds: 900\n", 900)):
        settings.preferences_file.write_text("network: online\n" + text, encoding="utf-8")
        assert load_preferences(settings).poll_seconds == seconds, text
    save_preferences(settings, load_preferences(settings))
    saved = settings.preferences_file.read_text(encoding="utf-8")
    assert "poll_seconds: 900" in saved and "\nrefresh_" not in saved


def test_offline_makes_no_network_calls(imported, no_network):
    with pytest.raises(OfflineError):
        update_market(imported)  # an automatic caller is refused offline
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
                for t in tickers if t != "VUAA.L"}


def _seed_ticker_info(settings):
    with closing(sqlite3.connect(settings.db_path)) as conn:
        from finance_analytics.db import migrate

        migrate(conn)
        conn.execute("INSERT INTO ticker_info (ticker, currency, fetched_at) VALUES ('NVDA', 'USD', 'x')")
        conn.commit()


def test_update_live_polls_held_tickers_and_fx(imported):
    go_online(imported)
    _seed_ticker_info(imported)
    client = FakeQuotes()
    report = live.update_live(imported, now=MONDAY_NOON, client=client)
    assert report.updated and "USDPLN=X" in client.calls[0] and "EURPLN=X" in client.calls[0]
    assert "VUAA.L" in report.missing  # reported, not fatal (bought every month, always held)
    # The cadence is the feed's job (market.feed): every call polls, optionally only some tickers.
    assert live.update_live(imported, now=MONDAY_NOON, client=client, tickers=["NVDA"]).quotes == 1
    assert client.calls[-1] == ["NVDA"]

    prices, fx, at = live.read_live(imported.db_path, now=MONDAY_NOON + timedelta(minutes=10))
    assert prices["NVDA"] == 123.0 and fx["USD"] == 4.0 and at is not None


def test_live_quotes_count_only_on_the_day_they_arrived(imported):
    """D-069: yesterday's evening quotes (post-market) do not move the new day; it starts from the closes."""
    go_online(imported)
    evening = datetime.now(UTC).astimezone().replace(hour=23, minute=30, second=0, microsecond=0)
    live.store_quotes(imported, {"NVDA": (130.0, "USD")}, evening)
    assert live.read_live(imported.db_path, now=evening + timedelta(minutes=20))[0] == {"NVDA": 130.0}
    after_midnight = evening + timedelta(hours=1)
    assert live.read_live(imported.db_path, now=after_midnight) == ({}, {}, None)


def test_quotes_in_pence_are_stored_in_pounds():
    assert live.to_major_unit(7650.0, "GBp") == (76.5, "GBP")
    assert live.to_major_unit(12.5, "USD") == (12.5, "USD")
    # The stream may leave the currency out; a London price ~100x its last close is in pence.
    assert live.stream_quote(5540.44, None, ("GBP", 55.48)) == pytest.approx((55.4044, "GBP"))
    assert live.stream_quote(56.1, None, ("GBP", 55.48)) == (56.1, "GBP")
    assert live.stream_quote(159.6, None, ("USD", 155.46)) == (159.6, "USD")
    assert live.stream_quote(10450.0, "GBp", ("GBP", None)) == (104.5, "GBP")


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


def test_daily_update_after_the_us_close(imported, monkeypatch):
    """D-067: one more update shortly after the US close, so the session's closing prices are final."""
    warsaw = timezone(timedelta(hours=1))
    monkeypatch.setattr(auto, "last_update", lambda db_path: datetime(2026, 11, 16, 18, tzinfo=warsaw))
    assert not auto.daily_update_due(imported.db_path, datetime(2026, 11, 16, 22, 10, tzinfo=warsaw))
    assert auto.daily_update_due(imported.db_path, datetime(2026, 11, 16, 22, 20, tzinfo=warsaw))
    monkeypatch.setattr(auto, "last_update", lambda db_path: datetime(2026, 11, 16, 22, 20, tzinfo=warsaw))
    assert not auto.daily_update_due(imported.db_path, datetime(2026, 11, 16, 23, 30, tzinfo=warsaw))


def test_today_tile_preference(tmp_path):
    settings = Settings(data_dir=tmp_path / "data")
    assert load_preferences(settings).today_tile == "calendar_day"
    save_preferences(settings, Preferences(today_tile="us_session"))
    assert load_preferences(settings).today_tile == "us_session"
    settings.preferences_file.write_text("today_tile: weekly\n", encoding="utf-8")
    with pytest.raises(PreferencesError):
        load_preferences(settings)
