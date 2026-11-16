"""Dividends in PLN at the NBP D-1 rate, and the PIT-38 estimate, on hand-computed cases."""

from __future__ import annotations

import pandas as pd
import pytest

from finance_analytics.portfolio.dividends import payments, per_company, per_year

D = pd.Timestamp
FX = pd.DataFrame(
    [("USD", D("2026-01-02"), 3.9), ("USD", D("2026-01-05"), 4.0), ("USD", D("2026-01-06"), 4.1),
     ("USD", D("2026-01-07"), 4.2)],
    columns=["currency", "date", "mid"],
)


def event(kind, amount, day="2026-01-07", account="usd", currency="USD", wrapper=None, symbol="AAPL.US"):
    return {"account_id": account, "account": account.upper(), "currency": currency, "tax_wrapper": wrapper,
            "date": D(day), "symbol": symbol, "name": symbol.split(".")[0], "type": kind, "amount": amount,
            "comment": None}


def test_regular_account_uses_d_minus_1_rate_and_estimates_pit():
    paid = payments(pd.DataFrame([event("DIVIDEND", 10.0), event("WHT", -1.5)]), FX)
    row = paid.iloc[0]
    assert row["rate"] == 4.1  # paid on the 7th -> NBP table of the 6th
    assert (row["gross_pln"], row["wht_pln"], row["net_pln"]) == pytest.approx((41.0, 6.15, 34.85))
    assert row["tax_due_pln"] == pytest.approx(0.19 * 41.0 - 6.15)  # 15% abroad, 4% left to pay in Poland


def test_monday_payment_uses_fridays_rate():
    paid = payments(pd.DataFrame([event("DIVIDEND", 10.0, day="2026-01-05")]), FX)
    assert paid.iloc[0]["rate"] == 3.9  # the last table before Monday is Friday's


def test_ike_pays_no_polish_tax_and_pln_account_is_not_converted():
    ike = payments(pd.DataFrame([event("DIVIDEND", 10.0, wrapper="IKE"), event("WHT", -1.5, wrapper="IKE")]), FX)
    assert ike.iloc[0]["tax_due_pln"] == 0.0
    pln = payments(pd.DataFrame([event("DIVIDEND", 40.0, account="pln", currency="PLN")]), FX)
    assert pln.iloc[0]["rate"] == 1.0 and pln.iloc[0]["gross_pln"] == 40.0
    assert pln.iloc[0]["tax_due_pln"] == pytest.approx(0.19 * 40.0)  # nothing withheld abroad


def test_withholding_above_19_percent_means_nothing_to_pay():
    paid = payments(pd.DataFrame([event("DIVIDEND", 10.0), event("WHT", -3.0)]), FX)  # 30% withheld
    assert paid.iloc[0]["tax_due_pln"] == 0.0


def test_summaries_per_company_and_year():
    events = pd.DataFrame([
        event("DIVIDEND", 10.0), event("WHT", -1.5),
        event("DIVIDEND", 20.0, day="2025-12-15", symbol="MSFT.US"), event("WHT", -3.0, day="2025-12-15",
                                                                           symbol="MSFT.US"),
    ])
    fx = pd.concat([FX, pd.DataFrame([("USD", D("2025-12-12"), 3.6)], columns=FX.columns)])
    paid = payments(events, fx)
    companies = per_company(paid).set_index("symbol")
    assert companies.loc["MSFT.US", "net_pln"] == pytest.approx(17.0 * 3.6)
    assert companies.loc["AAPL.US", "wht_rate"] == pytest.approx(0.15)
    years = per_year(paid).set_index("year")
    assert years.loc[2026, "gross_pln"] == pytest.approx(41.0) and years.loc[2025, "gross_pln"] == pytest.approx(72.0)


def test_no_dividends():
    empty = pd.DataFrame(columns=["account_id", "account", "currency", "tax_wrapper", "date", "symbol", "name",
                                  "type", "amount", "comment"])
    assert payments(empty, FX).empty and per_company(payments(empty, FX)).empty
