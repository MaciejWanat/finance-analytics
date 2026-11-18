"""Reset of the data directory (D-038): synthetic data only, tmp directories only."""

from __future__ import annotations

import io
import sqlite3
import zipfile
from contextlib import closing

import pytest
from click.testing import CliRunner
from streamlit.testing.v1 import AppTest

from finance_analytics.cli import main
from finance_analytics.config import APP_DIR, DATA_DIR_ENV, Settings
from finance_analytics.mock.bonds import write_mock_bonds
from finance_analytics.mock.cash import write_mock_cash
from finance_analytics.mock.xtb_export import write_mock_export
from finance_analytics.preferences import load_preferences, save_preferences
from finance_analytics.sources.bonds import bonds_file
from finance_analytics.sources.cash import cash_file
from finance_analytics.sources.reset import ResetChoice, backup_zip, files_for, reset_data
from finance_analytics.sources.sync import import_xtb, sync

PAGE = str(APP_DIR / "views" / "settings.py")


@pytest.fixture(scope="module")
def export(tmp_path_factory):
    root = tmp_path_factory.mktemp("export")
    write_mock_export(root)
    return root


@pytest.fixture
def settings(tmp_path, export, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data")
    monkeypatch.setenv(DATA_DIR_ENV, str(settings.data_dir))
    for folder in settings.all_dirs():
        folder.mkdir(parents=True, exist_ok=True)
    import_xtb(export, settings)
    write_mock_bonds(bonds_file(settings.manual_dir))
    write_mock_cash(settings.accounts_file, cash_file(settings.manual_dir))
    save_preferences(settings, load_preferences(settings).model_copy(update={"poll_seconds": 600}))
    sync(settings)
    with closing(sqlite3.connect(settings.db_path)) as conn, conn:
        conn.execute("INSERT INTO fx_rates (currency, date, mid) VALUES ('USD', '2024-01-02', 4.0)")
    return settings


def _count(settings, table):
    with closing(sqlite3.connect(settings.db_path)) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_backup_holds_every_source_file(settings):
    with zipfile.ZipFile(io.BytesIO(backup_zip(settings))) as archive:
        names = set(archive.namelist())
    assert "manual/bonds.csv" in names and "config/accounts.yaml" in names
    assert any(name.startswith("raw/xtb/") and name.endswith(".xlsx") for name in names)


def test_full_reset_empties_projection_and_keeps_preferences(settings):
    result = reset_data(settings, ResetChoice())
    assert result.removed
    assert not any(p.is_file() for p in settings.raw_dir.rglob("*"))
    assert not bonds_file(settings.manual_dir).exists() and not settings.accounts_file.exists()
    assert load_preferences(settings).poll_seconds == 600  # settings.yaml kept
    for table in ("accounts", "positions", "cash_ledger", "bond_lots", "cash_snapshots"):
        assert _count(settings, table) == 0, table
    with closing(sqlite3.connect(settings.db_path)) as conn:
        left = [row[0] for row in conn.execute("SELECT path FROM source_files")]
    assert all(path.startswith("resources/") for path in left)  # only the shipped public files
    assert _count(settings, "fx_rates") == 1  # market cache kept unless asked
    assert files_for(settings, ResetChoice()) == []


def test_partial_reset_and_market_cache(settings):
    reset_data(settings, ResetChoice(exports=False, manual=True, accounts=False, market=True))
    assert any(p.is_file() for p in settings.raw_dir.rglob("*.xlsx"))
    assert settings.accounts_file.exists()
    assert _count(settings, "positions") > 0 and _count(settings, "bond_lots") == 0
    assert _count(settings, "fx_rates") == 0


def test_never_deletes_outside_data_dir(settings, export):
    before = sorted(export.rglob("*"))
    reset_data(settings, ResetChoice(market=True))
    assert sorted(export.rglob("*")) == before  # the source export folder is untouched


def test_cli_reset_asks_and_writes_backup(settings, tmp_path):
    runner = CliRunner()
    aborted = runner.invoke(main, ["reset"], input="n\n")
    assert aborted.exit_code != 0 and settings.accounts_file.exists()
    backup = tmp_path / "backup.zip"
    done = runner.invoke(main, ["reset", "--yes", "--backup", str(backup)])
    assert done.exit_code == 0, done.output
    assert backup.exists() and not settings.accounts_file.exists()


def test_settings_page_requires_typed_confirmation(settings):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    delete = next(b for b in at.button if b.label == "Usuń dane")
    assert delete.disabled
    at.text_input(key="reset_confirm_0").input("USUŃ").run()
    next(b for b in at.button if b.label == "Usuń dane").click().run()
    assert not at.exception
    assert not settings.accounts_file.exists()
    assert any("Usunięto" in s.value for s in at.success)


def test_settings_page_saves_the_today_tile_mode(settings):
    """D-067: the "Dzisiaj" tile counts from midnight by default; the settings page switches it."""
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    tile = next(r for r in at.radio if r.label == "Kafelek „Dzisiaj”")
    assert tile.value == "calendar_day"
    tile.set_value("us_session").run()
    next(b for b in at.button if b.label == "Zapisz").click().run()
    assert not at.exception
    assert load_preferences(settings).today_tile == "us_session"
    assert load_preferences(settings).poll_seconds == 600  # the other settings stay
