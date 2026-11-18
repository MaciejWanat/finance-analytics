"""The portfolio during one day, every 5 minutes, for the "1D" range (D-070). Pure functions of their inputs.

The day's holdings are the rows of the daily valuation (`Valuation.daily`) on that day. Each row moves with its
instrument's price and its currency's rate *relative to the end of the window*:

    value(t) = value at the end of the day x price(t) / price(end) x rate(t) / rate(end)

so the last point is exactly the daily valuation, and so the "Dzisiaj" tile. Before an exchange opens, its
instruments stay at the last price before (the previous close); bonds and cash in PLN stay flat; cash in a
foreign currency moves with the rate only. An instrument without intraday quotes stays flat and is reported.
Simplification: the holdings at the end of the day apply all day, so a trade during the day makes no jump.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from finance_analytics.market.hours import NEW_YORK, closing_time, previous_trading_day
from finance_analytics.portfolio.valuation import Valuation

STEP = "5min"
FX_TICKER = "{currency}PLN=X"


@dataclass(frozen=True)
class DayWindow:
    """The span of one "1D" chart: from `start` to `end` (aware), measured from the close of `base`."""

    day: pd.Timestamp  # the day in the daily valuation (the "Dzisiaj" tile's day or session)
    base: pd.Timestamp  # the daily close it is compared with
    start: datetime
    end: datetime  # the end of the day, or now while it lasts
    until: datetime  # the end of the day even while it lasts: the chart's x-axis runs to here


def day_window(day: pd.Timestamp, *, by_us_session: bool, now: datetime) -> DayWindow:
    """Calendar day: midnight to midnight (local). US session (D-067): from the previous session's close to the end
    of the session's calendar day, so moves between sessions count towards it, as on the tile."""
    local = now.astimezone().tzinfo
    midnight = datetime.combine(day.date(), datetime.min.time(), tzinfo=local)
    until = midnight + timedelta(days=1)
    if by_us_session:
        base = previous_trading_day(day.date())
        start = datetime.combine(base, closing_time(base), tzinfo=NEW_YORK).astimezone(local)
    else:
        base, start = (day - pd.Timedelta(days=1)).date(), midnight
    return DayWindow(day, pd.Timestamp(base), start, min(now.astimezone(local), until), until)


@dataclass
class Intraday:
    # long: ts (aware, local), account, kind, symbol, asset_class, currency, value_pln; fx_pln: the foreign rows'
    # value moved by the rate only; px_pln / rate_pln: every row moved by its price only / its rate only
    rows: pd.DataFrame
    missing: list[str] = field(default_factory=list)  # instruments without intraday quotes (kept flat)

    @property
    def total(self) -> pd.Series:
        return self.rows.groupby("ts")["value_pln"].sum()

    @property
    def fx_part(self) -> pd.Series:
        """What the foreign holdings gained or lost on exchange rates alone since the window start (PLN)."""
        series = self.rows.groupby("ts")["fx_pln"].sum()
        return series - series.iloc[0] if len(series) else series

    def split(self) -> pd.DataFrame:
        """Return since the window start, split like the daily attribution (D-023): total, price (instrument prices
        alone), fx (exchange rates alone) and other (what is left: the two moving together)."""
        sums = self.rows.groupby("ts")[["value_pln", "px_pln", "rate_pln"]].sum()
        if sums.empty:
            return pd.DataFrame(columns=["total", "price", "fx", "other"])
        growth = sums / sums.iloc[0]
        other = growth["value_pln"] / (growth["px_pln"] * growth["rate_pln"])
        return pd.DataFrame({"total": growth["value_pln"], "price": growth["px_pln"], "fx": growth["rate_pln"],
                             "other": other}) - 1

    def by(self, column: str) -> pd.DataFrame:
        """Value per part (account, asset class, symbol, currency): moments x parts."""
        return self.rows.pivot_table(index="ts", columns=column, values="value_pln", aggfunc="sum").fillna(0.0)


def _ratios(quotes: pd.DataFrame, columns: list[str], times: pd.DatetimeIndex) -> pd.DataFrame:
    """price(t) / price(end) per column at `times` (UTC), from the last quote at or before each moment; 1.0 where
    nothing is known."""
    if quotes.empty or not columns:
        return pd.DataFrame(1.0, index=times, columns=columns)
    known = quotes.reindex(columns=columns)
    asof = known.reindex(known.index.union(times)).sort_index().ffill().reindex(times)
    asof = asof.bfill()  # before the first quote: the earliest one known (rare: bars cover 5 days)
    return (asof / asof.iloc[-1]).fillna(1.0)


def intraday_values(v: Valuation, window: DayWindow, quotes: pd.DataFrame) -> Intraday:
    """`quotes`: UTC moments x tickers (prices in the main unit, FX as 'USDPLN=X'), e.g. `intraday.read_intraday`."""
    rows = v.daily[v.daily["date"] == window.day].copy()
    if rows.empty:
        return Intraday(pd.DataFrame(columns=["ts", "account", "kind", "symbol", "asset_class", "currency",
                                              "value_pln", "fx_pln", "px_pln", "rate_pln"]))
    start, end = pd.Timestamp(window.start).tz_convert("UTC"), pd.Timestamp(window.end).tz_convert("UTC")
    times = pd.date_range(start.ceil(STEP), end, freq=STEP)
    times = times.union(pd.DatetimeIndex([start, end])).unique()

    tickers = v.lots.drop_duplicates("symbol").set_index("symbol")["ticker"]
    rows["ticker"] = rows["symbol"].map(tickers).where(rows["kind"] == "position")
    held = sorted(t for t in rows["ticker"].dropna().unique())
    currencies = sorted(c for c in rows["currency"].dropna().unique() if c != "PLN")
    fx_columns = [FX_TICKER.format(currency=c) for c in currencies]
    quotes = quotes if not quotes.empty else pd.DataFrame()
    price = _ratios(quotes, held, times)
    rate = _ratios(quotes, fx_columns, times)
    rate.columns = currencies
    missing = sorted(set(rows.loc[rows["ticker"].isin([t for t in held if quotes.empty or t not in quotes.columns
                                                       or quotes[t].dropna().empty]), "symbol"]))

    # Every row times every moment at once (rows x moments), laid out row by row: a frame per row cost a
    # millisecond each, on every live redraw of 1D (D-071).
    ones = np.ones(len(times))
    p = np.vstack([price[t].to_numpy() if isinstance(t, str) else ones for t in rows["ticker"]])
    in_rate = rows["currency"].isin(rate.columns).to_numpy()
    r = np.vstack([rate[c].to_numpy() if ok else ones for c, ok in zip(rows["currency"], in_rate, strict=True)])
    value = rows["value_pln"].to_numpy(dtype=float)[:, None]
    n = len(times)

    def each(column: str) -> np.ndarray:
        return np.repeat(rows[column].to_numpy(), n)

    frame = pd.DataFrame({
        "ts": times.tz_convert(window.start.tzinfo)[np.tile(np.arange(n), len(rows))],
        "account": each("account"), "kind": each("kind"), "symbol": each("symbol"),
        "asset_class": each("asset_class"), "currency": each("currency"),
        "value_pln": (value * p * r).ravel(),
        "fx_pln": np.where(in_rate[:, None], value * r, 0.0).ravel(),
        "px_pln": (value * p).ravel(), "rate_pln": (value * r).ravel(),
    })
    return Intraday(frame, missing)
