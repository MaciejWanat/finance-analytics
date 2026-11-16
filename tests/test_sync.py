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


def _edit_usd_export(export, tmp_path, edit):
    """Copy the synthetic export and change its USD file with `edit(workbook)`."""
    from openpyxl import load_workbook

    root = tmp_path / "edited_export"
    shutil.copytree(export, root)
    path = next(root.rglob("USD_*.xlsx"))
    wb = load_workbook(path)
    edit(wb)
    wb.save(path)
    return root


def test_timestamps_with_milliseconds_do_not_break_reading(settings, export, tmp_path):
    from datetime import timedelta

    from finance_analytics import reports
    from finance_analytics.sources.xtb import schema

    def add_milliseconds(wb):
        ws = wb[schema.OPEN_POSITIONS.name]
        column = schema.OPEN_POSITIONS.columns.index("Open time (UTC)") + 1
        for row in range(schema.OPEN_POSITIONS.header_row + 1, ws.max_row + 1, 2):
            cell = ws.cell(row=row, column=column)
            if cell.value is not None:
                cell.value = cell.value + timedelta(milliseconds=123)

    import_xtb(_edit_usd_export(export, tmp_path, add_milliseconds), settings)
    assert not sync(settings).errors
    opened = reports.positions(settings.db_path, "xtb-1000001", open_only=True)
    assert not opened.empty and opened["open_time"].notna().all()
    assert not reports.cash_ledger(settings.db_path, "xtb-1000001").empty


def test_purchase_with_a_different_position_id_is_paired_by_time_and_volume(settings, export, tmp_path):
    from finance_analytics.sources.xtb import schema

    def change_ids(wb):
        ws = wb[schema.CASH_OPERATIONS.name]
        kind = schema.CASH_OPERATIONS.columns.index("Type") + 1
        pid = schema.CASH_OPERATIONS.columns.index("Position ID") + 1
        changed = 0
        for row in range(schema.CASH_OPERATIONS.header_row + 1, ws.max_row + 1):
            if ws.cell(row=row, column=kind).value == "Stock purchase" and changed < 3:
                ws.cell(row=row, column=pid).value = f"9{ws.cell(row=row, column=pid).value[1:]}"
                changed += 1

    import_xtb(_edit_usd_export(export, tmp_path, change_ids), settings)
    result = sync(settings)
    assert not [w for w in result.warnings if "no matching position" in w], result.warnings
    assert _count(settings, "positions", "purchase_value IS NULL") == 0


def test_reports_read_mixed_timestamp_formats_already_in_the_database(settings, export):
    """Databases built before timestamps were normalised hold both '...:SS' and '...:SS.ffffff'."""
    from finance_analytics import reports

    import_xtb(export, settings)
    sync(settings)
    with closing(sqlite3.connect(settings.db_path)) as conn:
        conn.execute("UPDATE positions SET open_time = open_time || '.123000' WHERE id % 2 = 0")
        conn.execute("UPDATE cash_ledger SET ts = ts || '.500000' WHERE id % 3 = 0")
        conn.commit()
    opened = reports.positions(settings.db_path, "xtb-1000001", open_only=True)
    assert opened["open_time"].notna().all()
    assert reports.cash_ledger(settings.db_path, "xtb-1000001")["ts"].notna().all()


def test_sub_accounts_stay_separate_and_remember_their_main_account(settings, export, tmp_path):
    """PLN, IKE and IKZE files of one login carry the main account in B1 but stay three accounts."""
    from openpyxl import load_workbook

    root = tmp_path / "sub_accounts"
    shutil.copytree(export, root)
    for path in root.rglob("*.xlsx"):
        if path.name.split("_")[0] in ("PLN", "IKE", "IKZE"):
            wb = load_workbook(path)
            for ws in wb.worksheets:
                ws["B1"] = "1000002"  # the PLN main account
            wb.save(path)
    import_xtb(root, settings)
    result = sync(settings)
    assert not result.errors, result.errors
    data = yaml.safe_load(settings.accounts_file.read_text(encoding="utf-8"))
    by_id = {a["id"]: a for a in data["accounts"]}
    assert by_id["xtb-20000003"]["tax_wrapper"] == "IKE" and by_id["xtb-20000003"]["parent_no"] == "1000002"
    assert by_id["xtb-20000004"]["tax_wrapper"] == "IKZE"
    assert by_id["xtb-1000002"]["parent_no"] is None  # B1 equals its own number
