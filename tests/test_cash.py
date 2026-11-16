"""Bank cash entered by hand: CSV, accounts, sync and the daily valuation (R-007, D-027)."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from finance_analytics.config import Settings
from finance_analytics.mock.cash import DEMO_ACCOUNTS, DEMO_BALANCES, write_mock_cash
from finance_analytics.portfolio.returns import twr_index
from finance_analytics.portfolio.valuation import load_inputs, value_portfolio
from finance_analytics.sources import bonds as bond_files
from finance_analytics.sources import cash as files
from finance_analytics.sources.accounts import add_bank_account, load_accounts, slug
from finance_analytics.sources.manual_csv import template
from finance_analytics.sources.sync import sync
from tests.test_valuation import FX, PRICES, lot, make_inputs

D = pd.Timestamp
HEADER = "account_id,date,balance,note\n"
KINDS = {"bank-pln": "bank", "bank-eur": "bank", "xtb-1": "broker"}


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


def test_read_snapshots_accepts_valid_rows_and_reports_bad_ones(tmp_path):
    path = write(tmp_path / "cash_balances.csv", HEADER + "\n".join([
        'bank-pln,2026-01-05,"12 345,67",salary',  # decimal comma and a space are fine
        "bank-eur,05.01.2026,100.5,",  # Polish date format
        "bank-pln,2026-01-05,1,",  # second balance for the same day
        "bank-pln,2026-13-40,1,",
        "bank-pln,2026-01-06,abc,",
        "bank-pln,2026-01-06,nan,",
        "nope,2026-01-06,1,",
        "xtb-1,2026-01-06,1,",  # not a bank account
        ",2026-01-06,1,",
        "bank-pln,2027-01-06,1,",  # future
        "bank-pln,2026-01-07,-80,overdraft",  # negative is fine
    ]) + "\n")
    result = files.read_snapshots(path, KINDS, date(2026, 11, 16))
    assert [(s.row, s.account_id, s.day, s.balance) for s in result.snapshots] == [
        (1, "bank-pln", date(2026, 1, 5), Decimal("12345.67")),
        (2, "bank-eur", date(2026, 1, 5), Decimal("100.5")),
        (11, "bank-pln", date(2026, 1, 7), Decimal("-80")),
    ]
    assert len(result.errors) == 8
    assert "wierszu 1" in result.errors[0] and "wiersz 3" in result.errors[0]
    assert any("nieznane" in e for e in result.errors) and any("nie jest kontem bankowym" in e for e in result.errors)
    assert any("w przyszłości" in e for e in result.errors)


def test_read_snapshots_handles_semicolons_missing_columns_and_missing_file(tmp_path):
    semicolons = write(tmp_path / "a.csv", "account_id;date;balance;note\nbank-pln;2026-01-05;10,5;\n")
    assert files.read_snapshots(semicolons, KINDS).snapshots[0].balance == Decimal("10.5")
    broken = write(tmp_path / "b.csv", "account,date\nbank-pln,2026-01-05\n")
    result = files.read_snapshots(broken, KINDS)
    assert not result.snapshots and "brak kolumn" in result.errors[0]
    assert files.read_snapshots(tmp_path / "missing.csv", KINDS).snapshots == []


def test_append_and_delete_rows(tmp_path):
    path = tmp_path / "manual" / "cash_balances.csv"
    files.append_snapshot(path, "bank-pln", date(2026, 1, 5), Decimal("100"), "a")
    files.append_snapshot(path, "bank-eur", date(2026, 1, 5), Decimal("2.50"))
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")  # a blank line in the middle
    files.append_snapshot(path, "bank-pln", date(2026, 2, 5), Decimal("-3.1"))
    assert [(s.account_id, s.balance) for s in files.read_snapshots(path, KINDS).snapshots] == [
        ("bank-pln", Decimal("100")), ("bank-eur", Decimal("2.50")), ("bank-pln", Decimal("-3.1"))]
    assert files.delete_row(path, 2)
    assert [(s.row, s.day) for s in files.read_snapshots(path, KINDS).snapshots] == [
        (1, date(2026, 1, 5)), (2, date(2026, 2, 5))]
    assert not files.delete_row(path, 9)
    assert path.read_text(encoding="utf-8").startswith(HEADER)


def test_upload_is_validated_and_never_overwrites(tmp_path):
    path = tmp_path / "cash_balances.csv"
    files.append_snapshot(path, "bank-pln", date(2026, 1, 5), Decimal("100"))
    upload = HEADER + "bank-pln,2026-01-05,999,\nbank-pln,2026-02-05,200,\nbank-pln,bad,1,\n"
    result, fresh = files.merge_upload(path, upload, "mine.csv", KINDS, date(2026, 11, 16))
    assert [(s.day, s.balance) for s in fresh] == [(date(2026, 2, 5), Decimal("200"))]
    assert len(result.errors) == 2 and any("już jest w pliku" in e for e in result.errors)
    assert len(files.read_snapshots(path, KINDS).snapshots) == 1  # the preview changes nothing


def test_bonds_upload_skips_identical_rows_and_non_bond_accounts(tmp_path):
    path = tmp_path / "bonds.csv"
    bond_files.append_lot(path, "pko", "EDO0735", date(2025, 7, 8), 30, "x")
    upload = ("account_id,series,purchase_date,quantity,note\n"
              "pko,EDO0735,2025-07-08,30,x\npko,EDO0735,2025-07-08,31,x\nbank-pln,EDO0735,2025-07-08,1,\n"
              "new,EDO0735,2025-07-08,2,\n")
    result, fresh = bond_files.merge_upload(path, upload, "up.csv", {"EDO0735"}, {"pko": "bonds", "bank-pln": "bank"},
                                            date(2026, 11, 16))
    assert [(lot_.account_id, lot_.quantity) for lot_ in fresh] == [("pko", 31), ("new", 2)]
    assert len(result.errors) == 2


def test_templates_are_header_only():
    assert template(files.SNAPSHOT_COLUMNS) == HEADER
    assert template(bond_files.LOT_COLUMNS) == "account_id,series,purchase_date,quantity,note\n"


# ----------------------------------------------------------------------------------- accounts


def test_add_bank_account_derives_unique_ids_and_keeps_existing_entries(tmp_path):
    path = tmp_path / "config" / "accounts.yaml"
    first = add_bank_account(path, "Konto Łódzkie", "pln", "mBank")
    assert (first.id, first.kind, first.currency, first.institution) == ("bank-konto-lodzkie", "bank", "PLN", "mBank")
    second = add_bank_account(path, "Konto łódzkie 2", "EUR")
    assert second.id == "bank-konto-lodzkie-2" and second.institution == "bank"
    assert add_bank_account(path, "Bank PLN", "CHF").id == "bank-pln"  # no doubled prefix
    assert [a.alias for a in load_accounts(path)] == ["Konto Łódzkie", "Konto łódzkie 2", "Bank PLN"]
    with pytest.raises(ValueError, match="już istnieje"):
        add_bank_account(path, "konto łódzkie", "PLN")
    with pytest.raises(ValueError, match="pusta"):
        add_bank_account(path, "  ", "PLN")
    with pytest.raises(ValueError, match="ISO"):
        add_bank_account(path, "X", "zł")
    assert slug("Żółć & Ąę") == "zolc-ae"


# -------------------------------------------------------------------------------------- sync


def test_sync_projects_snapshots_and_reports_issues(settings):
    add_bank_account(settings.accounts_file, "Konto", "PLN")
    write(files.cash_file(settings.manual_dir), HEADER + "bank-konto,2026-01-05,100.5,a\n"
          "bank-konto,2026-01-05,1,dup\nghost,2026-01-05,1,\n")
    result = sync(settings)
    assert result.rebuilt and len(result.errors) == 2  # errors, not a crash
    assert query(settings, "SELECT account_id, date, balance, note, row_no FROM cash_snapshots") == [
        ("bank-konto", "2026-01-05", 100.5, "a", 1)]
    assert query(settings, "SELECT COUNT(*) FROM import_issues WHERE severity = 'error'") == [(2,)]


def test_cash_files_are_in_the_sync_fingerprint(settings):
    add_bank_account(settings.accounts_file, "Konto", "PLN")
    path = write(files.cash_file(settings.manual_dir), HEADER + "bank-konto,2026-01-05,100,\n")
    assert sync(settings).rebuilt
    assert not sync(settings).rebuilt  # nothing changed
    files.append_snapshot(path, "bank-konto", date(2026, 2, 5), Decimal("250"))
    assert sync(settings).rebuilt
    assert query(settings, "SELECT COUNT(*) FROM cash_snapshots") == [(2,)]
    files.delete_row(path, 1)
    assert sync(settings).rebuilt
    assert query(settings, "SELECT date FROM cash_snapshots") == [("2026-02-05",)]
    add_bank_account(settings.accounts_file, "Drugie", "EUR")  # accounts.yaml is in the fingerprint too
    assert sync(settings).rebuilt


def test_demo_cash_is_valid(settings):
    write_mock_cash(settings.accounts_file, files.cash_file(settings.manual_dir))
    result = sync(settings)
    assert not result.errors
    assert query(settings, "SELECT COUNT(*) FROM cash_snapshots") == [(len(DEMO_BALANCES),)]
    assert {a.alias for a in load_accounts(settings.accounts_file)} == {name for name, _, _ in DEMO_ACCOUNTS}
    write_mock_cash(settings.accounts_file, files.cash_file(settings.manual_dir))  # twice: nothing stacks
    assert len(load_accounts(settings.accounts_file)) == 2


# --------------------------------------------------------------------------------- valuation

ACCOUNTS = pd.DataFrame([("bank-pln", "Bank PLN", "PLN", None), ("bank-eur", "Konto EUR", "EUR", None)],
                        columns=["account_id", "alias", "currency", "tax_wrapper"])
EUR_FX = [("EUR", D("2026-01-05"), 4.0), ("EUR", D("2026-01-06"), 4.2)]  # none on the 7th (carried)


def bank_inputs(snapshots, fx=EUR_FX):
    inputs = make_inputs(accounts=ACCOUNTS, fx=fx)
    inputs.cash_snapshots = pd.DataFrame(snapshots, columns=["account_id", "date", "balance"]).astype(
        {"date": "datetime64[ns]"})
    return inputs


def test_balance_is_a_step_function_converted_at_the_nbp_rate():
    inputs = bank_inputs([("bank-eur", D("2026-01-05"), 100.0), ("bank-eur", D("2026-01-08"), 150.0)])
    v = value_portfolio(inputs, date(2026, 1, 9))
    rows = v.daily.set_index("date")
    assert rows.index.min() == D("2026-01-05")  # the account does not exist before its first snapshot
    assert set(rows["kind"]) == {"cash"} and set(rows["asset_class"]) == {"cash"}
    assert set(rows["symbol"]) == {"Gotówka"} and set(rows["account"]) == {"Konto EUR"}
    assert rows["qty"].tolist() == [100.0, 100.0, 100.0, 150.0, 150.0]
    # 100 EUR x 4.0, then x 4.2 (the 7th has no rate: carried), then 150 EUR x 4.2
    assert rows["value_pln"].tolist() == pytest.approx([400.0, 420.0, 420.0, 630.0, 630.0])


def test_pln_account_needs_no_rates_and_ignores_snapshots_after_the_end():
    inputs = bank_inputs([("bank-pln", D("2026-01-05"), 1000.0), ("bank-pln", D("2026-02-01"), 5.0)], fx=[])
    v = value_portfolio(inputs, date(2026, 1, 7))
    assert v.total.tolist() == [1000.0, 1000.0, 1000.0]
    assert not v.warnings


def test_balance_changes_are_external_flows_so_twr_ignores_deposits_and_spending():
    inputs = bank_inputs([
        ("bank-pln", D("2026-01-05"), 1000.0), ("bank-pln", D("2026-01-07"), 600.0),  # spent 400
        ("bank-eur", D("2026-01-05"), 100.0), ("bank-eur", D("2026-01-08"), 150.0),  # topped up by 50 EUR
    ])
    v = value_portfolio(inputs, date(2026, 1, 8))
    by_day = v.flows.groupby("date")["amount_pln"].sum()
    assert by_day.to_dict() == pytest.approx({
        D("2026-01-05"): 1000.0 + 400.0,  # first snapshots: the money enters the portfolio
        D("2026-01-07"): -400.0,
        D("2026-01-08"): 50 * 4.2,
    })
    assert set(v.flows["type"]) == {"BANK"}
    total = v.total
    assert total.tolist() == pytest.approx([1400.0, 1420.0, 1020.0, 1230.0])  # 600 + 150 x 4.2 on the 8th
    index = twr_index(total, v.flows.set_index("date")["amount_pln"])
    # Only the 100 EUR moved: 4.0 -> 4.2 on the 6th is +20 on 1 400 of capital; deposits and spending add nothing.
    assert index.iloc[1] == pytest.approx(1 + 20 / 1400)
    assert index.iloc[2] == pytest.approx(index.iloc[1])  # spending 400 zł is not a loss
    assert index.iloc[-1] == pytest.approx(index.iloc[1])  # topping up by 50 EUR is not a gain


def test_bank_cash_sits_next_to_positions():
    inputs = make_inputs(lots=[lot()], prices=PRICES, fx=FX + EUR_FX, accounts=pd.DataFrame(
        [("usd", "XTB USD", "USD", None), ("bank-pln", "Bank PLN", "PLN", None)],
        columns=["account_id", "alias", "currency", "tax_wrapper"]))
    inputs.cash_snapshots = pd.DataFrame([("bank-pln", D("2026-01-05"), 500.0)],
                                         columns=["account_id", "date", "balance"]).astype({"date": "datetime64[ns]"})
    v = value_portfolio(inputs, date(2026, 1, 5))
    day = v.daily[v.daily["date"] == D("2026-01-05")]
    assert day.groupby("kind")["value_pln"].sum().to_dict() == pytest.approx({"position": 4000.0, "cash": 500.0})


def test_load_inputs_reads_the_projection(settings):
    add_bank_account(settings.accounts_file, "Konto", "PLN")
    write(files.cash_file(settings.manual_dir), HEADER + "bank-konto,2026-01-05,100.5,\n")
    sync(settings)
    inputs = load_inputs(settings.db_path)
    assert inputs.cash_snapshots["balance"].tolist() == [100.5]
    v = value_portfolio(inputs, date(2026, 1, 6))
    assert v.total.tolist() == [100.5, 100.5]
