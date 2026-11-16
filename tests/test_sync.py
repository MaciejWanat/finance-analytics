"""Import + sync: files in data/ -> projection tables, rebuilt only when needed."""

from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing

import pytest
import yaml

from finance_analytics.config import Settings
from finance_analytics.mock.xtb_export import write_mock_export
from finance_analytics.sources import sync as sync_module
from finance_analytics.sources.sync import import_xtb, sync, yahoo_ticker


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture(scope="module")
def export(tmp_path_factory):
    root = tmp_path_factory.mktemp("export")
    write_mock_export(root)
    return root


def _count(settings, table, where="1=1"):
    with closing(sqlite3.connect(settings.db_path)) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]


def test_import_archives_files_by_account_number(settings, export):
    result = import_xtb(export, settings)
    assert len(result.copied) == 5
    assert sorted(p.parent.name for p in result.copied) == ["1000001", "1000002", "1000005", "20000003", "20000004"]
    again = import_xtb(export, settings)
    assert not again.copied and len(again.unchanged) == 5


def test_sync_builds_projection_and_registers_accounts(settings, export):
    import_xtb(export, settings)
    result = sync(settings)
    assert result.rebuilt and not result.errors
    assert sorted(result.accounts_added) == ["XTB EUR", "XTB IKE", "XTB IKZE", "XTB PLN", "XTB USD"]
    assert _count(settings, "accounts") == 5
    assert _count(settings, "accounts", "tax_wrapper = 'IKE'") == 1
    assert _count(settings, "cash_ledger") > 500
    assert _count(settings, "positions", "close_time IS NOT NULL") > 0
    # Only the "assumed format" notices; reconciliation finds nothing on a consistent export.
    assert all("assumed" in w for w in result.warnings), result.warnings
    # Every position knows what it cost.
    assert _count(settings, "positions", "purchase_value IS NULL") == 0

    assert not sync(settings).rebuilt  # nothing changed


def test_overlapping_exports_do_not_duplicate(settings, export):
    import_xtb(export, settings)
    sync(settings)
    before = _count(settings, "cash_ledger"), _count(settings, "positions")
    # The same account exported again under a different date range: same operation IDs.
    source = next(export.rglob("USD_*.xlsx"))
    overlap = settings.data_dir / "overlap" / source.name.replace("2024-11-01", "2025-01-01")
    overlap.parent.mkdir(parents=True)
    shutil.copy(source, overlap)
    import_xtb(overlap, settings)
    assert sync(settings).rebuilt
    assert (_count(settings, "cash_ledger"), _count(settings, "positions")) == before


def test_alias_edits_survive_and_trigger_rebuild(settings, export):
    import_xtb(export, settings)
    sync(settings)
    data = yaml.safe_load(settings.accounts_file.read_text(encoding="utf-8"))
    data["accounts"][0]["alias"] = "Konto maklerskie"
    settings.accounts_file.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    assert sync(settings).rebuilt
    assert _count(settings, "accounts", "alias = 'Konto maklerskie'") == 1
    assert "Konto maklerskie" in settings.accounts_file.read_text(encoding="utf-8")


def test_parser_version_change_forces_rebuild(settings, export, monkeypatch):
    import_xtb(export, settings)
    sync(settings)
    monkeypatch.setattr(sync_module, "PARSER_VERSION", 999)
    assert sync(settings).rebuilt


def test_broken_file_is_reported_not_imported(settings, export):
    import_xtb(export, settings)
    broken = settings.raw_dir / "xtb" / "1000001" / "USD_1000001_2026-01-01_2026-02-01.xlsx"
    broken.write_bytes(b"not an xlsx")
    result = sync(settings)
    assert len(result.errors) == 1 and "cannot read the file" in result.errors[0]
    assert _count(settings, "import_issues", "severity = 'error'") == 1
    assert _count(settings, "accounts") == 5  # the other files still imported


def test_yahoo_ticker_rules():
    assert yahoo_ticker("NVDA.US") == "NVDA"
    assert yahoo_ticker("VUAA.UK") == "VUAA.L"
    assert yahoo_ticker("PKN.PL") is None  # not seen yet: unresolved, reported as a warning
