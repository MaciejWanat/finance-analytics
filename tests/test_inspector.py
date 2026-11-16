"""The inspector must describe structure without leaking values.

The workbook built here is a generic, invented layout (metadata block, header row,
data rows, a total row). It is NOT the real XTB format; the inspector does not
assume any particular sheet or column names.
"""

from __future__ import annotations

from datetime import datetime

import inspect_xtb_export as inspector
import pytest
from openpyxl import Workbook
from test_privacy_check import fake_pl_iban

PERSON = "Jan Kowalski"
ACCOUNT_NO = "51234567"
IBAN = fake_pl_iban()


def _write_export(root):
    folder = root / ACCOUNT_NO
    folder.mkdir(parents=True)
    path = folder / f"USD_{ACCOUNT_NO}_2025-01-01_2025-12-31.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Operations"
    ws.append(["Client", PERSON])
    ws.append(["Account", int(ACCOUNT_NO)])
    ws.append([])
    ws.append(["ID", "Type", "Time", "Symbol", "Comment", "Amount"])
    rows = [
        (101, "Stock purchase", datetime(2025, 3, 4, 15, 30, 12), "AAPL.US", "OPEN BUY 5 @ 123.45", -617.25),
        (102, "Stock purchase", datetime(2025, 3, 5, 10, 1, 0), "VWCE.DE", "OPEN BUY 2 @ 110.10", -220.2),
        (103, "Deposit", datetime(2025, 3, 1, 9, 0, 0), None, f"Transfer from {PERSON} {IBAN}", 5000.0),
        (104, "Dividend", datetime(2025, 5, 15, 8, 0, 0), "AAPL.US", "AAPL.US USD 0.2500/ SHR", 1.25),
    ]
    for row in rows:
        ws.append(list(row))
    ws.append(["Total", None, None, None, None, 4163.8])
    wb.create_sheet("Empty")
    wb.save(path)
    return path


@pytest.fixture
def export_root(tmp_path):
    root = tmp_path / "export"
    _write_export(root)
    return root


def test_report_describes_structure(export_root):
    report = inspector.build_report(
        [inspector.load_file(p, a) for a, p in inspector.discover(export_root)], show_symbols=False
    )
    assert "konto_1" in report
    assert "`USD_99999999_9999-99-99_9999-99-99.xlsx`" in report
    assert "| USD |" in report
    assert "header row (1-based): 4" in report
    for header in ("ID", "Type", "Time", "Symbol", "Comment", "Amount"):
        assert f"| {header} |" in report
    assert "`Stock purchase` (2)" in report  # enumerations stay readable
    assert "`OPEN BUY 9 @ 999.99` (2)" in report  # comments become patterns
    assert "`AAAA.US`" in report and "`AAAA.DE`" in report
    assert "Excel dates with seconds" in report
    assert "unique, 3–3 digits" in report
    assert "`Total`" in report  # the summary row is visible as a tail row


def test_report_leaks_no_values(export_root):
    report = inspector.build_report(
        [inspector.load_file(p, a) for a, p in inspector.discover(export_root)], show_symbols=False
    )
    for secret in ("Jan", "Kowalski", ACCOUNT_NO, IBAN, IBAN[2:], "AAPL", "VWCE", "123.45", "617", "5000", "4163"):
        assert secret not in report, secret


def test_show_symbols_reveals_only_symbols(export_root):
    report = inspector.build_report(
        [inspector.load_file(p, a) for a, p in inspector.discover(export_root)], show_symbols=True
    )
    assert "`AAPL.US`" in report and "`VWCE.DE`" in report
    assert "Kowalski" not in report and ACCOUNT_NO not in report


def test_cli_writes_report_and_refuses_output_inside_export(export_root, tmp_path):
    out = tmp_path / "samples" / "report.md"
    assert inspector.main([str(export_root), "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("# XTB export structure report")
    with pytest.raises(SystemExit):
        inspector.main([str(export_root), "--out", str(export_root / "report.md")])


def test_masking_helpers():
    assert inspector.mask_text("Deposit 1234 from Anna") == "Deposit 9999 from Xxxx"
    assert inspector.mask_symbol("PKN.PL") == "AAA.PL"
    assert inspector.mask_symbol("BRK.B.US") == "AAA.A.US"
    assert inspector.split_prefix("IKZE_123.xlsx") == "IKZE"
    assert inspector.split_prefix("IKE_123.xlsx") == "IKE"
    assert inspector.split_prefix("report.xlsx") is None
