"""A filtered part of the portfolio measured as a portfolio of its own (D-085)."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from test_valuation import FX, PRICES, D, lot, make_inputs

from finance_analytics.portfolio.returns import twr_index
from finance_analytics.portfolio.slicing import Slice, part_flows, slice_valuation
from finance_analytics.portfolio.valuation import CASH_SYMBOL, value_portfolio

STOCKS = Slice(classes=frozenset({"stock"}))


def flows_of(v) -> pd.Series:
    return v.flows.groupby("date")["amount_pln"].sum()


def test_a_purchase_is_a_deposit_into_the_part_at_the_days_value():
    inputs = make_inputs(lots=[lot()], ledger=[("usd", D("2026-01-05"), "DEPOSIT", 2000.0),
                                               ("usd", D("2026-01-05"), "STOCK_PURCHASE", -1000.0)],
                         prices=PRICES, fx=FX)
    v = value_portfolio(inputs, date(2026, 1, 7))
    part = slice_valuation(v, STOCKS)
    assert set(part.daily["kind"]) == {"position"}
    assert flows_of(part).to_dict() == {D("2026-01-05"): pytest.approx(4000.0)}  # 10 × 100 USD × 4.0
    twr = twr_index(part.total, flows_of(part))
    assert twr.iloc[-1] == pytest.approx(10 * 110 * 4.1 / 4000)  # only the price and the rate moved it


def test_a_sale_is_a_withdrawal_and_the_part_runs_to_the_portfolios_last_day():
    inputs = make_inputs(lots=[lot(close_date="2026-01-07")], prices=PRICES, fx=FX,
                         ledger=[("usd", D("2026-01-05"), "DEPOSIT", 1000.0)])
    v = value_portfolio(inputs, date(2026, 1, 8))
    part = slice_valuation(v, STOCKS)
    assert part.total.index[-1] == D("2026-01-08") and part.total.iloc[-1] == 0
    assert flows_of(part)[D("2026-01-07")] == pytest.approx(-10 * 110 * 4.1)


def test_a_dividend_leaves_the_position_for_the_accounts_cash():
    inputs = make_inputs(lots=[lot()], prices=PRICES, fx=FX,
                         ledger=[("usd", D("2026-01-05"), "DEPOSIT", 1000.0),
                                 ("usd", D("2026-01-06"), "DIVIDEND", 5.0),
                                 ("usd", D("2026-01-06"), "WHT", -0.75)])
    inputs.ledger["symbol"] = [None, "NVDA.US", "NVDA.US"]
    v = value_portfolio(inputs, date(2026, 1, 7))
    assert v.income["amount_pln"].sum() == pytest.approx(4.25 * 4.1)
    flows = part_flows(v)
    on_the_day = flows[flows["date"] == D("2026-01-06")].set_index("symbol")["amount_pln"]
    assert on_the_day["NVDA.US"] == pytest.approx(-4.25 * 4.1)
    assert on_the_day[CASH_SYMBOL] == pytest.approx(4.25 * 4.1)


def test_no_filter_is_the_valuation_itself():
    v = value_portfolio(make_inputs(lots=[lot()], prices=PRICES, fx=FX), date(2026, 1, 7))
    assert slice_valuation(v, Slice()) is v


def test_mask_ands_dimensions_and_ors_within_them():
    frame = pd.DataFrame({"symbol": ["A", "B", "C"], "asset_class": ["stock", "etf", "stock"]})
    both = Slice(classes=frozenset({"stock", "etf"}), symbols=frozenset({"A", "B"}))
    assert both.mask(frame).tolist() == [True, True, False]
    assert Slice(classes=frozenset({"stock"}), symbols=frozenset({"B"})).mask(frame).tolist() == [False] * 3


@pytest.fixture(scope="module")
def mock_valuation(tmp_path_factory):
    from conftest import go_online
    from test_market import TODAY, FakePriceClient, fake_nbp_get

    from finance_analytics.config import Settings
    from finance_analytics.market import nbp
    from finance_analytics.market.update import update_market
    from finance_analytics.mock.xtb_export import write_mock_export
    from finance_analytics.portfolio.valuation import load_inputs
    from finance_analytics.sources.sync import import_xtb, sync

    root = tmp_path_factory.mktemp("slicing")
    settings = Settings(data_dir=root / "data")
    write_mock_export(root / "export")
    import_xtb(root / "export", settings)
    sync(settings)
    go_online(settings)
    update_market(settings, today=TODAY, price_client=FakePriceClient(),
                  fx_fetch=lambda c, s, e: nbp.fetch_rates(c, s, e, get=fake_nbp_get([])),
                  cpi_fetch=lambda: [(2026, 1, 100.0, 103.0)])
    return value_portfolio(load_inputs(settings.db_path), TODAY)


def test_the_parts_flows_sum_to_the_portfolios_flows(mock_valuation):
    v = mock_valuation
    parts = part_flows(v).groupby("date")["amount_pln"].sum()
    external = flows_of(v)
    both = pd.concat([parts, external], axis=1).fillna(0.0)
    assert (both.iloc[:, 0] - both.iloc[:, 1]).abs().max() < 1e-6


def test_a_filter_keeping_every_class_gives_the_same_twr(mock_valuation):
    v = mock_valuation
    everything = slice_valuation(v, Slice(classes=frozenset(v.daily["asset_class"])))
    whole = twr_index(v.total, flows_of(v))
    part = twr_index(everything.total, flows_of(everything))
    assert part.iloc[-1] == pytest.approx(whole.iloc[-1], rel=1e-9)


def test_classes_split_the_value_without_a_remainder(mock_valuation):
    v = mock_valuation
    pieces = [slice_valuation(v, Slice(classes=frozenset({c}))).total for c in v.daily["asset_class"].unique()]
    summed = pd.concat(pieces, axis=1).fillna(0.0).sum(axis=1)
    pd.testing.assert_series_equal(summed.reindex(v.total.index), v.total, check_names=False, check_freq=False)
