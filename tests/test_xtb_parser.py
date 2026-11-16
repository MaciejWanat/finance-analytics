"""XTB parser on the synthetic export (same layout as the real one)."""

from __future__ import annotations

import shutil

import pytest
from openpyxl import Workbook, load_workbook

from finance_analytics.mock.xtb_export import write_mock_export
from finance_analytics.sources.xtb import schema
from finance_analytics.sources.xtb.parser import XtbFormatError, parse_file, parse_file_name


@pytest.fixture(scope="module")
def export(tmp_path_factory):
    root = tmp_path_factory.mktemp("export")
    return {p.name.split("_")[0]: p for p in write_mock_export(root)}


def _rows(path, layout):
    ws = load_workbook(path, read_only=True)[layout.name]
    return list(ws.iter_rows(min_row=layout.header_row + 1, values_only=True))


def test_file_name():
    prefix, number, start, end = parse_file_name("IKZE_20000004_2024-11-01_2026-11-13.xlsx")
    assert (prefix, number, start.isoformat(), end.isoformat()) == ("IKZE", "20000004", "2024-11-01", "2026-11-13")
    assert parse_file_name("USD_1000001_2024-11-01_2026-11-13__ab12cd34.xlsx")[1] == "1000001"
    with pytest.raises(XtbFormatError):
        parse_file_name("report.xlsx")


@pytest.mark.parametrize("prefix", ["USD", "PLN", "EUR", "IKE", "IKZE"])
def test_parses_every_row(export, prefix):
    path = export[prefix]
    parsed = parse_file(path)
    cash_rows = _rows(path, schema.CASH_OPERATIONS)[:-1]
    open_rows = [r for r in _rows(path, schema.OPEN_POSITIONS) if r[4] == "BUY"]
    closed_rows = _rows(path, schema.CLOSED_POSITIONS)[:-1]

    assert parsed.prefix == prefix and not parsed.empty
    assert parsed.currency == ("PLN" if prefix in ("IKE", "IKZE") else prefix)
    assert parsed.tax_wrapper == (prefix if prefix in ("IKE", "IKZE") else None)
    assert len(parsed.cash) == len(cash_rows)
    assert len(parsed.open_positions) == len(open_rows)
    assert len(parsed.closed_positions) == len(closed_rows)
    assert round(sum(op.amount for op in parsed.cash), 2) == pytest.approx(
        _rows(path, schema.CASH_OPERATIONS)[-1][5], abs=0.01
    )
    assert all(isinstance(op.operation_id, str) for op in parsed.cash)
    assert {i.category for i in parsed.instruments.values()} <= {"ETF", "STOCK"}
    # Only the assumed-format notices; no structural warnings on a consistent export.
    assert all("assumed" in w for w in parsed.warnings), parsed.warnings


def test_empty_account_file(tmp_path):
    wb = Workbook()
    wb.active.title = schema.SHEETS[0].name
    for layout in schema.SHEETS[1:]:
        wb.create_sheet(layout.name)
    path = tmp_path / "PLN_1234567_2026-10-01_2026-11-01.xlsx"
    wb.save(path)
    parsed = parse_file(path)
    assert parsed.empty and parsed.account_number == "1234567" and not parsed.cash


def _modified_copy(export, tmp_path, edit):
    target = tmp_path / export["USD"].name
    shutil.copy(export["USD"], target)
    wb = load_workbook(target)
    edit(wb)
    wb.save(target)
    return target


def test_rejects_changed_header(export, tmp_path):
    def rename(wb):
        wb[schema.CASH_OPERATIONS.name].cell(row=schema.CASH_OPERATIONS.header_row, column=6).value = "Kwota"

    with pytest.raises(XtbFormatError, match=r"missing \['Amount'\], unexpected \['Kwota'\]"):
        parse_file(_modified_copy(export, tmp_path, rename))


def test_rejects_unknown_cash_type(export, tmp_path):
    def unknown(wb):
        wb[schema.CASH_OPERATIONS.name].cell(row=schema.CASH_OPERATIONS.header_row + 1, column=1).value = "Swap"

    with pytest.raises(XtbFormatError, match="unknown cash operation types"):
        parse_file(_modified_copy(export, tmp_path, unknown))


def test_rejects_cfd_category(export, tmp_path):
    def cfd(wb):
        wb[schema.OPEN_POSITIONS.name].cell(row=schema.OPEN_POSITIONS.header_row + 1, column=4).value = "CFD"

    with pytest.raises(XtbFormatError, match="unsupported instrument category 'CFD'"):
        parse_file(_modified_copy(export, tmp_path, cfd))


def test_sub_account_keeps_its_file_name_number_and_records_the_main_account(export, tmp_path):
    """IKE/IKZE are sub-accounts: B1 holds the main account, the file name the sub-account (D-033)."""
    def main_account_in_b1(wb):
        for ws in wb.worksheets:
            ws["B1"] = "7777777"

    parsed = parse_file(_modified_copy(export, tmp_path, main_account_in_b1))
    assert parsed.account_number == "1000001" and parsed.parent_number == "7777777"
    assert parsed.cash and not [w for w in parsed.warnings if "main account" in w]


def test_rejects_a_sheet_without_the_account_label(export, tmp_path):
    def broken_label(wb):
        wb[schema.CASH_OPERATIONS.name]["A1"] = "Something else"

    with pytest.raises(XtbFormatError, match="Account number"):
        parse_file(_modified_copy(export, tmp_path, broken_label))
