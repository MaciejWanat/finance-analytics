"""The portfolio against the S&P 500 (D-080): "Czy pobiłeś giełdę?".

The comparison is a shadow portfolio: on the first day of the period it holds the S&P 500 worth exactly what the
portfolio was worth, and every later deposit buys the index (a withdrawal sells it) on the day it happened. The gap
between the two values is what the investor's own choices earned or lost against simply buying the index with the
same money at the same times. The index is the total-return one (dividends reinvested), in PLN at NBP rates, so it
is measured like the portfolio: with dividends and with the currency.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

BENCHMARK_TICKER = "^SP500TR"  # S&P 500 Total Return (USD) on Yahoo
BENCHMARK_CURRENCY = "USD"


def index_in_pln(close: pd.Series, fx: pd.Series, calendar: pd.DatetimeIndex) -> pd.Series:
    """The index level in PLN on every day of `calendar`: the last close times the last NBP rate, carried over
    weekends and holidays. NaN before the first close or rate, and after the last close: a day the index has not
    closed yet is not compared, or the portfolio's live move would count against a level that stood still."""
    def daily(series: pd.Series) -> pd.Series:
        series = series[~series.index.duplicated(keep="last")].sort_index()
        return series.reindex(series.index.union(calendar)).ffill().reindex(calendar)
    level = daily(close) * daily(fx)
    return level[calendar <= close.index.max()].reindex(calendar) if len(close) else level


@dataclass(frozen=True)
class Comparison:
    gap: pd.Series  # portfolio value − shadow value, by day from `start` (0 on the first day)
    shadow: pd.Series  # the shadow portfolio's value, by day
    portfolio_return: float | None  # TWR of the portfolio over the period (passed in, for the text)
    index_return: float  # the index's own change over the period

    @property
    def beaten(self) -> bool:
        return float(self.gap.iloc[-1]) > 0


def compare(total: pd.Series, flows: pd.Series, index_pln: pd.Series, start: pd.Timestamp,
            portfolio_return: float | None = None) -> Comparison | None:
    """The portfolio against a shadow portfolio in the index, from `start` to the last day of `total` that the index
    has a close for.

    `flows`: deposits (+) and withdrawals (−) in PLN, indexed by date; a flow on day d is in the value of day d, so
    the shadow buys at that day's level. Flows on `start` itself are part of the starting value, as in the period
    result. None when the index has no level on `start` (not downloaded that far back).
    """
    level = index_pln.reindex(total.index)
    last = level.last_valid_index()
    total = total[(total.index >= start) & (total.index <= last)] if last is not None else total.iloc[:0]
    if total.empty:
        return None
    level = level.reindex(total.index)
    if pd.isna(level.iloc[0]) or level.iloc[0] <= 0:
        return None
    level = level.ffill()
    flows = pd.Series(flows.to_numpy(dtype=float), index=pd.DatetimeIndex(flows.index))  # also when empty
    in_window = flows[(flows.index > start) & (flows.index <= total.index[-1])]
    bought = (in_window.groupby(level=0).sum() / level.reindex(in_window.index.unique()).sort_index())
    units = float(total.iloc[0]) / float(level.iloc[0]) + bought.reindex(total.index, fill_value=0.0).cumsum()
    shadow = units * level
    return Comparison(gap=total - shadow, shadow=shadow, portfolio_return=portfolio_return,
                      index_return=float(level.iloc[-1] / level.iloc[0] - 1))
