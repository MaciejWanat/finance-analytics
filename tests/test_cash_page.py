"""Smoke test of the "Gotówka" page on a synthetic data directory (Streamlit AppTest, offline)."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from finance_analytics.config import DATA_DIR_ENV, Settings
from finance_analytics.db import connect, migrate
from finance_analytics.mock.cash import write_mock_cash
from finance_analytics.sources.accounts import add_bank_account, load_accounts
from finance_analytics.sources.cash import append_snapshot, cash_file, read_snapshots
from finance_analytics.sources.sync import sync

PAGE = str(Path(__file__).resolve().parents[1] / "app" / "views" / "cash.py")


@pytest.fixture
def settings(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data")
    monkeypatch.setenv(DATA_DIR_ENV, str(settings.data_dir))
    settings.config_dir.mkdir(parents=True)
    with closing(connect(settings.db_path)) as conn:
        migrate(conn)
    return settings


def test_empty_state_then_add_an_account_and_a_balance(settings):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert any("Nie masz jeszcze kont bankowych" in m.value for m in at.markdown)
    at.text_input[0].input("Konto osobiste")
    at.button[0].click().run()
    assert not at.exception and not at.error
    (account,) = load_accounts(settings.accounts_file)
    assert (account.kind, account.currency, account.alias) == ("bank", "PLN", "Konto osobiste")
    assert any("Nie masz jeszcze zapisanych sald" in m.value for m in at.markdown)

    at.number_input[0].set_value(2500.5)
    next(b for b in at.button if b.label == "Zapisz saldo").click().run()
    assert not at.exception and not at.error, [e.value for e in at.error]
    (snapshot,) = read_snapshots(cash_file(settings.manual_dir), {account.id: "bank"}).snapshots
    assert (snapshot.day, snapshot.balance) == (date.today(), Decimal("2500.5"))
    assert [m.label for m in at.metric] == ["Gotówka razem", "Konta bankowe", "Ostatnia aktualizacja"]


def test_page_with_demo_balances_flags_stale_ones(settings):
    write_mock_cash(settings.accounts_file, cash_file(settings.manual_dir))
    sync(settings)
    with closing(sqlite3.connect(settings.db_path)) as conn, conn:  # NBP rates the demo EUR account needs
        conn.execute("INSERT INTO fx_rates (currency, date, mid) VALUES ('EUR', '2024-01-02', 4.3)")
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert [m.label for m in at.metric] == ["Gotówka razem", "Konta bankowe", "Ostatnia aktualizacja"]
    assert "Twoje konta" in [s.value for s in at.subheader]
    assert "Podział na konta" in [s.value for s in at.subheader]
    assert any("starsze niż 30 dni" in w.value for w in at.warning)  # the demo's last balances are old


def test_recent_balance_is_not_stale(settings):
    account = add_bank_account(settings.accounts_file, "Konto", "PLN")
    append_snapshot(cash_file(settings.manual_dir), account.id, date.today() - timedelta(days=3), Decimal("10"))
    sync(settings)
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert not any("starsze niż" in w.value for w in at.warning)


def test_importy_page_offers_csv_export_and_import(settings):
    write_mock_cash(settings.accounts_file, cash_file(settings.manual_dir))
    sync(settings)
    at = AppTest.from_file(str(Path(PAGE).with_name("imports.py")), default_timeout=60).run()
    assert not at.exception
    assert any("Dane wpisywane ręcznie" in m.value for m in at.markdown)


def test_foreign_balance_without_nbp_rates_shows_a_warning_not_an_error(settings):
    # Regression (D-029): the only account is in EUR and no rate is cached; the page used to crash.
    account = add_bank_account(settings.accounts_file, "Konto EUR", "EUR")
    append_snapshot(cash_file(settings.manual_dir), account.id, date.today() - timedelta(days=3), Decimal("10"))
    sync(settings)
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert any("brakuje kursów NBP" in w.value for w in at.warning)
