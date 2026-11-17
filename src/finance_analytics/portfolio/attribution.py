"""Split the PLN return into stock prices, currencies and the rest (R-002, D-023).

Per instrument and day, with the quantity held overnight q_{t-1}, the price P (in the
instrument's currency) and the NBP rate X (PLN per unit):

    PLN gain = q·(P_t·X_t − P_{t-1}·X_{t-1})
             = q·(P_t − P_{t-1})·X_{t-1}      <- price effect ("akcje")
             + q·P_t·(X_t − X_{t-1})          <- currency effect ("waluty")

Cash held in a foreign currency adds only a currency effect. Everything else that
changes the value without being a deposit (dividends, interest, taxes, fees, the gap
between a purchase price and that day's close) is "other".

Daily returns of the three parts multiply exactly into the daily TWR:

    (1 + r_PLN) = (1 + r_price) · (1 + r_fx) · (1 + r_other)

which, without "other", is the requested (1 + r_PLN) = (1 + r_local) · (1 + r_FX).
Chained over a window, the cumulative parts multiply into the window's TWR.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from finance_analytics.portfolio.valuation import Valuation

PARTS = ("price", "fx", "other")


@dataclass(frozen=True)
class Attribution:
    daily: pd.DataFrame  # date x [price, fx, other, total]: daily returns
    cumulative: pd.DataFrame  # same columns, compounded over the window
    by_instrument: pd.DataFrame  # symbol, name, currency, pnl_price, pnl_fx, pnl_total, price_change, fx_change
    by_currency: pd.DataFrame  # currency, pnl_fx (positions + cash), fx_change


def _pnl_tables(v: Valuation) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict, dict, pd.DataFrame]:
    """Daily price and FX gains in PLN per symbol, and FX gains on cash per currency."""
    calendar = v.total.index
    positions = v.daily[v.daily["kind"] == "position"]
    qty = positions.pivot_table(index="date", columns="symbol", values="qty", aggfunc="sum")
    qty = qty.reindex(calendar).fillna(0.0)
    symbol_ticker = dict(zip(v.lots["symbol"], v.lots["ticker"], strict=True))
    symbol_currency = positions.drop_duplicates("symbol").set_index("symbol")["currency"].to_dict()

    priced = [s for s in qty.columns if symbol_ticker.get(s) in v.prices.columns]
    price = pd.DataFrame({s: v.prices[symbol_ticker[s]] for s in priced}, index=calendar)
    fx = pd.DataFrame(
        {s: v.fx[symbol_currency[s]] if symbol_currency.get(s) in v.fx.columns else 1.0 for s in priced},
        index=calendar,
    )
    held = qty[priced].shift(1).fillna(0.0)
    pnl_price = (held * (price - price.shift(1)) * fx.shift(1)).fillna(0.0)
    pnl_fx = (held * price * (fx - fx.shift(1))).fillna(0.0)

    cash = v.daily[v.daily["kind"] == "cash"].pivot_table(index="date", columns="currency", values="qty",
                                                         aggfunc="sum")
    cash = cash.reindex(calendar).fillna(0.0)
    cash_fx = pd.DataFrame(
        {c: cash[c].shift(1).fillna(0.0) * (v.fx[c] - v.fx[c].shift(1)) for c in cash.columns if c in v.fx.columns},
        index=calendar,
    ).fillna(0.0)
    return pnl_price, pnl_fx, cash_fx, symbol_currency, symbol_ticker, qty


def fx_pnl(v: Valuation) -> pd.DataFrame:
    """Daily currency gain or loss in PLN, date x currency, positions and foreign cash together (D-059).

    Per day: what was held overnight, valued in its own currency, times the change of the NBP rate.
    Summed from a purchase to today this is exactly "today's rate vs the rate on the purchase day";
    after a sale it keeps the realised part. PLN holdings add nothing.
    """
    _, pnl_fx, cash_fx, symbol_currency, _, _ = _pnl_tables(v)
    by_currency = pnl_fx.T.groupby(pd.Series(symbol_currency)).sum().T if not pnl_fx.empty else pd.DataFrame(
        index=v.total.index)
    combined = by_currency.add(cash_fx, fill_value=0.0).fillna(0.0)
    return combined.drop(columns=["PLN"], errors="ignore")


def attribute(v: Valuation, start: pd.Timestamp, end: pd.Timestamp) -> Attribution:
    pnl_price, pnl_fx, cash_fx, symbol_currency, symbol_ticker, qty = _pnl_tables(v)
    values = v.total
    flows = v.flows.groupby("date")["amount_pln"].sum().reindex(values.index, fill_value=0.0)
    base = values.shift(1).fillna(0.0) + flows
    total = (values / base - 1).where(base > 0, 0.0)

    r_price = (pnl_price.sum(axis=1) / base).where(base > 0, 0.0)
    r_fx_add = ((pnl_fx.sum(axis=1) + cash_fx.sum(axis=1)) / base).where(base > 0, 0.0)
    r_fx = (1 + r_price + r_fx_add) / (1 + r_price) - 1
    r_other = (1 + total) / ((1 + r_price) * (1 + r_fx)) - 1
    daily = pd.DataFrame({"price": r_price, "fx": r_fx, "other": r_other, "total": total})

    window = (daily.index > start) & (daily.index <= end)
    cumulative = (1 + daily[window]).cumprod() - 1

    def window_sum(frame: pd.DataFrame) -> pd.Series:
        return frame[window].sum() if not frame.empty else pd.Series(dtype=float)

    price_sum, fx_sum = window_sum(pnl_price), window_sum(pnl_fx)
    rows = []
    for symbol in price_sum.index:
        if abs(price_sum[symbol]) < 0.005 and abs(fx_sum[symbol]) < 0.005:
            continue  # not held in the window
        ticker = symbol_ticker[symbol]
        currency = symbol_currency.get(symbol)
        series = v.prices[ticker]
        # Changes are measured over the part of the window the instrument was actually held.
        held_days = qty.index[(qty[symbol] > 0) & (qty.index >= start) & (qty.index <= end)]
        since = max(start, held_days[0]) if len(held_days) else start
        until = min(end, held_days[-1] + pd.Timedelta(days=1)) if len(held_days) else end
        rows.append({
            "symbol": symbol,
            "currency": currency,
            "pnl_price": price_sum[symbol],
            "pnl_fx": fx_sum[symbol],
            "pnl_total": price_sum[symbol] + fx_sum[symbol],
            "price_change": series.asof(until) / series.asof(since) - 1 if series.asof(since) else None,
            "fx_change": (v.fx[currency].asof(until) / v.fx[currency].asof(since) - 1)
            if currency in v.fx.columns and currency != "PLN" else 0.0,
        })
    by_instrument = pd.DataFrame(rows, columns=["symbol", "currency", "pnl_price", "pnl_fx", "pnl_total",
                                                "price_change", "fx_change"])
    names = v.daily.drop_duplicates("symbol").set_index("symbol")["name"]
    by_instrument.insert(1, "name", by_instrument["symbol"].map(names))
    by_instrument = by_instrument.sort_values("pnl_total", ascending=False, ignore_index=True)

    fx_by_currency = by_instrument.groupby("currency")["pnl_fx"].sum().add(window_sum(cash_fx), fill_value=0.0)
    fx_by_currency = fx_by_currency.drop("PLN", errors="ignore")
    by_currency = pd.DataFrame({
        "currency": fx_by_currency.index,
        "pnl_fx": fx_by_currency.to_numpy(),
        "fx_change": [v.fx[c].asof(end) / v.fx[c].asof(start) - 1 if c in v.fx.columns else None
                      for c in fx_by_currency.index],  # None: no NBP rates for that currency yet
    })
    return Attribution(daily=daily, cumulative=cumulative, by_instrument=by_instrument, by_currency=by_currency)
