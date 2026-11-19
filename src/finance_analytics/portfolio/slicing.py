"""A part of the portfolio (D-085): only some asset classes or instruments, measured as a portfolio of its own.

The filter keeps the daily rows that match it, and replaces the external flows (deposits and withdrawals of whole
accounts) with the flows of the part itself. Every row group, one (account, symbol), gets its own flows:

- a position: a purchase is a deposit into it and a sale a withdrawal, both worth the change of quantity at that
  day's price and rate (the same unit value its rows are valued at), so a trade day's result is the market's move
  only; a dividend leaves it as a withdrawal (the money goes to the account's cash);
- a bond series: its own purchases, coupons and redemptions (D-026);
- broker cash: the account's deposits and withdrawals, minus what its positions bought, plus what they sold and
  paid out; bank cash: its balance changes (D-027).

Summed over every row group these are exactly the external flows of the whole portfolio, so TWR, XIRR, the period
result and the comparison with the S&P 500 work on a part unchanged, and a filter that keeps everything gives the
same numbers as no filter.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import pandas as pd

from finance_analytics.portfolio.valuation import CASH_SYMBOL, Valuation

FLOW_COLUMNS = ["date", "account_id", "symbol", "asset_class", "amount_pln"]
QTY_NOISE = 1e-9  # a change of quantity below this is rounding, not a trade


@dataclass(frozen=True)
class Slice:
    """What the filter keeps: asset classes OR-ed within, instruments OR-ed within, the two AND-ed. Empty: all."""

    classes: frozenset[str] = frozenset()
    symbols: frozenset[str] = frozenset()

    @property
    def active(self) -> bool:
        return bool(self.classes or self.symbols)

    def mask(self, frame: pd.DataFrame) -> pd.Series:
        """Rows of `frame` (with `symbol` and `asset_class`) that the filter keeps."""
        keep = pd.Series(True, index=frame.index)
        if self.classes:
            keep &= frame["asset_class"].isin(self.classes)
        if self.symbols:
            keep &= frame["symbol"].isin(self.symbols)
        return keep

    def keeps(self, symbol: str, asset_class: str) -> bool:
        return (not self.classes or asset_class in self.classes) and (not self.symbols or symbol in self.symbols)


def _asset_classes(v: Valuation) -> dict[str, str]:
    classes: dict[str, str] = {CASH_SYMBOL: "cash"}
    for frame in (v.lots, v.daily):
        if {"symbol", "asset_class"} <= set(frame.columns):
            classes.update(frame.drop_duplicates("symbol").set_index("symbol")["asset_class"].to_dict())
    return classes


def _position_flows(v: Valuation, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """Purchases (+) and sales (−) of every (account, symbol) position, at the day's unit value in PLN."""
    pos = v.daily[v.daily["kind"] == "position"]
    if pos.empty or calendar.empty:
        return pd.DataFrame(columns=["date", "account_id", "symbol", "amount_pln"])
    keys = ["account_id", "symbol"]
    qty = pos.pivot_table(index="date", columns=keys, values="qty", aggfunc="sum")
    qty = qty.reindex(calendar).fillna(0.0)
    unit = pos.assign(unit=pos["value_pln"] / pos["qty"]).pivot_table(
        index="date", columns=keys, values="unit", aggfunc="mean").reindex(index=calendar, columns=qty.columns)
    # A sale that empties a position leaves no row on its day: take the market price and rate of that day, or else
    # the last unit value the position had.
    tickers = v.lots.drop_duplicates("symbol").set_index("symbol")["ticker"] if "ticker" in v.lots.columns else {}
    currencies = pos.drop_duplicates(keys, keep="last").set_index(keys)["currency"]
    for column in qty.columns:
        ticker = tickers.get(column[1]) if len(tickers) else None
        currency = currencies.get(column)
        if ticker in v.prices.columns and currency in v.fx.columns:
            market = (v.prices[ticker] * v.fx[currency]).reindex(calendar)
            unit[column] = unit[column].fillna(market)
    unit = unit.ffill()
    change = qty.diff()
    change.iloc[0] = qty.iloc[0]
    change = change.where(change.abs() > QTY_NOISE, 0.0)
    amounts = (change * unit).where(change != 0)
    amounts.index.name = "date"
    long = amounts.stack(keys, future_stack=True).rename("amount_pln").reset_index()
    return long[long["amount_pln"].notna() & (long["amount_pln"] != 0)]


def part_flows(v: Valuation) -> pd.DataFrame:
    """The flows of every row group of the portfolio (see the module docstring): date, account_id, symbol,
    asset_class, amount_pln. They sum to the portfolio's external flows."""
    calendar = v.total.index
    external = v.flows.assign(symbol=v.flows["symbol"].fillna(CASH_SYMBOL) if "symbol" in v.flows.columns
                              else CASH_SYMBOL)[["date", "account_id", "symbol", "amount_pln"]]
    trades = _position_flows(v, calendar)
    income = v.income[["date", "account_id", "symbol", "amount_pln"]]
    moves = pd.concat([trades, income.assign(amount_pln=-income["amount_pln"])], ignore_index=True)
    # What a position gains, the account's cash gives, and the other way round.
    cash_side = moves.assign(symbol=CASH_SYMBOL, amount_pln=-moves["amount_pln"])
    frames = [frame for frame in (external, moves, cash_side) if not frame.empty]
    if not frames:
        return pd.DataFrame(columns=FLOW_COLUMNS)
    flows = pd.concat(frames, ignore_index=True)
    flows["date"] = pd.to_datetime(flows["date"])
    flows = flows.groupby(["date", "account_id", "symbol"], as_index=False)["amount_pln"].sum()
    flows = flows[flows["amount_pln"].abs() > QTY_NOISE]
    classes = _asset_classes(v)
    # Only bond flows carry a symbol that may have no row left (a series redeemed before the first valued day).
    flows["asset_class"] = flows["symbol"].map(classes).fillna("bond")
    return flows[FLOW_COLUMNS].sort_values("date", kind="stable", ignore_index=True)


def slice_valuation(v: Valuation, part: Slice) -> Valuation:
    """The valuation of only what `part` keeps, with the part's own flows. `v` itself when the filter is off."""
    if not part.active:
        return v
    daily = v.daily[part.mask(v.daily)]
    flows = part_flows(v)
    flows = flows[part.mask(flows)]
    flows = flows.assign(amount=flows["amount_pln"], currency="PLN", type="PART").drop(columns="asset_class")
    lots = v.lots[part.mask(v.lots)] if {"symbol", "asset_class"} <= set(v.lots.columns) else v.lots
    classes = _asset_classes(v)
    income = v.income
    if not income.empty:
        income = income[part.mask(income.assign(asset_class=income["symbol"].map(classes)))]
    last = v.total.index[-1] if not v.total.empty else v.last_day
    return replace(v, daily=daily.reset_index(drop=True), flows=flows.reset_index(drop=True),
                   lots=lots.reset_index(drop=True), income=income.reset_index(drop=True), last_day=last)


