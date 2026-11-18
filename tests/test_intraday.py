"""The portfolio within one day, for the "1D" range (D-070): synthetic quotes, no network."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest
from test_valuation import FX, PRICES, D, lot, make_inputs

from finance_analytics.config import Settings
from finance_analytics.db import connect, migrate
from finance_analytics.market import intraday as market_intraday
from finance_analytics.market.hours import NEW_YORK
from finance_analytics.market.network import OfflineError
from finance_analytics.portfolio.intraday import DayWindow, day_window, intraday_values
from finance_analytics.portfolio.valuation import value_portfolio

DAY = D("2026-01-07")
LEDGER = [("usd", D("2026-01-05"), "DEPOSIT", 2000.0), ("usd", D("2026-01-05"), "BUY", -1000.0)]
WINDOW = DayWindow(DAY, D("2026-01-06"), datetime(2026, 1, 7, tzinfo=UTC), datetime(2026, 1, 8, tzinfo=UTC),
                   datetime(2026, 1, 8, tzinfo=UTC))


def quotes(rows) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["ticker", "ts", "price"])
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    return frame.pivot_table(index="ts", columns="ticker", values="price", aggfunc="last")


QUOTES = quotes([
    ("NVDA", "2026-01-06 21:00", 105.0),  # the previous session's last price
    ("NVDA", "2026-01-07 15:00", 108.0),
    ("NVDA", "2026-01-07 20:55", 110.0),
    ("USDPLN=X", "2026-01-07 00:00", 4.0),
    ("USDPLN=X", "2026-01-07 20:00", 4.1),
])


def valuation():
    return value_portfolio(make_inputs(lots=[lot()], ledger=LEDGER, prices=PRICES, fx=FX), date(2026, 1, 7))


def at(series: pd.Series, moment: str) -> float:
    return float(series[series.index == pd.Timestamp(moment, tz="UTC")].iloc[0])


def test_the_last_point_is_the_daily_valuation():
    v = valuation()
    total = intraday_values(v, WINDOW, QUOTES).total
    assert total.iloc[-1] == pytest.approx(v.total[DAY])
    assert total.index[0] == pd.Timestamp("2026-01-07", tz="UTC") and len(total) == 24 * 12 + 1


def test_prices_and_rates_move_each_row_relative_to_the_end():
    v = valuation()
    total = intraday_values(v, WINDOW, QUOTES).total
    position, cash = 10 * 110 * 4.1, 1000 * 4.1  # the daily values at the end of the day
    # 10:00 UTC: NVDA still at the previous close (105), the rate at 4.0; cash moves with the rate only.
    expected = position * (105 / 110) * (4.0 / 4.1) + cash * (4.0 / 4.1)
    assert at(total, "2026-01-07 10:00") == pytest.approx(expected)
    expected = position * (108 / 110) * (4.0 / 4.1) + cash * (4.0 / 4.1)
    assert at(total, "2026-01-07 15:00") == pytest.approx(expected)


def test_currency_part_and_breakdown():
    intra = intraday_values(valuation(), WINDOW, QUOTES)
    # Rates alone: everything in USD went from 4.0 to 4.1 PLN.
    assert intra.fx_part.iloc[-1] == pytest.approx((10 * 110 + 1000) * 4.1 * (1 - 4.0 / 4.1))
    parts = intra.by("kind")
    assert set(parts.columns) == {"position", "cash"} and parts.iloc[-1].sum() == pytest.approx(intra.total.iloc[-1])


def test_split_into_prices_and_rates_since_the_window_start():
    split = intraday_values(valuation(), WINDOW, QUOTES).split()
    last = split.iloc[-1]
    assert last["price"] == pytest.approx((10 * 110 * 4.1 + 1000 * 4.1) / (10 * 105 * 4.1 + 1000 * 4.1) - 1)
    assert last["fx"] == pytest.approx(4.1 / 4.0 - 1)  # everything is in USD
    assert (1 + last["total"]) == pytest.approx((1 + last["price"]) * (1 + last["fx"]) * (1 + last["other"]))
    assert split.iloc[0].abs().max() == 0


def test_an_instrument_without_quotes_stays_flat_and_is_reported():
    v = valuation()
    intra = intraday_values(v, WINDOW, QUOTES.drop(columns="NVDA"))
    assert intra.missing == ["NVDA.US"]
    position = intra.rows[intra.rows["kind"] == "position"].set_index("ts")["value_pln"]
    assert position.iloc[0] == pytest.approx(10 * 110 * 4.1 * 4.0 / 4.1)  # only the rate moves it
    assert intraday_values(v, WINDOW, pd.DataFrame()).total.nunique() == 1  # nothing known: flat


def test_window_by_calendar_day_and_by_us_session():
    now = datetime(2026, 11, 18, 18, 0, tzinfo=UTC)
    calendar = day_window(D("2026-11-18"), by_us_session=False, now=now)
    assert calendar.base == D("2026-11-17") and calendar.start.hour == 0 and calendar.end == now.astimezone()
    assert calendar.until - calendar.start == timedelta(days=1)
    monday = day_window(D("2026-11-16"), by_us_session=True, now=now)
    assert monday.base == D("2026-11-13")  # Friday's session
    assert monday.start == datetime(2026, 11, 13, 16, 0, tzinfo=NEW_YORK)  # from its close


def test_intraday_bars_are_stored_read_and_pruned(tmp_path):
    settings = Settings(data_dir=tmp_path / "data")
    now = datetime(2026, 11, 18, 15, 0, tzinfo=UTC)

    class Bars:
        def bars(self, ticker):
            return [(now - timedelta(minutes=10), 10.0), (now - timedelta(minutes=5), 11.0)]

    with pytest.raises(OfflineError):  # an automatic call needs online mode
        market_intraday.update_intraday(settings, ["NVDA"], client=Bars(), now=now)
    with closing(connect(settings.db_path)) as conn:
        migrate(conn)
        market_intraday.store_bars(conn, [("OLD", now - timedelta(days=11), 1.0)], now - timedelta(days=11))
    report = market_intraday.update_intraday(settings, ["NVDA"], manual=True, client=Bars(), now=now)
    assert report.tickers == 1 and report.rows == 2
    frame = market_intraday.read_intraday(settings.db_path, now - timedelta(hours=1), now)
    assert frame["NVDA"].dropna().tolist() == [10.0, 11.0]
    assert market_intraday.coverage(settings.db_path, now - timedelta(hours=1), now) is not None
    with closing(sqlite3.connect(settings.db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM intraday_quotes WHERE ticker = 'OLD'").fetchone()[0] == 0
