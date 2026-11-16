"""bonds.csv parsing, sync into the projection and bonds inside the daily valuation (D-026)."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
import yaml

from finance_analytics.config import Settings
from finance_analytics.mock.bonds import DEMO_PURCHASES, write_mock_bonds
from finance_analytics.portfolio.valuation import BondInputs, load_inputs, value_portfolio
from finance_analytics.sources import bonds as files
from finance_analytics.sources.accounts import load_accounts
from finance_analytics.sources.sync import sync

KNOWN = {"EDO0735", "COI0929", "EDO0334"}
HEADER = "account_id,series,purchase_date,quantity,note\n"


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data")


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def query(settings, sql):
    with closing(sqlite3.connect(settings.db_path)) as conn:
        return conn.execute(sql).fetchall()


# --------------------------------------------------------------------------------------- CSV


def test_read_lots_accepts_valid_rows_and_reports_bad_ones(tmp_path):
    path = write(tmp_path / "bonds.csv", HEADER + "\n".join([
        "pko,edo0735,2025-07-08,30,first",  # lower case is fine
        "pko,COI0929,03.09.2025,20,",  # Polish date format is accepted
        "pko,EDO0735,2025-08-08,5,",  # EDO0735 matures in 07.2035: bought in August it would be EDO0835
        "pko,XYZ0101,2025-01-01,1,",
        "pko,EDO0334,2024-03-12,0,",
        "pko,EDO0334,2024-03-12,1.5,",
        ",EDO0334,2024-03-12,1,",
        "pko,EDO1299,2024-03-12,1,",  # unknown series
    ]) + "\n")
    result = files.read_lots(path, KNOWN, date(2026, 11, 16))
    assert [(lot.row, lot.series, lot.purchase_date, lot.quantity) for lot in result.lots] == [
        (1, "EDO0735", date(2025, 7, 8), 30), (2, "COI0929", date(2025, 9, 3), 20)]
    assert len(result.errors) == 6
    assert "wiersz 3" in result.errors[0] and "07.2035" in result.errors[0]
    assert any("nieznana" in e for e in result.errors)


def test_read_lots_handles_semicolons_and_missing_columns(tmp_path):
    semicolons = write(tmp_path / "a.csv", "account_id;series;purchase_date;quantity;note\npko;EDO0735;2025-07-08;3;\n")
    assert files.read_lots(semicolons, KNOWN).lots[0].quantity == 3
    broken = write(tmp_path / "b.csv", "account,series\npko,EDO0735\n")
    result = files.read_lots(broken, KNOWN)
    assert not result.lots and "brak kolumn" in result.errors[0]
    assert files.read_lots(tmp_path / "missing.csv", KNOWN).lots == []


def test_future_purchase_is_rejected():
    assert "przyszłości" in files.check_purchase("EDO0735", date(2025, 7, 8), KNOWN, date(2025, 7, 1))


def test_append_and_delete_rows(tmp_path):
    path = tmp_path / "manual" / "bonds.csv"
    files.append_lot(path, "pko", "EDO0735", date(2025, 7, 8), 30, "a")
    files.append_lot(path, "pko", "COI0929", date(2025, 9, 3), 20)
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")  # a blank line in the middle
    files.append_lot(path, "pko", "EDO0334", date(2024, 3, 12), 5)
    assert [lot.series for lot in files.read_lots(path, KNOWN).lots] == ["EDO0735", "COI0929", "EDO0334"]
    assert files.delete_row(path, 2)
    assert [(lot.row, lot.series) for lot in files.read_lots(path, KNOWN).lots] == [(1, "EDO0735"), (2, "EDO0334")]
    assert not files.delete_row(path, 7)


def test_yaml_overrides_add_series_and_rates(tmp_path):
    write(tmp_path / "bond_series.yaml", yaml.safe_dump({"series": {
        "EDO1299": {"first_rate": 5.0, "margin": 2.0, "early_fee": 3.0},
        "EDO0129": {"rates": {9: 4.6}},
        "COI1299": {"first_rate": 5.0, "early_fee": 2.0},  # floating without margin: rejected
        "BAD": {},
    }}))
    table = files.load_series(tmp_path)
    assert table.series["EDO1299"]["origin"] == "user" and table.series["EDO1299"]["type"] == "EDO"
    assert table.rates[("EDO0129", 9)] == (Decimal("4.6"), "user")
    assert "COI1299" not in table.series
    assert len(table.errors) == 2


# -------------------------------------------------------------------------------------- sync


def test_sync_creates_bonds_account_and_lots(settings):
    write(files.bonds_file(settings.manual_dir), HEADER + "pko-obligacje,EDO0735,2025-07-08,30,mock\n"
          "pko-obligacje,XYZ,2025-07-08,1,\n")
    result = sync(settings)
    assert result.rebuilt and result.accounts_added == ["Obligacje skarbowe"]
    (account,) = load_accounts(settings.accounts_file)
    assert (account.id, account.institution, account.kind, account.currency, account.tax_wrapper) == (
        "pko-obligacje", "pko", "bonds", "PLN", None)
    assert query(settings, "SELECT series, purchase_date, quantity, row_no FROM bond_lots") == [
        ("EDO0735", "2025-07-08", 30, 1)]
    assert len(result.errors) == 1 and "wiersz 2" in result.errors[0]  # error, not a crash
    assert query(settings, "SELECT COUNT(*) FROM import_issues WHERE severity = 'error'") == [(1,)]
    assert query(settings, "SELECT COUNT(*) FROM bond_series")[0][0] > 600
    assert query(settings, "SELECT COUNT(*) FROM bond_reference_rate")[0][0] > 10


def test_bond_files_are_in_the_sync_fingerprint(settings):
    path = write(files.bonds_file(settings.manual_dir), HEADER + "pko-obligacje,EDO0735,2025-07-08,30,\n")
    assert sync(settings).rebuilt
    assert not sync(settings).rebuilt  # nothing changed
    files.append_lot(path, "pko-obligacje", "COI0929", date(2025, 9, 3), 20)
    assert sync(settings).rebuilt
    assert query(settings, "SELECT COUNT(*) FROM bond_lots") == [(2,)]
    write(files.series_overrides_file(settings.config_dir), "series:\n  EDO0735:\n    rates: {2: 6.0}\n")
    assert sync(settings).rebuilt
    assert query(settings, "SELECT rate, origin FROM bond_rates WHERE series = 'EDO0735' AND period = 2") == [
        (6.0, "user")]
    assert not sync(settings).rebuilt


def test_lot_on_a_non_bonds_account_is_rejected(settings):
    settings.config_dir.mkdir(parents=True)
    settings.accounts_file.write_text(yaml.safe_dump({"accounts": [
        {"id": "bank", "institution": "pko", "kind": "bank", "currency": "PLN", "alias": "Konto"}]}), encoding="utf-8")
    write(files.bonds_file(settings.manual_dir), HEADER + "bank,EDO0735,2025-07-08,30,\n")
    result = sync(settings)
    assert query(settings, "SELECT COUNT(*) FROM bond_lots") == [(0,)]
    assert "nie jest rachunkiem obligacji" in result.errors[0]


def test_demo_purchases_are_valid(settings):
    write_mock_bonds(files.bonds_file(settings.manual_dir))
    result = sync(settings)
    assert not result.errors
    assert query(settings, "SELECT COUNT(*) FROM bond_lots") == [(len(DEMO_PURCHASES),)]


# --------------------------------------------------------------------------------- valuation


def test_bonds_appear_in_the_daily_valuation_with_their_flows(settings):
    write(files.bonds_file(settings.manual_dir), HEADER + "pko-obligacje,ROR0226,2025-02-10,10,\n")
    sync(settings)
    inputs = load_inputs(settings.db_path)
    v = value_portfolio(inputs, date(2026, 3, 1))
    bonds = v.daily[v.daily["asset_class"] == "bond"]
    assert set(bonds["symbol"]) == {"ROR0226"} and set(bonds["currency"]) == {"PLN"}
    assert bonds["date"].min() == pd.Timestamp("2025-02-10") and bonds["date"].max() == pd.Timestamp("2026-02-09")
    assert v.total[pd.Timestamp("2025-02-10")] == pytest.approx(1000.0)  # bought at nominal: no gain on day 1
    assert pd.Timestamp("2026-02-10") not in set(bonds["date"])  # redeemed: no longer held
    flows = v.flows.set_index("date")["amount_pln"]
    assert flows[pd.Timestamp("2025-02-10")] == pytest.approx(1000.0)  # purchase = deposit
    # ROR0226: 12 monthly coupons; the first at 5.75% -> 0.48 zł per bond, 4.80 zł for 10, minus 19% (0.91).
    assert flows[pd.Timestamp("2025-03-10")] == pytest.approx(-(4.80 - 0.91))
    redemption = flows[pd.Timestamp("2026-02-10")]
    assert redemption < -1000  # nominal back plus the last coupon, after tax
    assert len(v.flows) == 13
    assert inputs.bonds.lots["quantity"].tolist() == [10]


def test_bonds_only_portfolio_values_without_market_data():
    lots = pd.DataFrame({"account_id": ["ike"], "series": ["EDO0129"], "purchase_date": [pd.Timestamp("2025-01-15")],
                         "quantity": [2]})
    bonds = BondInputs.empty()
    bonds.lots = lots
    bonds.series = pd.DataFrame([("EDO0129", "EDO", 2.7, 1.5, 2.0, None)], columns=bonds.series.columns)
    from tests.test_valuation import make_inputs

    accounts = pd.DataFrame([("ike", "Obligacje IKE", "PLN", "IKE")],
                            columns=["account_id", "alias", "currency", "tax_wrapper"])
    inputs = make_inputs(accounts=accounts)
    inputs.bonds = bonds
    v = value_portfolio(inputs, date(2025, 2, 15))
    # 31 days at 2.7%: 100 * (1 + 0.027 * 31/365) = 100.229 -> 100.23 per bond
    assert v.total.iloc[-1] == pytest.approx(200.46)
    assert v.daily["kind"].unique().tolist() == ["bond"]
    assert v.flows["amount_pln"].tolist() == [pytest.approx(200.0)]
