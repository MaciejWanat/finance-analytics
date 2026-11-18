"""Import + sync: files in data/ -> projection tables, rebuilt only when needed."""

from __future__ import annotations

import shutil
import sqlite3
import zipfile
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
    assert yahoo_ticker("SXR8.DE") == "SXR8.DE"
    assert yahoo_ticker("PKN.PL") == "PKN.WA"
    assert yahoo_ticker("SAP.DE") == "SAP.DE"
    assert yahoo_ticker("COIN.DE", {"COIN.DE": "COIN.SW"}) == "COIN.SW"  # user override wins


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


def test_warns_when_an_open_position_has_no_purchase_history(settings, export, tmp_path):
    from finance_analytics.sources.xtb import schema

    def keep_only_blank_total(wb):
        ws = wb[schema.CASH_OPERATIONS.name]
        ws.delete_rows(schema.CASH_OPERATIONS.header_row + 1, ws.max_row)
        ws.append([schema.CASH_TOTAL_ROW])

    import_xtb(_edit_usd_export(export, tmp_path, keep_only_blank_total), settings)
    result = sync(settings)
    assert any("has no purchase value" in warning for warning in result.warnings)
    assert _count(settings, "positions", "close_time IS NULL AND purchase_value IS NULL") > 0


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


def test_user_yahoo_overrides_file(tmp_path):
    from finance_analytics.sources.sync import load_yahoo_overrides, yahoo_tickers_file

    config = tmp_path / "config"
    assert load_yahoo_overrides(config) == {}
    config.mkdir()
    yahoo_tickers_file(config).write_text("# c\nPKN.PL: PKN.WA\n", encoding="utf-8")
    assert load_yahoo_overrides(config) == {"PKN.PL": "PKN.WA"}
    yahoo_tickers_file(config).write_text("[broken: yaml", encoding="utf-8")
    assert load_yahoo_overrides(config) == {}


def _zip_of(folder, target, prefix="xStation5_export/"):
    with zipfile.ZipFile(target, "w") as archive:
        for path in sorted(folder.rglob("*.xlsx")):
            archive.write(path, prefix + path.relative_to(folder).as_posix())
        archive.writestr("__MACOSX/._junk.xlsx", b"junk")
    return target


def test_import_from_the_zip_xstation_saves(settings, export, tmp_path):
    from_folder = Settings(data_dir=tmp_path / "folder")
    expected = {p.relative_to(from_folder.raw_dir).as_posix() for p in import_xtb(export, from_folder).copied}
    archive = _zip_of(export, tmp_path / "export.zip")
    result = import_xtb(archive, settings)
    assert {p.relative_to(settings.raw_dir).as_posix() for p in result.copied} == expected and not result.skipped
    assert import_xtb(archive, settings).unchanged  # importing the same zip again changes nothing
    assert archive.exists()  # the source is only read


