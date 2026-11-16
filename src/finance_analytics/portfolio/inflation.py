"""Inflation-adjusted returns from the GUS consumer price index (D-025, R-004).

- The price level is chained from the published month-on-month indices (100.3 = +0.3%)
  and set to 100 at the first month. Only ratios of levels matter, so the base is arbitrary.
- The level is a monthly step: every day of a month has that month's level. GUS publishes a
  month in the middle of the next one, so the newest days fall in months with no data yet;
  they carry the last known level (no inflation assumed) and are flagged as estimated.
- Real return of a window: (1 + nominal) / (1 + inflation) - 1 (the Fisher relation, exact).
- Value in today's zloty: value_t * level_latest / level_t.
"""

from __future__ import annotations

import pandas as pd

from finance_analytics.portfolio.returns import annualize


def price_level_index(mom: pd.Series) -> pd.Series:
    """Price level, 100 at the first month. `mom`: m/m index points (previous month = 100) by month start.

    Only the latest unbroken run of months is used: a gap would make the chain meaningless, and
    the newest data matter most.
    """
    mom = mom.dropna().sort_index()
    if mom.empty:
        return pd.Series(dtype=float)
    mom.index = mom.index.to_period("M").to_timestamp()
    full = pd.date_range(mom.index[0], mom.index[-1], freq="MS")
    missing = full.difference(mom.index)
    if len(missing):
        mom = mom[mom.index > missing[-1]]
    steps = (mom / 100).copy()
    steps.iloc[0] = 1.0  # the first month defines the base
    return (steps.cumprod() * 100).rename("level")


def daily_levels(levels: pd.Series, days: pd.DatetimeIndex) -> pd.DataFrame:
    """Level for each day (its month's level) and whether that month is not published yet.

    Columns: `level` (NaN before the first month) and `estimated` (the month is after the last
    published one, so the last known level is carried forward).
    """
    months = days.to_period("M").to_timestamp()
    if levels.empty:
        return pd.DataFrame({"level": float("nan"), "estimated": True}, index=days)
    level = levels.reindex(levels.index.union(months.unique())).ffill().reindex(months)
    return pd.DataFrame({"level": level.to_numpy(), "estimated": months > levels.index[-1]}, index=days)


def window_inflation(daily: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> float | None:
    """Price rise between two days: level(end) / level(start) - 1; None when a level is unknown."""
    first, last = daily["level"].asof(start), daily["level"].asof(end)
    if pd.isna(first) or pd.isna(last):
        return None
    return float(last / first - 1)


def real_return(nominal: float, inflation: float) -> float:
    return (1 + nominal) / (1 + inflation) - 1


def real_annual(real: float, days: float) -> float | None:
    """Annualized real return, for windows of a year or more only (same rule as TWR)."""
    return annualize(real, days)


def cumulative_inflation(daily: pd.DataFrame, start: pd.Timestamp) -> pd.Series:
    """Price rise since `start`, per day from `start` on (NaN-free; empty when the level at start is unknown)."""
    base = daily["level"].asof(start)
    if pd.isna(base):
        return pd.Series(dtype=float)
    window = daily["level"][daily.index >= start]
    return (window / base - 1).dropna()


def todays_zloty(values: pd.Series, daily: pd.DataFrame) -> pd.Series:
    """Express a value series in the złoty of its last day: value_t * level_last / level_t.

    Days before the CPI starts are dropped.
    """
    levels = daily["level"].reindex(values.index)
    latest = levels.iloc[-1]
    return (values * latest / levels).dropna()


def estimated_months(levels: pd.Series, as_of: pd.Timestamp) -> int:
    """How many months up to and including `as_of`'s month have no published CPI yet."""
    if levels.empty:
        return 0
    last = levels.index[-1]
    current = as_of.to_period("M").to_timestamp()
    return max(0, (current.year - last.year) * 12 + current.month - last.month)
