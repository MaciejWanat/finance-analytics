"""Valuation on tiny hand-computed portfolios."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from finance_analytics.portfolio.valuation import Inputs, value_portfolio

D = pd.Timestamp


def make_inputs(lots=(), ledger=(), prices=(), fx=(), splits=(), currencies=None, accounts=None) -> Inputs:
    lot_columns = ["account_id", "instrument_id", "symbol", "name", "asset_class", "ticker", "volume", "open_date",
                   "close_date", "open_price", "purchase_value"]
    return Inputs(
        lots=pd.DataFrame(list(lots), columns=lot_columns).astype({"open_date": "datetime64[ns]",
                                                                   "close_date": "datetime64[ns]"}),
        ledger=pd.DataFrame(list(ledger), columns=["account_id", "date", "type", "amount"]).astype(
            {"date": "datetime64[ns]"}
        ),
        accounts=accounts if accounts is not None else pd.DataFrame(
            [("usd", "XTB USD", "USD", None), ("pln", "XTB PLN", "PLN", None)],
            columns=["account_id", "alias", "currency", "tax_wrapper"],
        ),
        prices=pd.DataFrame(list(prices), columns=["ticker", "date", "close"]).astype({"date": "datetime64[ns]"}),
        currencies=currencies or {"NVDA": "USD"},
        fx=pd.DataFrame(list(fx), columns=["currency", "date", "mid"]).astype({"date": "datetime64[ns]"}),
        splits=pd.DataFrame(list(splits), columns=["ticker", "date", "ratio"]).astype({"date": "datetime64[ns]"}),
    )


def lot(volume=10.0, open_date="2026-01-05", close_date=None, open_price=100.0, purchase_value=1000.0,
        account="usd", ticker="NVDA"):
    return (account, 1, f"{ticker}.US", ticker, "stock", ticker, volume, D(open_date),
            D(close_date) if close_date else pd.NaT, open_price, purchase_value)


FX = [("USD", D("2026-01-05"), 4.0), ("USD", D("2026-01-06"), 4.1)]  # no rate on the 7th (holiday)
PRICES = [("NVDA", D("2026-01-05"), 100.0), ("NVDA", D("2026-01-07"), 110.0)]  # no trading on the 6th


def positions_on(valuation, day):
    daily = valuation.daily
    return daily[(daily["date"] == D(day)) & (daily["kind"] == "position")]


def test_position_value_carries_price_and_fx_forward():
    v = value_portfolio(make_inputs(lots=[lot()], prices=PRICES, fx=FX), date(2026, 1, 7))
    assert positions_on(v, "2026-01-05")["value_pln"].item() == pytest.approx(10 * 100 * 4.0)
    assert positions_on(v, "2026-01-06")["value_pln"].item() == pytest.approx(10 * 100 * 4.1)  # last price
    assert positions_on(v, "2026-01-07")["value_pln"].item() == pytest.approx(10 * 110 * 4.1)  # last rate
    assert v.lots["cost_pln"].item() == pytest.approx(1000 * 4.0)
    assert not v.warnings


def test_closed_lot_is_not_held_from_its_closing_day():
    v = value_portfolio(make_inputs(lots=[lot(close_date="2026-01-07")], prices=PRICES, fx=FX), date(2026, 1, 8))
    assert positions_on(v, "2026-01-06")["qty"].item() == 10
    assert positions_on(v, "2026-01-07").empty and positions_on(v, "2026-01-08").empty


def test_cash_is_running_balance_in_pln():
    ledger = [("usd", D("2026-01-05"), "DEPOSIT", 2000.0), ("usd", D("2026-01-05"), "BUY", -1000.0),
              ("usd", D("2026-01-07"), "DIVIDEND", 5.0)]
    v = value_portfolio(make_inputs(lots=[lot()], ledger=ledger, prices=PRICES, fx=FX), date(2026, 1, 7))
    cash = v.daily[v.daily["kind"] == "cash"].set_index("date")
    assert cash.loc[D("2026-01-05"), "value_pln"] == pytest.approx(1000 * 4.0)
    assert cash.loc[D("2026-01-07"), "value_pln"] == pytest.approx(1005 * 4.1)
    assert v.total[D("2026-01-07")] == pytest.approx(10 * 110 * 4.1 + 1005 * 4.1)
    assert v.flows["amount_pln"].tolist() == [pytest.approx(8000.0)]  # only the deposit is an external flow


def test_pln_account_holding_usd_stock():
    v = value_portfolio(
        make_inputs(lots=[lot(account="pln", purchase_value=4020.0)], prices=PRICES, fx=FX), date(2026, 1, 6)
    )
    assert positions_on(v, "2026-01-06")["value_pln"].item() == pytest.approx(10 * 100 * 4.1)
    assert v.lots["cost_pln"].item() == pytest.approx(4020.0)  # PLN account: cost already in PLN


def test_missing_price_falls_back_to_cost_with_warning():
    v = value_portfolio(make_inputs(lots=[lot(ticker="XYZ")], fx=FX, currencies={}), date(2026, 1, 6))
    row = positions_on(v, "2026-01-06")
    assert row["value_pln"].item() == pytest.approx(1000 * 4.1) and not row["priced"].item()
    assert any("XYZ.US: brak ceny rynkowej" in w for w in v.warnings)


def test_split_after_purchase():
    # 10:1 split on the 6th. Yahoo's adjusted close before the split is 10 (was 100).
    prices = [("NVDA", D("2026-01-05"), 10.0), ("NVDA", D("2026-01-06"), 11.0)]
    splits = [("NVDA", D("2026-01-06"), 10.0)]
    # Broker kept the pre-split lot (10 shares @ 100): counted as 100 shares.
    kept = value_portfolio(make_inputs(lots=[lot()], prices=prices, fx=FX, splits=splits), date(2026, 1, 6))
    assert positions_on(kept, "2026-01-06")["qty"].item() == 100
    assert positions_on(kept, "2026-01-06")["value_pln"].item() == pytest.approx(100 * 11 * 4.1)
    assert any("split" in w for w in kept.warnings)
    # Broker already adjusted the lot (100 shares @ 10): left alone.
    adjusted = value_portfolio(
        make_inputs(lots=[lot(volume=100, open_price=10.0)], prices=prices, fx=FX, splits=splits), date(2026, 1, 6)
    )
    assert positions_on(adjusted, "2026-01-06")["qty"].item() == 100


def test_empty_portfolio():
    v = value_portfolio(make_inputs(), date(2026, 1, 6))
    assert v.daily.empty and v.total.empty


def test_end_to_end_on_mock_export(tmp_path):
    from conftest import go_online
    from test_market import TODAY, FakePriceClient, fake_nbp_get

    from finance_analytics.config import Settings
    from finance_analytics.market import nbp
    from finance_analytics.market.update import update_market
    from finance_analytics.mock.xtb_export import write_mock_export
    from finance_analytics.portfolio.valuation import load_inputs
    from finance_analytics.sources.sync import import_xtb, sync

    settings = Settings(data_dir=tmp_path / "data")
    write_mock_export(tmp_path / "export")
    import_xtb(tmp_path / "export", settings)
    sync(settings)
    go_online(settings)
    update_market(settings, today=TODAY, price_client=FakePriceClient(),
                  fx_fetch=lambda c, s, e: nbp.fetch_rates(c, s, e, get=fake_nbp_get([])),
                  cpi_fetch=lambda: [(2026, 1, 100.0, 103.0)])

    v = value_portfolio(load_inputs(settings.db_path), TODAY)
    assert not v.daily["value_pln"].isna().any() and not v.warnings
    assert (v.total > 0).all()
    last = v.daily[v.daily["date"] == v.daily["date"].max()]
    assert set(last["account"]) == {"XTB USD", "XTB PLN", "XTB EUR", "XTB IKE", "XTB IKZE"}
    # Every open lot is held on the last day, in the right quantity.
    open_lots = v.lots[v.lots["close_date"].isna()]
    held = last[last["kind"] == "position"].groupby(["account_id", "symbol"])["qty"].sum()
    expected = open_lots.groupby(["account_id", "symbol"])["volume_adj"].sum()
    pd.testing.assert_series_equal(held.sort_index(), expected.sort_index(), check_names=False, atol=1e-6)


# --------------------------------------------------------------- release review regressions (D-029)


def test_only_bank_balances_without_rates_give_an_empty_valuation_not_a_crash():
    inputs = make_inputs(accounts=pd.DataFrame([("bank-eur", "Konto EUR", "EUR", None)],
                                               columns=["account_id", "alias", "currency", "tax_wrapper"]))
    inputs.cash_snapshots = pd.DataFrame({"account_id": ["bank-eur"], "date": [D("2026-01-05")],
                                          "balance": [100.0]})
    v = value_portfolio(inputs, date(2026, 1, 8))
    assert v.total.empty and v.daily[v.daily["kind"] == "cash"].empty  # pages filter an empty frame safely
    assert v.warnings == ["Brak kursów NBP dla EUR: wartości w tej walucie nie są wyceniane"]


def test_end_before_the_first_event_gives_an_empty_valuation():
    v = value_portfolio(make_inputs(lots=[lot()], prices=PRICES, fx=FX), date(2026, 1, 1))
    assert v.total.empty


def test_flows_after_the_end_day_are_left_out():
    ledger = [("pln", D("2026-01-05"), "DEPOSIT", 100.0), ("pln", D("2026-02-05"), "DEPOSIT", 50.0)]
    v = value_portfolio(make_inputs(ledger=ledger), date(2026, 1, 8))
    assert v.flows["date"].tolist() == [D("2026-01-05")]
