"""Return metrics on hand-computed examples."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from finance_analytics.portfolio.returns import (
    annualize,
    daily_returns,
    drawdown,
    monthly_returns,
    period_return,
    returns_for,
    twr_index,
    xirr,
)

D = pd.Timestamp


def series(values: dict[str, float]) -> pd.Series:
    return pd.Series(list(values.values()), index=pd.to_datetime(list(values)))


# Deposit 1000 on day 1; +10% by day 2; deposit 1000 more on day 3 (no market move);
# +10% by day 4. TWR = 1.1 * 1.0 * 1.1 - 1 = 21%, whatever the timing of deposits.
VALUES = series({"2026-01-01": 1000, "2026-01-02": 1100, "2026-01-03": 2100, "2026-01-04": 2310})
FLOWS = series({"2026-01-01": 1000, "2026-01-03": 1000})


def test_daily_returns_and_twr_ignore_deposits():
    r = daily_returns(VALUES, FLOWS)
    assert r.tolist() == pytest.approx([0.0, 0.1, 0.0, 0.1])
    assert twr_index(VALUES, FLOWS).iloc[-1] == pytest.approx(1.21)
    assert period_return(twr_index(VALUES, FLOWS), D("2026-01-01"), D("2026-01-04")) == pytest.approx(0.21)
    # From day 2's close: only the day-4 gain counts.
    assert period_return(twr_index(VALUES, FLOWS), D("2026-01-02"), D("2026-01-04")) == pytest.approx(0.10)


def test_withdrawal_is_not_a_loss():
    values = series({"2026-01-01": 1000, "2026-01-02": 500})
    flows = series({"2026-01-01": 1000, "2026-01-02": -500})
    assert twr_index(values, flows).iloc[-1] == pytest.approx(1.0)


def test_xirr_known_cases():
    assert xirr([(date(2025, 1, 1), -1000), (date(2026, 1, 1), 1100)]) == pytest.approx(0.0998, abs=1e-3)
    # Excel's documented XIRR example: about 37.34%.
    flows = [(date(2008, 1, 1), -10000), (date(2008, 3, 1), 2750), (date(2008, 10, 30), 4250),
             (date(2009, 2, 15), 3250), (date(2009, 4, 1), 2750)]
    assert xirr(flows) == pytest.approx(0.3734, abs=1e-3)
    assert xirr([(date(2025, 1, 1), -1000), (date(2026, 1, 1), 500)]) == pytest.approx(-0.5, abs=1e-3)
    assert xirr([(date(2025, 1, 1), 1000)]) is None
    assert xirr([(date(2025, 1, 1), 1000), (date(2026, 1, 1), 1000)]) is None


def test_annualize_only_for_a_year_or_more():
    assert annualize(0.21, 30) is None
    assert annualize(0.21, 730) == pytest.approx(1.21 ** (365.25 / 730) - 1)


def test_drawdown_peak_trough_recovery():
    index = series({"2026-01-01": 1.0, "2026-01-02": 1.2, "2026-01-03": 0.9, "2026-01-04": 1.0,
                    "2026-01-05": 1.25})
    dd = drawdown(index)
    assert dd.max_drawdown == pytest.approx(0.9 / 1.2 - 1)
    assert (dd.peak, dd.trough, dd.recovered) == (D("2026-01-02"), D("2026-01-03"), D("2026-01-05"))
    assert dd.current == 0.0
    flat = drawdown(series({"2026-01-01": 1.0, "2026-01-02": 1.1}))
    assert flat.max_drawdown == 0.0 and flat.trough is None


def test_monthly_returns_grid():
    days = pd.date_range("2025-11-01", "2026-02-28", freq="D")
    index = pd.Series(1.0, index=days)
    index[index.index >= "2025-12-01"] = 1.1  # +10% in December
    index[index.index >= "2026-02-01"] = 0.99  # -10% in February
    grid = monthly_returns(index)
    assert grid.loc[2025, 12] == pytest.approx(0.10) and grid.loc[2026, 1] == pytest.approx(0.0)
    assert grid.loc[2026, 2] == pytest.approx(-0.10)
    assert grid.loc[2026, "year"] == pytest.approx(0.99 / 1.1 - 1)
    assert pd.isna(grid.loc[2026, 3])


def test_returns_for_window():
    result = returns_for(VALUES, FLOWS, D("2026-01-01"), D("2026-01-04"))
    assert result.twr == pytest.approx(0.21) and result.twr_annual is None
    assert result.index.iloc[-1] == pytest.approx(1.21)
    assert result.xirr is None  # annual rates are not reported for windows under a year


def test_xirr_differs_from_twr_when_timing_matters():
    # 1000 in, -20% in year one; 10000 more in, +20% in year two.
    values = series({"2024-01-01": 1000, "2025-01-01": 800, "2025-01-02": 10800, "2026-01-02": 12960})
    flows = series({"2024-01-01": 1000, "2025-01-02": 10000})
    result = returns_for(values, flows, D("2024-01-01"), D("2026-01-02"))
    assert result.twr == pytest.approx(0.8 * 1.2 - 1)  # -4%: the investments lost overall
    assert result.xirr > 0.15  # but most money came in before the good year: the saver gained


def test_underwater_is_the_lowest_profit_relative_to_deposits():
    """D-049, the user's example: 1000 PLN in, 800 at the lowest, 1200 today -> -20 %."""
    from finance_analytics.portfolio.returns import underwater

    days = pd.date_range("2026-01-01", periods=5, freq="D")
    values = pd.Series([1000.0, 900.0, 800.0, 1100.0, 1200.0], index=days)
    contributed = pd.Series([1000.0] * 5, index=days)
    uw = underwater(values, contributed)
    assert uw.worst == pytest.approx(-0.2) and uw.day == days[2] and uw.profit == pytest.approx(-200)
    assert uw.current == pytest.approx(0.2)
    # A later deposit raises the bar: 1000 + 1000 in, value 1500 -> -25 %.
    more = underwater(pd.Series([1000.0, 1500.0], index=days[:2]), pd.Series([1000.0, 2000.0], index=days[:2]))
    assert more.worst == pytest.approx(-0.25)
    # Never below the deposits: the lowest ratio is positive.
    assert underwater(values + 500, contributed).worst == pytest.approx(0.3)
    # From a start day on, and nothing before the first deposit.
    assert underwater(values, contributed, start=days[3]).worst == pytest.approx(0.1)
    assert underwater(values, pd.Series(0.0, index=days)).worst is None


