"""The portfolio against the S&P 500 (D-080): the shadow portfolio and the index in PLN."""

from __future__ import annotations

import sqlite3
from datetime import date

import pandas as pd
import pytest

from finance_analytics.db import migrate
from finance_analytics.market.update import with_benchmark
from finance_analytics.portfolio.benchmark import BENCHMARK_TICKER, compare, index_in_pln

DAYS = pd.date_range("2026-01-01", periods=5, freq="D")
NO_FLOWS = pd.Series(dtype=float)


def test_same_as_index_is_not_beating_it():
    index = pd.Series([100.0, 110.0, 99.0, 120.0, 130.0], index=DAYS)
    total = index * 10  # the portfolio is exactly the index
    vs = compare(total, NO_FLOWS, index, DAYS[0])
    assert vs.gap.abs().max() == pytest.approx(0)
    assert not vs.beaten
    assert vs.index_return == pytest.approx(0.30)


def test_deposit_buys_the_index_on_its_day():
    index = pd.Series([100.0, 100.0, 200.0, 200.0, 200.0], index=DAYS)
    # 1000 zł at the start, 1000 zł more on day 2 (bought at 100); the portfolio stays in cash.
    total = pd.Series([1000.0, 2000.0, 2000.0, 2000.0, 2000.0], index=DAYS)
    flows = pd.Series([1000.0, 1000.0], index=[DAYS[0], DAYS[1]])
    vs = compare(total, flows, index, DAYS[0])
    # The shadow: 10 units, then 10 more at 100 -> 20 units at 200 = 4000 zł.
    assert vs.shadow.iloc[-1] == pytest.approx(4000)
    assert vs.gap.iloc[-1] == pytest.approx(-2000)
    assert not vs.beaten


def test_withdrawal_sells_the_index_and_beating_it():
    index = pd.Series([100.0, 100.0, 100.0, 100.0, 50.0], index=DAYS)
    total = pd.Series([1000.0, 1000.0, 500.0, 500.0, 500.0], index=DAYS)  # cash, 500 zł taken out on day 3
    flows = pd.Series([-500.0], index=[DAYS[2]])
    vs = compare(total, flows, index, DAYS[0])
    assert vs.shadow.iloc[-1] == pytest.approx(250)  # 5 units left, at 50
    assert vs.gap.iloc[-1] == pytest.approx(250)
    assert vs.beaten


def test_period_start_and_last_index_close():
    index = pd.Series([100.0, 100.0, 120.0, 150.0, float("nan")], index=DAYS)  # no close on the last day yet
    total = pd.Series([1.0, 500.0, 600.0, 700.0, 900.0], index=DAYS)
    vs = compare(total, NO_FLOWS, index, DAYS[1])
    assert list(vs.gap.index) == list(DAYS[1:4])  # from the period start, up to the last close
    assert vs.gap.iloc[-1] == pytest.approx(700 - 750)


def test_no_index_on_the_start_day_is_no_comparison():
    index = pd.Series([float("nan"), 100.0, 100.0, 100.0, 100.0], index=DAYS)
    assert compare(pd.Series(1.0, index=DAYS), NO_FLOWS, index, DAYS[0]) is None
    assert compare(pd.Series(1.0, index=DAYS), NO_FLOWS, pd.Series(float("nan"), index=DAYS), DAYS[0]) is None


def test_index_in_pln_carries_closes_and_rates_but_not_past_the_last_close():
    close = pd.Series([10.0, 12.0], index=pd.to_datetime(["2026-01-02", "2026-01-04"]))
    fx = pd.Series([4.0, 3.5], index=pd.to_datetime(["2026-01-01", "2026-01-03"]))
    level = index_in_pln(close, fx, DAYS)
    assert level.isna().tolist() == [True, False, False, False, True]
    assert level.iloc[1:4].tolist() == [40.0, 35.0, 42.0]


def test_benchmark_is_fetched_from_the_portfolio_first_day():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    assert with_benchmark(conn, {}) == {}  # no portfolio, nothing to compare
    conn.execute("INSERT INTO accounts (id, alias, institution, kind, currency) "
                 "VALUES ('bank', 'Konto', 'bank', 'bank', 'PLN')")
    conn.execute("INSERT INTO cash_snapshots (account_id, date, balance, row_no) VALUES ('bank', '2025-03-01', 1, 1)")
    needed = with_benchmark(conn, {"AAPL": date(2025, 5, 1)})
    assert needed == {"AAPL": date(2025, 5, 1), BENCHMARK_TICKER: date(2025, 3, 1)}
