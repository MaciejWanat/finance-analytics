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
        return Today(day, change_since(values, flows, base), per_day, base)
    session = pd.Series([pd.Timestamp(session_of(d.date())) for d in values.index], index=values.index)
    opened = pd.Timestamp(last_opened_session(now))
    shown = sorted(s for s in set(session[session.index.isin(moved)]) if s <= opened)
    day = shown[-1] if shown else end
    base = pd.Timestamp(previous_trading_day(day.date()))
    per_day = chained_returns(returns, session)
    return Today(day, change_since(values, flows, base, min(day, end)), per_day[per_day.index.isin(shown)], base)
