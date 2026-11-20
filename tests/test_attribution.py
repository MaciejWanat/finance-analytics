"""Stock vs currency split of the PLN return, on hand-computed cases."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from test_valuation import D, lot, make_inputs

from finance_analytics.portfolio.attribution import attribute, fx_pnl
from finance_analytics.portfolio.valuation import value_portfolio

FX = [("USD", D("2026-01-05"), 4.0), ("USD", D("2026-01-06"), 4.0), ("USD", D("2026-01-07"), 4.4)]
PRICES = [("NVDA", D("2026-01-05"), 100.0), ("NVDA", D("2026-01-06"), 110.0), ("NVDA", D("2026-01-07"), 110.0)]
LEDGER = [("usd", D("2026-01-05"), "DEPOSIT", 1000.0), ("usd", D("2026-01-05"), "BUY", -1000.0),
          ("usd", D("2026-01-07"), "DIVIDEND", 5.0)]
START, END = D("2026-01-05"), D("2026-01-07")


def test_price_then_currency_then_dividend():
    # Day 6: price +10% at an unchanged rate -> 400 zł from the stock.
    # Day 7: rate +10% at an unchanged price -> 440 zł from the currency; a 5 USD dividend is "other".
    v = value_portfolio(make_inputs(lots=[lot()], ledger=LEDGER, prices=PRICES, fx=FX), date(2026, 1, 7))
    a = attribute(v, START, END)

    day6, day7 = a.daily.loc[D("2026-01-06")], a.daily.loc[D("2026-01-07")]
    assert (day6["price"], day6["fx"], day6["other"]) == pytest.approx((0.10, 0.0, 0.0))
    assert day7["price"] == pytest.approx(0.0) and day7["fx"] == pytest.approx(0.10)
    assert day7["other"] == pytest.approx(4862 / 4400 / 1.1 - 1)  # 22 zł dividend on 4400 zł

    final = a.cumulative.iloc[-1]
    assert (1 + final["price"]) * (1 + final["fx"]) * (1 + final["other"]) == pytest.approx(1 + final["total"])
    assert final["total"] == pytest.approx(4862 / 4000 - 1)

    nvda = a.by_instrument.set_index("symbol").loc["NVDA.US"]
    assert (nvda["pnl_price"], nvda["pnl_fx"], nvda["pnl_total"]) == pytest.approx((400.0, 440.0, 840.0))
    assert (nvda["price_change"], nvda["fx_change"]) == pytest.approx((0.10, 0.10))
    assert a.by_currency.set_index("currency").loc["USD", "pnl_fx"] == pytest.approx(440.0)


def test_foreign_cash_has_only_a_currency_effect():
    ledger = [("usd", D("2026-01-05"), "DEPOSIT", 1000.0)]
    v = value_portfolio(make_inputs(ledger=ledger, fx=FX), date(2026, 1, 7))
    a = attribute(v, START, END)
    final = a.cumulative.iloc[-1]
    assert final["price"] == pytest.approx(0.0) and final["fx"] == pytest.approx(0.10)
    assert final["other"] == pytest.approx(0.0, abs=1e-12)
    assert a.by_instrument.empty
    assert a.by_currency.set_index("currency").loc["USD", "pnl_fx"] == pytest.approx(400.0)


def test_pln_stock_has_no_currency_effect():
    pln_lot = ("pln", 1, "PKN.PL", "Orlen", "stock", "PKN.WA", 10.0, D("2026-01-05"), None, 60.0, 600.0)
    prices = [("PKN.WA", D("2026-01-05"), 60.0), ("PKN.WA", D("2026-01-07"), 66.0)]
    v = value_portfolio(make_inputs(lots=[pln_lot], prices=prices, fx=FX, currencies={"PKN.WA": "PLN"}),
                        date(2026, 1, 7))
    row = attribute(v, START, END).by_instrument.set_index("symbol").loc["PKN.PL"]
    assert row["pnl_price"] == pytest.approx(60.0) and row["pnl_fx"] == pytest.approx(0.0)
    assert row["fx_change"] == 0.0


def test_currency_without_nbp_rates_does_not_break_the_split():
    # Prices cached but the NBP download for USD failed: values are missing, the split must not raise.
    v = value_portfolio(make_inputs(lots=[lot()], ledger=LEDGER, prices=PRICES), date(2026, 1, 7))
    a = attribute(v, START, END)
    assert a.by_currency["fx_change"].isna().all()


def test_fx_pnl_is_the_daily_currency_gain_in_pln():
    """D-059: shares and foreign cash, rate change times what was held overnight, per currency."""
    stock = fx_pnl(value_portfolio(make_inputs(lots=[lot()], ledger=LEDGER, prices=PRICES, fx=FX), date(2026, 1, 7)))
    assert list(stock.columns) == ["USD"] and stock["USD"].sum() == pytest.approx(440.0)  # 1100 USD x +0.4
    assert stock.loc[D("2026-01-06"), "USD"] == pytest.approx(0.0)  # price moved, the rate did not
    cash = fx_pnl(value_portfolio(make_inputs(ledger=[("usd", D("2026-01-05"), "DEPOSIT", 1000.0)], fx=FX),
                                  date(2026, 1, 7)))
    assert cash["USD"].sum() == pytest.approx(400.0)


def test_daily_sources_split_the_day_into_market_and_currency_and_leave_the_dividend():
    # Same case: day 6 is 400 zł from the price, day 7 is 440 zł from the rate; the 22 zł dividend is left out,
    # so with the rest the parts add up to the day's result.
    from finance_analytics.portfolio.attribution import daily_sources
    from finance_analytics.portfolio.today import Today, day_breakdown

    v = value_portfolio(make_inputs(lots=[lot()], ledger=LEDGER, prices=PRICES, fx=FX), date(2026, 1, 7))
    sources = daily_sources(v)
    assert tuple(sources.loc[D("2026-01-06")]) == pytest.approx((400.0, 0.0, 0.0))
    assert tuple(sources.loc[D("2026-01-07")]) == pytest.approx((0.0, 0.0, 440.0))

    day = D("2026-01-07")
    amount = float(v.total[day] - v.total[D("2026-01-06")])
    parts = day_breakdown(sources, Today(day, (amount, 0.0), pd.Series(dtype=float), D("2026-01-06"), day))
    assert (parts["market"], parts["fx"], parts["other"]) == pytest.approx((0.0, 440.0, 22.0))
    assert parts.sum() == pytest.approx(amount)
    assert day_breakdown(sources, Today(day, None, pd.Series(dtype=float))) is None