def test_rounding_noise_is_not_capital():
    """D-062: a deposit and a withdrawal that cancel on day one leave 1e-13, not money at risk."""
    from finance_analytics.portfolio.returns import daily_returns, twr_index, underwater

    days = pd.date_range("2020-01-06", periods=3, freq="D")
    values = pd.Series([0.0, 1000.0, 1100.0], index=days)
    noise = 1e-13
    flows = pd.Series([noise, 1000.0], index=[days[0], days[1]])
    assert daily_returns(values, flows).iloc[0] == 0.0  # not -100 %
    assert twr_index(values, flows).iloc[-1] == pytest.approx(1.1)
    contributed = flows.reindex(days, fill_value=0.0).cumsum()
    uw = underwater(values, contributed)
    assert uw.worst == pytest.approx(0.0) and uw.current == pytest.approx(0.1)  # day one is not -100 %


def test_change_since_the_previous_close_ignores_deposits():
    """D-063: today's result is the value change minus today's deposit; the % is the TWR of the day."""
    from finance_analytics.portfolio.returns import change_since

    amount, pct = change_since(VALUES, FLOWS, D("2026-01-03"))
    assert amount == pytest.approx(210.0) and pct == pytest.approx(0.10)
    # Day 3: the 1000 deposit is not a gain.
    amount, pct = change_since(VALUES.loc[:"2026-01-03"], FLOWS, D("2026-01-02"))
    assert amount == pytest.approx(0.0) and pct == pytest.approx(0.0)
    # Over a weekend-like span (two days back) both days count.
    amount, pct = change_since(VALUES, FLOWS, D("2026-01-02"))
    assert amount == pytest.approx(210.0) and pct == pytest.approx(0.10)
    # No close before the first day: nothing to compare with.
    assert change_since(VALUES, FLOWS, D("2025-12-31")) is None
