"""Inflation-adjusted returns from the GUS consumer price index (D-025, R-004).

- The price level is chained from the published month-on-month indices (100.3 = +0.3%)
  and set to 100 at the first month. Only ratios of levels matter, so the base is arbitrary.
- The level is a monthly step: every day of a month has that month's level. GUS publishes a
  month in the middle of the next one, so the newest days fall in months with no data yet;
  they extrapolate the last published y/y inflation, spread evenly over months (D-041), and
  are flagged as estimated.
- Real return of a window: (1 + nominal) / (1 + inflation) - 1 (the Fisher relation, exact).
- Value in today's zloty: value_t * level_latest / level_t.
- Real profit (D-041): value today minus every deposit and withdrawal restated in today's
  złoty, so "how much more can I buy than with the money I put in".
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from finance_analytics.portfolio.returns import annualize, period_xirr


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


def monthly_trend(yoy: pd.Series) -> float:
    """Monthly price rise implied by the latest published y/y index (105.0 -> 1.05 ** (1/12) - 1); 0 without one."""
    yoy = yoy.dropna()
    if yoy.empty:
        return 0.0
    return float((yoy.sort_index().iloc[-1] / 100) ** (1 / 12) - 1)


def daily_levels(levels: pd.Series, days: pd.DatetimeIndex, monthly_rate: float = 0.0) -> pd.DataFrame:
    """Level for each day (its month's level) and whether that month is not published yet.

    Columns: `level` (NaN before the first month) and `estimated` (the month is after the last
    published one). Months after the last published one grow by `monthly_rate` a month from the
    last known level (0 carries it forward unchanged).
    """
    months = days.to_period("M").to_timestamp()
    if levels.empty:
        return pd.DataFrame({"level": float("nan"), "estimated": True}, index=days)
    last = levels.index[-1]
    later = months.unique()[months.unique() > last]
    if len(later):
        ahead = [(m.year - last.year) * 12 + m.month - last.month for m in later]
        levels = pd.concat([levels, pd.Series([levels.iloc[-1] * (1 + monthly_rate) ** k for k in ahead], index=later)])
    level = levels.reindex(levels.index.union(months.unique())).ffill().reindex(months)
    return pd.DataFrame({"level": level.to_numpy(), "estimated": months > last}, index=days)


def daily_from_cpi(cpi: pd.DataFrame, days: pd.DatetimeIndex) -> tuple[pd.Series, pd.DataFrame]:
    """Monthly levels and daily levels from the CPI table (`month`, `mom`, `yoy`), with the y/y extrapolation."""
    table = cpi.set_index("month")
    levels = price_level_index(table["mom"])
    return levels, daily_levels(levels, days, monthly_trend(table["yoy"]))


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


def level_on(daily: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.Series:
    """Level on each date (the latest day of `daily` on or before it); NaN before the CPI starts."""
    return pd.Series(daily["level"].asof(pd.DatetimeIndex(dates)).to_numpy(), index=dates)


def in_todays_zloty(amounts: pd.Series, daily: pd.DataFrame, as_of: pd.Timestamp) -> pd.Series:
    """Restate dated amounts in the złoty of `as_of`: amount_t * level(as_of) / level(t). NaN where unknown."""
    if amounts.empty:
        return amounts.astype(float)
    return amounts * daily["level"].asof(as_of) / level_on(daily, amounts.index)


@dataclass(frozen=True)
class RealProfit:
    invested: float  # start value plus net flows, each in the złoty of the end day
    profit: float  # end value minus `invested`
    pct: float | None  # profit / invested; None when nothing was invested


def real_profit(values: pd.Series, flows: pd.Series, daily: pd.DataFrame,
                start: pd.Timestamp | None, end: pd.Timestamp) -> RealProfit | None:
    """Profit after inflation: end value minus the money put in, restated in the złoty of `end`.

    With `start` None it covers the whole history (every flow up to `end`); otherwise the value on
    `start` counts as money put in on that day and only flows after it count (the D-022 window).
    None when a needed price level is unknown (the CPI starts later than a flow).
    """
    if start is None:
        put_in = flows[flows.index <= end]
    else:
        put_in = flows[(flows.index > start) & (flows.index <= end)]
        start_value = float(values.asof(start)) if start >= values.index[0] else 0.0
        if start_value:
            put_in = pd.concat([pd.Series([start_value], index=[start]), put_in])
    restated = in_todays_zloty(put_in, daily, end)
    if restated.isna().any() or pd.isna(daily["level"].asof(end)):
        return None
    invested = float(restated.sum())
    profit = float(values.asof(end)) - invested
    return RealProfit(invested, profit, profit / invested if invested > 0 else None)


def real_xirr(values: pd.Series, flows: pd.Series, daily: pd.DataFrame,
              start: pd.Timestamp, end: pd.Timestamp) -> float | None:
    """XIRR of the window with every cash flow and value restated in the złoty of `end` (D-022 rules)."""
    real_values = todays_zloty(values[values.index <= end], daily)
    if real_values.empty or real_values.index[0] > max(start, values.index[0]):
        return None
    inside = flows[(flows.index > start) & (flows.index <= end)]
    real_flows = in_todays_zloty(inside, daily, end)
    if real_flows.isna().any():
        return None
    return period_xirr(real_values, real_flows, start, end)


def real_return_with_payouts(value: float, deposits: pd.Series, payouts: pd.Series, daily: pd.DataFrame,
                             as_of: pd.Timestamp) -> float | None:
    """Real return of a holding: (value + payouts received) / deposits - 1, all in the złoty of `as_of`.

    Used for bonds (D-041): a coupon paid out is part of the return, so it is added back.
    """
    paid_in = in_todays_zloty(deposits, daily, as_of)
    paid_out = in_todays_zloty(payouts, daily, as_of)
    if paid_in.isna().any() or paid_out.isna().any() or paid_in.sum() <= 0:
        return None
    return float((value + paid_out.sum()) / paid_in.sum() - 1)
