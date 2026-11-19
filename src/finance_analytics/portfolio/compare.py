"""Instruments, asset classes and references side by side (D-086). Pure functions of their inputs.

Every portfolio series is a part of the portfolio (`slicing.Slice`, D-085) measured as a portfolio of its own: its
daily value in PLN and its own flows, so its cumulative TWR is the market's move on what was held, whatever was
bought or sold. A series is drawn only on the days it holds something, plus the day before each holding starts, so
a line bought within the period starts at 0% of that day; after a full sale it breaks and a repurchase continues
from the same level (TWR does not change while nothing is held).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd

from finance_analytics.portfolio.returns import MIN_CAPITAL, drawdown, twr_index
from finance_analytics.portfolio.slicing import Slice, part_flows
from finance_analytics.portfolio.valuation import Valuation


@dataclass(frozen=True)
class Line:
    """One series within a period: what the chart draws and the row of the table under it."""

    twr: pd.Series  # cumulative TWR from the period's first day; NaN on days it is not drawn
    value: pd.Series  # value in PLN per day (0 while nothing is held); empty for the S&P 500
    total_twr: float | None  # over the period; None when nothing was held in it
    result: float | None  # PLN: end value − start value − net flows in between; None for the S&P 500
    max_drawdown: float | None
    end_value: float | None

    @property
    def held(self) -> bool:
        return self.total_twr is not None


def series_line(values: pd.Series, flows: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> Line:
    """One part of the portfolio from its daily values and its flows (date -> PLN, deposit +)."""
    flows = flows.groupby(level=0).sum() if len(flows) else pd.Series(dtype=float)
    index = twr_index(values, flows)
    window = (index.index >= start) & (index.index <= end)
    held = values > MIN_CAPITAL
    drawn = (held | held.shift(-1, fill_value=False))[window]
    if not drawn.any():
        return Line(pd.Series(float("nan"), index=index.index[window]), values[window], None, None, None, None)
    base = index.asof(start) if start > index.index[0] else 1.0
    rebased = index[window] / base
    from_start = start <= values.index[0]
    start_value = 0.0 if from_start else float(values.asof(start))
    inside = flows[(flows.index >= start if from_start else flows.index > start) & (flows.index <= end)]
    end_value = float(values.asof(end))
    return Line(
        twr=(rebased - 1).where(drawn),
        value=values[window],
        total_twr=float(rebased.iloc[-1] - 1),
        result=end_value - start_value - float(inside.sum()),
        max_drawdown=drawdown(rebased).max_drawdown,
        end_value=end_value,
    )


def compare_parts(v: Valuation, parts: Mapping[str, Slice], start: pd.Timestamp, end: pd.Timestamp) -> dict[str, Line]:
    """Every part (name -> slice; an empty slice is the whole portfolio) within [start, end]. The parts' flows are
    worked out once for all of them."""
    calendar = v.total.index
    if calendar.empty:
        return {}
    flows = part_flows(v) if any(part.active for part in parts.values()) else None
    lines = {}
    for name, part in parts.items():
        if part.active:
            daily = v.daily[part.mask(v.daily)]
            values = daily.groupby("date")["value_pln"].sum().reindex(calendar, fill_value=0.0)
            kept = flows[part.mask(flows)]
            part_series = kept.groupby("date")["amount_pln"].sum()
        else:
            values = v.total
            part_series = v.flows.groupby("date")["amount_pln"].sum()
        lines[name] = series_line(values.astype(float), part_series, start, end)
    return lines


def index_line(index_pln: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> Line | None:
    """A reference index (the S&P 500 in PLN, D-080) from the period's first day; None without a close in it."""
    window = index_pln[(index_pln.index >= start) & (index_pln.index <= end)].dropna()
    if window.empty:
        return None
    base = index_pln[index_pln.index <= start].dropna()
    rebased = window / (base.iloc[-1] if not base.empty else window.iloc[0])
    return Line(twr=(rebased - 1).reindex(index_pln.index[(index_pln.index >= start) & (index_pln.index <= end)]),
                value=pd.Series(dtype=float), total_twr=float(rebased.iloc[-1] - 1), result=None,
                max_drawdown=drawdown(rebased).max_drawdown, end_value=None)


def intraday_parts(rows: pd.DataFrame, parts: Mapping[str, Slice]) -> pd.DataFrame:
    """Within one day (`Intraday.rows`, D-070): the value of every part every 5 minutes (columns: names)."""
    frame = {}
    for name, part in parts.items():
        kept = rows[part.mask(rows)] if part.active else rows
        frame[name] = kept.groupby("ts")["value_pln"].sum()
    out = pd.DataFrame(frame)
    times = rows["ts"].drop_duplicates().sort_values()
    return out.reindex(times.to_numpy()).fillna(0.0) if len(times) else out


def intraday_twr(values: pd.DataFrame, bases: Mapping[str, float]) -> pd.DataFrame:
    """Each part's change over its base close; a part with nothing at that close (bought today) is measured from
    its first moment, and a part with nothing today is left out (NaN)."""
    out = {}
    for name in values.columns:
        series = values[name]
        base = bases.get(name) or 0.0
        if base <= MIN_CAPITAL:
            base = float(series.iloc[0]) if len(series) else 0.0
        out[name] = series / base - 1 if base > MIN_CAPITAL and (series > MIN_CAPITAL).any() else series * float("nan")
    return pd.DataFrame(out, index=values.index)