def test_folder_with_a_zip_and_a_broken_zip(settings, export, tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _zip_of(export, inbox / "export.zip")
    (inbox / "broken.zip").write_bytes(b"not a zip")
    result = import_xtb(inbox, settings)
    assert len(result.copied) == len(list(export.rglob("*.xlsx")))
    assert [p.name for p, _ in result.skipped] == ["broken.zip"]


def test_split_fractional_order_adds_every_part_to_the_position_cost():
    """D-048: XTB fills 12.3456 shares as 12 + 0.3456; the parts may carry different IDs and no ticker."""
    from datetime import datetime
    from types import SimpleNamespace as NS

    from finance_analytics.sources.sync import _fill, _match

    when = datetime(2026, 6, 8, 8, 30)
    position = NS(symbol="AAA.US", volume=12.3456, open_time=when)
    positions = {("acc", "P1"): (position, 1)}
    fraction = NS(symbol="AAA.US", ts=when, amount=-40.0, comment="OPEN BUY 0.3456/12.3456 @ 100.00")
    whole = NS(symbol="AAA.US", ts=when, amount=-1200.0, comment="OPEN BUY 12/12.3456 @ 100.00")
    other = NS(symbol="AAA.US", ts=when, amount=-500.0, comment="OPEN BUY 5 @ 100.00")  # another order
    ops = {("acc", "P1"): [fraction], ("acc", "X9"): [whole, other]}
    matched = _match(positions, ops, lambda p: p.open_time)
    assert [op.amount for op in matched[("acc", "P1")]] == [-40.0, -1200.0]
    assert _fill(fraction) == (0.3456, 12.3456) and _fill(other) == (5.0, 5.0)
    assert _fill(NS(comment="OPEN BUY VUAA.UK 1.5 @ 121.34")) == (1.5, 1.5)  # the format with a ticker


def test_two_positions_opened_together_do_not_steal_each_others_parts():
    from datetime import datetime
    from types import SimpleNamespace as NS

    from finance_analytics.sources.sync import _match

    when = datetime(2026, 7, 8, 18, 1)
    small = NS(symbol="BBB.US", volume=2.5, open_time=when)
    big = NS(symbol="BBB.US", volume=7.25, open_time=when)
    positions = {("acc", "S"): (small, 1), ("acc", "B"): (big, 1)}
    parts = [NS(symbol="BBB.US", ts=when, amount=-a, comment=c) for a, c in (
        (2.5, "OPEN BUY 0.25/7.25 @ 1.00"), (7.0, "OPEN BUY 7/7.25 @ 1.00"), (2.5, "OPEN BUY 2.5 @ 1.00"))]
    matched = _match(positions, {("acc", None): parts}, lambda p: p.open_time)
    assert sorted(op.comment for op in matched[("acc", "B")]) == ["OPEN BUY 0.25/7.25 @ 1.00", "OPEN BUY 7/7.25 @ 1.00"]
    assert [op.comment for op in matched[("acc", "S")]] == ["OPEN BUY 2.5 @ 1.00"]


def test_a_close_made_only_for_a_split_runs_until_the_real_sale():
    """D-051: XTB closes the old lot at its own open price, no sale; the shares are sold later."""
    from datetime import datetime
    from types import SimpleNamespace as NS

    from finance_analytics.sources.sync import _continue_split_closes
    from finance_analytics.sources.xtb.parser import Position

    old = Position("A1", "XYZ.US", 3.0, datetime(2019, 5, 2, 15), 420.0, close_time=datetime(2023, 3, 15),
                   close_price=420.0, purchase_value=1260.0, sale_value=1260.0)
    other = Position("B2", "XYZ.US", 1.0, datetime(2023, 8, 1, 15), 55.0, close_time=None)
    positions = {("usd", "A1"): (old, 1), ("usd", "B2"): (other, 1)}
    sale = NS(symbol="XYZ.US", ts=datetime(2024, 10, 7, 16), amount=1950.0, comment="CLOSE BUY 30 @ 65.00")
    elsewhere = NS(symbol="XYZ.US", ts=datetime(2024, 10, 9, 16), amount=60.0, comment="CLOSE BUY 1 @ 60.00")
    sell_for: dict = {}
    issues = []
    _continue_split_closes(positions, {("usd", "X"): [sale, elsewhere]}, sell_for,
                           lambda *args: issues.append(args[-1]))
    moved = positions[("usd", "A1")][0]
    assert (moved.close_time, moved.sale_value, moved.close_price) == (sale.ts, 1950.0, 65.0)
    assert sell_for[("usd", "A1")] == [sale]  # only the first day's sales
    assert any("stock split" in text for text in issues)
    # A real sale at the same price as the purchase, with its cash operation, is left alone.
    real = Position("C3", "AAA.US", 1.0, datetime(2025, 1, 2), 10.0, close_time=datetime(2025, 2, 2), close_price=10.0)
    kept = {("usd", "C3"): (real, 1)}
    _continue_split_closes(kept, {}, {("usd", "C3"): [NS()]}, lambda *args: None)
    assert kept[("usd", "C3")][0] is real


def test_position_listed_open_after_its_close_stays_open():
    """D-056: XTB keeps the position ID across a split (technical close) or a partial sale."""
    from datetime import date, datetime

    from finance_analytics.sources.sync import _merge_open_and_closed
    from finance_analytics.sources.xtb.parser import Position

    opened = datetime(2019, 5, 2, 15)
    technical = Position("A", "XYZ.US", 3.0, opened, 420.0, close_time=datetime(2023, 3, 15), close_price=420.0,
                         purchase_value=1260.0, sale_value=1260.0)
    after_split = Position("A", "XYZ.US", 30.0, opened, 42.0, purchase_value=1260.0)
    merged = _merge_open_and_closed({("usd", "A"): (after_split, 2, date(2026, 11, 15))},
                                    {("usd", "A"): [(technical, 1)]})
    assert merged == {("usd", "A"): (after_split, 2)}  # the split close is dropped, the shares stay

    partial = Position("B", "AAA.US", 4.0, opened, 10.0, close_time=datetime(2025, 3, 1), close_price=15.0,
                       purchase_value=40.0, sale_value=60.0)
    rest = Position("B", "AAA.US", 6.0, opened, 10.0, purchase_value=60.0)
    merged = _merge_open_and_closed({("usd", "B"): (rest, 2, date(2026, 11, 15))}, {("usd", "B"): [(partial, 1)]})
    assert merged[("usd", "B")][0] is partial and merged[("usd", "B/rest")][0].volume == 6.0

    # An open record from an export that ended before the sale is just out of date.
    sold = Position("C", "AAA.US", 1.0, opened, 10.0, close_time=datetime(2025, 3, 1), close_price=12.0)
    old_open = Position("C", "AAA.US", 1.0, opened, 10.0)
    merged = _merge_open_and_closed({("usd", "C"): (old_open, 1, date(2024, 12, 31))}, {("usd", "C"): [(sold, 2)]})
    assert merged == {("usd", "C"): (sold, 2)}


def test_rest_after_a_partial_sale_gets_the_rest_of_the_cost():
    """D-061: the purchase pairs with the sold part (same ID); what is left costs the remainder."""
    from datetime import datetime
    from types import SimpleNamespace as NS

    from finance_analytics.sources.sync import _rest_cost
    from finance_analytics.sources.xtb.parser import Position

    opened = datetime(2023, 3, 1)
    sold = Position("A", "ABC.US", 4.0, opened, 150.0, close_time=datetime(2025, 1, 2), close_price=240.0,
                    purchase_value=600.0, sale_value=960.0)
    rest = Position("A/rest", "ABC.US", 6.0, opened, 150.0)
    buy = NS(amount=-1500.0)
    assert _rest_cost({("usd", "A"): (sold, 1)}, {("usd", "A"): [buy]}, ("usd", "A"), rest) == 900.0
    unknown = Position("A", "ABC.US", 4.0, opened, 150.0, close_time=datetime(2025, 1, 2), close_price=240.0)
    assert _rest_cost({("usd", "A"): (unknown, 1)}, {("usd", "A"): [buy]}, ("usd", "A"), rest) == 900.0  # by volume
    assert _rest_cost({("usd", "A"): (sold, 1)}, {}, ("usd", "A"), rest) is None


def test_a_position_sold_in_several_parts_keeps_every_part_and_the_rest_costs_what_is_left():
    """D-079: each partial sale is its own Closed Positions row with the same ID; none may be lost."""
    from datetime import date, datetime
    from types import SimpleNamespace as NS

    from finance_analytics.sources.sync import _merge_open_and_closed, _rest_cost
    from finance_analytics.sources.xtb.parser import Position

    opened = datetime(2022, 3, 1, 15)
    first = Position("G", "ABC.US", 2.0, opened, 150.0, close_time=datetime(2024, 5, 2), close_price=200.0,
                     purchase_value=300.0, sale_value=400.0)
    second = Position("G", "ABC.US", 3.0, opened, 150.0, close_time=datetime(2025, 6, 3), close_price=250.0,
                      purchase_value=450.0, sale_value=750.0)
    rest = Position("G", "ABC.US", 5.0, opened, 150.0)
    merged = _merge_open_and_closed({("usd", "G"): (rest, 3, date(2026, 11, 15))},
                                    {("usd", "G"): [(second, 2), (first, 1)]})
    assert sorted(merged) == [("usd", "G"), ("usd", "G/part2"), ("usd", "G/rest")]
    assert merged[("usd", "G")][0] is first and merged[("usd", "G/part2")][0].volume == 3.0
    assert sum(p.volume for p, _ in merged.values()) == 10.0  # every share bought is somewhere

    buy = NS(amount=-1500.0)
    assert _rest_cost(merged, {("usd", "G"): [buy]}, ("usd", "G"), merged[("usd", "G/rest")][0]) == 750.0
    # Without the purchase value of one part, the purchases are split by volume.
    unknown = {**merged, ("usd", "G/part2"): (Position("G/part2", "ABC.US", 3.0, opened, 150.0,
                                                       close_time=datetime(2025, 6, 3)), 2)}
    assert _rest_cost(unknown, {("usd", "G"): [buy]}, ("usd", "G"), merged[("usd", "G/rest")][0]) == 750.0

    # Sold to the end in two parts: both stay, no rest.
    merged = _merge_open_and_closed({}, {("usd", "G"): [(first, 1), (second, 2)]})
    assert sorted(merged) == [("usd", "G"), ("usd", "G/part2")]
