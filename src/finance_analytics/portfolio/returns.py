"""Return metrics on top of the daily valuation (D-022).

- TWR (time-weighted return): daily sub-period returns chained,
  r_t = V_t / (V_{t-1} + F_t) - 1, with external flows F_t (deposits +, withdrawals -)
  treated as arriving at the start of day t. Independent of when money was added,
  so it measures the investments, not the saver.
- XIRR (money-weighted return): the annual rate that discounts all external flows
  plus the start and end value to zero. It measures the investor's own experience.
- Drawdown: fall of the TWR index below its running peak (deposits cannot hide losses).

All amounts are in PLN; flows are deposits and withdrawals only (buys, sells,
dividends and taxes are internal to the portfolio).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import pandas as pd

DAYS_PER_YEAR = 365.25


# ------------------------------------------------------------------------------------ TWR


MIN_CAPITAL = 0.01  # PLN; less than a grosz of capital is rounding noise, not money at risk (D-062)
MIN_DEPOSITS = 1.0  # PLN; profit vs deposits is meaningless below this (D-062)


def daily_returns(values: pd.Series, flows: pd.Series) -> pd.Series:
    """Daily TWR sub-period returns. `values`: daily value; `flows`: external flow per day."""
    flows = flows.groupby(level=0).sum().reindex(values.index, fill_value=0.0)
    base = values.shift(1).fillna(0.0) + flows
    returns = values / base - 1
    # No capital at risk: no return. "Capital" below a grosz is rounding noise, e.g. a deposit and a
    # withdrawal of the same amount on one day that sum to 1e-13 instead of 0 (D-062).
    return returns.where(base > MIN_CAPITAL, 0.0)


def twr_index(values: pd.Series, flows: pd.Series) -> pd.Series:
    """Growth of 1 PLN invested at the start (1.0 = break-even)."""
    return (1 + daily_returns(values, flows)).cumprod()


def period_return(index: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> float:
    """Return between two days from a growth index (start day's close to end day's close)."""
    first = index.asof(start) if start > index.index[0] else 1.0
    return float(index.asof(end) / first - 1)


def change_since(
    values: pd.Series, flows: pd.Series, base: pd.Timestamp, end: pd.Timestamp | None = None
) -> tuple[float, float] | None:
    """Result from the close of `base` to the close of `end` (default: the last day), e.g. since the
    previous session (D-063, D-067).

    (PLN, return): the PLN amount is the change of value minus deposits plus withdrawals made after
    `base`; the return chains the daily TWR sub-periods over the same days, so a deposit is not a
    gain. None when there is no close at `base` (it is before the first day).
    """
    if values.empty or base < values.index[0]:
        return None
    end = values.index[-1] if end is None else end
    added = flows[(flows.index > base) & (flows.index <= end)].sum()
    amount = float(values.asof(end) - values.asof(base) - added)
    index = twr_index(values, flows)
    start = index.asof(base)
    return amount, float(index.asof(end) / start - 1) if start > 0 else 0.0


def chained_returns(returns: pd.Series, groups: pd.Series) -> pd.Series:
    """Daily returns chained within each group label, e.g. all days that count towards one session (D-067)."""
    return (1 + returns).groupby(groups.reindex(returns.index)).prod() - 1


def annualize(total_return: float, days: float) -> float | None:
    """Annualized rate; None for periods under a year (annualizing them exaggerates)."""
    if days < 365 or total_return <= -1:
        return None
    return (1 + total_return) ** (DAYS_PER_YEAR / days) - 1


# ----------------------------------------------------------------------------------- XIRR


XIRR_LOW, XIRR_HIGH = -1 + 1e-12, 1e6  # the bracket of the bisection: −100% (exclusive) to +100 000 000%


def xirr(cashflows: Sequence[tuple[date, float]], *, guess: float = 0.1) -> float | None:
    """Annual internal rate of return of dated cash flows (investor's view: money in < 0).

    Newton's method, falling back to bisection. None when there is no solution
    (all flows of one sign, or nothing to compare).
    """
    flows = [(d, a) for d, a in cashflows if a]
    if len(flows) < 2 or all(a > 0 for _, a in flows) or all(a < 0 for _, a in flows):
        return None
    t0 = min(d for d, _ in flows)
    years = [((d - t0).days / DAYS_PER_YEAR, a) for d, a in flows]

    def npv(rate: float) -> float:
        return sum(a / (1 + rate) ** t for t, a in years)

    def dnpv(rate: float) -> float:
        return sum(-t * a / (1 + rate) ** (t + 1) for t, a in years)

    rate = guess
    try:
        for _ in range(100):
            value, slope = npv(rate), dnpv(rate)
            if slope == 0:
                break
            step = value / slope
            rate -= step
            if rate <= XIRR_LOW:
                break
            if abs(step) < 1e-10:
                return rate
    except (OverflowError, ZeroDivisionError):  # Newton ran off to an extreme rate; bisection below
        pass
    # Bisection on a wide bracket: a result of a few days put on a yearly basis can be thousands of percent, or
    # almost −100% (D-084).
    low, high = XIRR_LOW, XIRR_HIGH
    try:
        f_low, f_high = npv(low), npv(high)
    except (OverflowError, ZeroDivisionError):  # decades of flows at an extreme rate: no usable answer
        return None
    if math.isnan(f_low) or math.isnan(f_high) or f_low * f_high > 0:
        return None
    for _ in range(300):
        mid = (low + high) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-9:
            return mid
        if f_low * f_mid < 0:
            high = mid
        else:
            low, f_low = mid, f_mid
    return (low + high) / 2


def period_xirr(values: pd.Series, flows: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> float | None:
    """XIRR of a window: the start value counts as money put in, the end value as money taken out."""
    start_value = float(values.asof(start)) if start >= values.index[0] else 0.0
    inside = flows[(flows.index > start) & (flows.index <= end)]
    cashflows = [(start.date(), -start_value)] if start_value else []
    cashflows += [(d.date(), -float(a)) for d, a in inside.items()]
    cashflows.append((end.date(), float(values.asof(end))))
    return xirr(cashflows)


def xirr_curve(values: pd.Series, flows: pd.Series, start: pd.Timestamp, freq: str = "W-FRI") -> pd.Series:
    """XIRR from `start` to each later day, on the last day of every `freq` period (D-083, D-084): how the annual
    rate of the period developed. A few days after `start` it is a short result put on a yearly basis, so it swings
    hard. Days without a solution are left out."""
    flows = flows.groupby(level=0).sum()
    days = values[values.index > start]
    ends = days.groupby(pd.Grouper(freq=freq)).tail(1).index if len(days) else []
    rates = {end: period_xirr(values, flows, start, end) for end in ends}
    rates = {day: rate for day, rate in rates.items() if rate is not None}
    # A date index even when empty (e.g. "1R": no point a year after the start before the last day), so callers
    # can compare it with dates.
    return pd.Series(list(rates.values()), index=pd.DatetimeIndex(list(rates)), dtype=float)


# ------------------------------------------------------------------------------- drawdown


@dataclass(frozen=True)
class Drawdown:
    series: pd.Series  # index / running peak - 1 (<= 0)
    max_drawdown: float
    peak: pd.Timestamp | None  # high before the deepest fall
    trough: pd.Timestamp | None
    recovered: pd.Timestamp | None  # first day back at the old peak, None if not yet
    current: float


def drawdown(index: pd.Series) -> Drawdown:
    peak_series = index.cummax()
    series = index / peak_series - 1
    if series.empty or series.min() >= 0:
        return Drawdown(series, 0.0, None, None, None, 0.0)
    trough = series.idxmin()
    peak = index[:trough].idxmax()
    after = index[trough:]
    back = after[after >= index[peak]]
    return Drawdown(
        series=series,
        max_drawdown=float(series.min()),
        peak=peak,
        trough=trough,
        recovered=back.index[0] if not back.empty else None,
        current=float(series.iloc[-1]),
    )


@dataclass(frozen=True)
class Underwater:
    """How far the portfolio was below the money put in (D-049): (value - deposits) / deposits."""
    series: pd.Series  # daily ratio; NaN while nothing is deposited
    worst: float | None  # lowest ratio (negative when the portfolio was ever below its deposits)
    day: pd.Timestamp | None  # when it was lowest
    profit: float | None  # value - deposits on that day, PLN
    current: float | None


def underwater(values: pd.Series, contributed: pd.Series, start: pd.Timestamp | None = None) -> Underwater:
    """Profit relative to deposits, day by day; the minimum from `start` (default: all history).

    `contributed` is the running sum of external flows (deposits minus withdrawals) in PLN.
    Example: 1000 PLN deposited, 800 at the lowest, 1200 today -> worst -20 %, current +20 %.
    """
    contributed = contributed.reindex(values.index).ffill().fillna(0.0)
    profit = values - contributed
    ratio = (profit / contributed).where(contributed > MIN_DEPOSITS)  # below 1 zł: nothing really put in
    window = ratio[ratio.index >= start] if start is not None else ratio
    window = window.dropna()
    if window.empty:
        return Underwater(ratio, None, None, None, None)
    day = window.idxmin()
    return Underwater(ratio, float(window.min()), day, float(profit[day]), float(window.iloc[-1]))


# ----------------------------------------------------------------------- calendar returns


def monthly_returns(index: pd.Series) -> pd.DataFrame:
    """TWR per calendar month: rows = years, columns = 1..12, plus a 'year' column."""
    month_end = index.resample("ME").last()
    previous = month_end.shift(1).fillna(1.0)  # the first month is measured from 1.0
    by_month = month_end / previous - 1
    table = pd.DataFrame({"year": by_month.index.year, "month": by_month.index.month, "r": by_month.to_numpy()})
    grid = table.pivot(index="year", columns="month", values="r").reindex(columns=range(1, 13))
    year_end = index.resample("YE").last()
    grid["year"] = (year_end / year_end.shift(1).fillna(1.0) - 1).to_numpy()
    return grid


# --------------------------------------------------------------------------------- report


@dataclass(frozen=True)
class Returns:
    twr: float
    twr_annual: float | None
    xirr: float | None
    drawdown: Drawdown
    index: pd.Series


def returns_for(values: pd.Series, flows: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> Returns:
    """All metrics for one series (portfolio or account) within [start, end]."""
    flows = flows.groupby(level=0).sum()
    index = twr_index(values, flows)
    window = index[(index.index >= start) & (index.index <= end)]
    base = index.asof(start) if start > index.index[0] else 1.0
    rebased = window / base if base else window
    total = period_return(index, start, end)
    return Returns(
        twr=total,
        twr_annual=annualize(total, (end - start).days),
        # An annual rate over a few weeks explodes into nonsense; like annualized TWR, XIRR
        # is reported for windows of a year or more.
        xirr=period_xirr(values, flows, start, end) if (end - start).days >= 365 else None,
        drawdown=drawdown(rebased),
        index=rebased,
    )


def position_result_trends(daily: pd.DataFrame, lots: pd.DataFrame, end: pd.Timestamp, days: int = 90) -> dict:
    """(account, symbol) -> result per day over the last `days` days: value minus the cost of the lots held that day
    (D-054). One as-of join for all positions: a lookup per position cost a millisecond each live redraw (D-071)."""
    recent = daily[(daily["kind"] == "position") & (daily["date"] > end - pd.Timedelta(days=days))]
    values = recent.groupby(["account", "symbol", "date"], as_index=False)["value_pln"].sum()
    aliases = daily.drop_duplicates("account_id").set_index("account_id")["account"]
    all_lots = lots.assign(account=lambda d: d["account_id"].map(aliases), cost=lambda d: d["cost_pln"].fillna(0.0))
    steps = pd.concat([
        all_lots[["account", "symbol", "open_date", "cost"]].rename(columns={"open_date": "date"}),
        all_lots.dropna(subset=["close_date"])[["account", "symbol", "close_date", "cost"]]
        .rename(columns={"close_date": "date"}).assign(cost=lambda d: -d["cost"]),
    ]).groupby(["account", "symbol", "date"], as_index=False)["cost"].sum()
    steps["held_cost"] = steps.groupby(["account", "symbol"])["cost"].cumsum()
    joined = pd.merge_asof(values.sort_values("date"), steps[["account", "symbol", "date", "held_cost"]]
                           .astype({"date": values["date"].dtype}).sort_values("date"),
                           on="date", by=["account", "symbol"], direction="backward")
    joined["result"] = (joined["value_pln"] - joined["held_cost"].fillna(0.0)).round(0)
    joined = joined.sort_values(["account", "symbol", "date"])
    return {key: group.tolist() for key, group in joined.groupby(["account", "symbol"])["result"]}


def position_local_results(daily: pd.DataFrame, lots: pd.DataFrame, fx: pd.DataFrame, end: pd.Timestamp) -> pd.Series:
    """(account, symbol) -> result % of each position held on `end` in the instrument's own currency, without the
    currency rate: value in that currency over the cost of the open lots in it. The cost is the PLN cost of each
    lot at the NBP rate of that currency on its opening day, the same rates the PLN figures use.

    `fx`: calendar x currency, PLN per unit (`Valuation.fx`). NaN when a cost or a rate is unknown, or not positive.
    """
    held = daily[(daily["date"] == end) & (daily["kind"] == "position")]
    keys = ["account", "symbol"]
    value = held.groupby(keys)["value_local"].sum()
    currency = held.groupby(keys)["currency"].last()
    aliases = daily.drop_duplicates("account_id").set_index("account_id")["account"]
    open_lots = lots[lots["close_date"].isna()].assign(account=lambda d: d["account_id"].map(aliases))
    open_lots = open_lots[open_lots.set_index(keys).index.isin(currency.index)]

    def rate(row) -> float:
        ccy = currency.get((row.account, row.symbol))
        if ccy == "PLN":
            return 1.0
        if ccy not in fx.columns:
            return float("nan")
        return float(fx[ccy].asof(row.open_date))

    rates = [rate(row) for row in open_lots.itertuples(index=False)]
    cost = (open_lots["cost_pln"] / pd.Series(rates, index=open_lots.index, dtype=float)).groupby(
        [open_lots["account"], open_lots["symbol"]]).sum(min_count=1)
    cost = cost.where(cost > 0)
    return (value / cost.reindex(value.index) - 1).rename("pnl_local")
