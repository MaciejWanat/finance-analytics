"""The "Dzisiaj" tile on Portfel: which day it shows and the result of that day (D-063, D-067).

Two ways to count a day:
- calendar day: the last market day (some price or rate moved), from the close of the day before it;
- US session (default with US instruments): each calendar day counts towards the US trading day on or after it,
  so moves between two sessions (currencies, other exchanges, a weekend) go to the next session. The tile shows
  the session that opened last: from the open on it is today's, before the open it is still the previous one,
  so the result stays after the close until the next open.

Either way a day without any moved quote (a weekend, a holiday, quotes not fetched yet) is skipped, so the tile
never shows a false +0,00 %.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from finance_analytics.market.hours import last_opened_session, previous_trading_day, session_of
from finance_analytics.portfolio.returns import chained_returns, change_since, daily_returns


@dataclass(frozen=True)
class Today:
    day: pd.Timestamp  # the day (or session) the tile describes
    change: tuple[float, float] | None  # (PLN, return) from the close before it; None without an earlier close
    per_day: pd.Series  # the return of every such day, for the sparkline
    base: pd.Timestamp | None = None  # the close the result is measured from (the day before, or the previous session)
    until: pd.Timestamp | None = None  # the close the result is measured to


def today_result(
    values: pd.Series, flows: pd.Series, moved: pd.DatetimeIndex, *, by_us_session: bool, now: datetime
) -> Today:
    """`values`: daily value; `flows`: external flows by day; `moved`: market days (`valuation.market_days`)."""
    end = values.index[-1]
    returns = daily_returns(values, flows)
    if not by_us_session:
        day = moved[-1] if len(moved) else end
        per_day = returns[returns.index.isin(moved)] if len(moved) else returns
        base = day - pd.Timedelta(days=1)
        return Today(day, change_since(values, flows, base), per_day, base, end)
    session = pd.Series([pd.Timestamp(session_of(d.date())) for d in values.index], index=values.index)
    opened = pd.Timestamp(last_opened_session(now))
    shown = sorted(s for s in set(session[session.index.isin(moved)]) if s <= opened)
    day = shown[-1] if shown else end
    base = pd.Timestamp(previous_trading_day(day.date()))
    per_day = chained_returns(returns, session)
    until = min(day, end)
    return Today(day, change_since(values, flows, base, until), per_day[per_day.index.isin(shown)], base, until)


def position_day_returns(daily: pd.DataFrame, base: pd.Timestamp | None, day: pd.Timestamp) -> pd.Series:
    """(account, symbol) -> today's return of each position held on `day`, from the close of `base`: the change
    of one unit's price in the instrument's own currency, without the currency rate (the user asked for the move
    of the instrument alone). Per unit, so a purchase or a sale that day is not a gain or a loss.

    The same day and base as the "Dzisiaj" tile (`today_result`). NaN for a position not held at `base` (bought
    since then) or without a positive unit value.
    """
    positions = daily[daily["kind"] == "position"]
    keys = ["account", "symbol"]

    def unit_value(on: pd.Timestamp | None) -> pd.Series:
        if on is None:
            return pd.Series(dtype=float)
        rows = positions[positions["date"] == on].groupby(keys)[["qty", "value_local"]].sum()
        return (rows["value_local"] / rows["qty"].where(rows["qty"] > 0)).where(lambda s: s > 0)

    now, before = unit_value(day), unit_value(base)
    return (now / before.reindex(now.index) - 1).rename("today")


def day_breakdown(sources: pd.DataFrame, tile: Today) -> pd.Series | None:
    """The tile's PLN result split by where it came from: `sources` (`attribution.daily_sources`, in the tile's
    units) summed over the tile's days, plus "other" (what they do not explain), so the parts add up to the tile.
    None without a result."""
    if tile.change is None or tile.base is None or tile.until is None:
        return None
    window = sources[(sources.index > tile.base) & (sources.index <= tile.until)]
    parts = window.sum().reindex(["market", "bonds", "fx"], fill_value=0.0)
    parts["other"] = tile.change[0] - parts.sum()
    return parts.astype(float)
