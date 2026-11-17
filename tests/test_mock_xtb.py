"""The mock export must have exactly the structure the inspector saw in a real export."""

from __future__ import annotations

from collections import Counter
from datetime import datetime

import inspect_xtb_export as inspector
import pytest
from openpyxl import load_workbook

from finance_analytics.mock.xtb_export import ACCOUNTS, ETFS, STOCKS, write_mock_export
from finance_analytics.sources.xtb import schema

CASH = {name: i for i, name in enumerate(schema.CASH_OPERATIONS.columns)}
OPEN = {name: i for i, name in enumerate(schema.OPEN_POSITIONS.columns)}


@pytest.fixture(scope="module")
def export(tmp_path_factory):
    root = tmp_path_factory.mktemp("xtb_export")
    return root, write_mock_export(root)


def _rows(path, layout):
    ws = load_workbook(path, read_only=True)[layout.name]
    return list(ws.iter_rows(min_row=layout.header_row + 1, values_only=True))


def test_folder_layout_matches_real_export(export):
    root, paths = export
    assert len(paths) == len(ACCOUNTS)
    for path, account in zip(paths, ACCOUNTS, strict=True):
        assert path.parent == root / account.folder
        assert inspector.split_prefix(path.name) == account.prefix
    # One folder can hold several account files with different numbers (seen in the real export).
    assert len({p.parent for p in paths}) < len(paths)


def test_sheets_and_headers_match_schema(export):
    _, paths = export
    for path in paths:
        loaded = inspector.load_file(path, "konto")
        assert [s.name for s in loaded.sheets] == [layout.name for layout in schema.SHEETS]
        for sheet, layout in zip(loaded.sheets, schema.SHEETS, strict=True):
            assert sheet.header_index + 1 == layout.header_row, (path.name, layout.name)
            assert tuple(sheet.headers) == layout.columns, (path.name, layout.name)


@pytest.mark.parametrize("account", ACCOUNTS, ids=lambda a: a.prefix)
def test_cash_operations(export, account):
    _, paths = export
    path = next(p for p in paths if p.name.startswith(f"{account.prefix}_"))
    rows = _rows(path, schema.CASH_OPERATIONS)
    data, total = rows[:-1], rows[-1]

    assert total[CASH["Type"]] == schema.CASH_TOTAL_ROW
    assert total[CASH["Amount"]] == pytest.approx(sum(r[CASH["Amount"]] for r in data), abs=0.01)
    times = [r[CASH["Time"]] for r in data]
    assert all(isinstance(t, datetime) for t in times) and times == sorted(times)
    ids = [r[CASH["ID"]] for r in data]
    assert all(isinstance(i, str) and len(i) == 10 and i.isdigit() for i in ids) and len(set(ids)) == len(ids)

    kinds = Counter(r[CASH["Type"]] for r in data)
    assert set(kinds) <= set(schema.CASH_TYPES_OBSERVED) | set(schema.CASH_TYPES_ASSUMED)
    assert ("Free funds interest tax" in kinds) is not account.tax_wrapper  # no tax on IKE/IKZE
    months = 24
    assert kinds["Deposit"] >= months
    purchases = [r for r in data if r[CASH["Type"]] == "Stock purchase"]
    etf_buys = [r for r in purchases if r[CASH["Ticker"]] in ETFS]
    stock_buys = [r for r in purchases if r[CASH["Ticker"]] in STOCKS]
    assert len(etf_buys) >= months * len(account.etfs) * 0.9  # monthly ETF plan
    assert 2 <= len(stock_buys) <= 8 * 2  # a few single stocks a year

    for r in data:
        kind, amount = r[CASH["Type"]], r[CASH["Amount"]]
        assert r[CASH["Product"]] == schema.PRODUCT
        if kind == "Stock purchase":
            assert amount < 0 and r[CASH["Comment"]].startswith(f"OPEN BUY {r[CASH['Ticker']]} ")
            assert r[CASH["Position ID"]] is not None
        elif kind in ("Withholding tax", "Free funds interest tax"):
            assert amount < 0
        else:
            assert amount > 0


@pytest.mark.parametrize("account", ACCOUNTS, ids=lambda a: a.prefix)
def test_open_positions(export, account):
    _, paths = export
    path = next(p for p in paths if p.name.startswith(f"{account.prefix}_"))
    rows = _rows(path, schema.OPEN_POSITIONS)
    cash_rows = _rows(path, schema.CASH_OPERATIONS)

    summaries = [r for r in rows if r[OPEN["Category"]] is not None]
    positions = [r for r in rows if r[OPEN["Type"]] == "BUY"]
    assert summaries and positions and len(summaries) + len(positions) == len(rows)
    assert rows[0] in summaries  # a summary row opens each instrument group
    for s in summaries:
        own = [p for p in positions if p[OPEN["Ticker"]] == s[OPEN["Ticker"]]]
        assert s[OPEN["Volume"]] == pytest.approx(sum(p[OPEN["Volume"]] for p in own), abs=1e-4)
        assert s[OPEN["Value"]] == pytest.approx(sum(p[OPEN["Value"]] for p in own), abs=0.05)
    assert {r[OPEN["Ticker"]].rsplit(".", 1)[1] for r in rows} <= {s[1:] for s in schema.TICKER_SUFFIXES_OBSERVED}
    # Open positions = everything bought minus everything sold.
    bought = {r[CASH["Position ID"]] for r in cash_rows if r[CASH["Type"]] == "Stock purchase"}
    sold = {r[CASH["Position ID"]] for r in cash_rows if r[CASH["Type"]] == "Stock sell"}
    assert {p[OPEN["Instrument/Position"]] for p in positions} == bought - sold


CLOSED = {name: i for i, name in enumerate(schema.CLOSED_POSITIONS.columns)}


def test_closed_positions_match_sales(export):
    _, paths = export
    total_closed = 0
    for path in paths:
        *closed, total = _rows(path, schema.CLOSED_POSITIONS)
        assert total[CLOSED["Instrument"]] == schema.CLOSED_TOTAL_ROW
        sales = {
            r[CASH["Position ID"]]: r
            for r in _rows(path, schema.CASH_OPERATIONS)
            if r[CASH["Type"]] == "Stock sell"
        }
        assert {r[CLOSED["Position ID"]] for r in closed} == set(sales)
        for r in closed:
            sale = sales[r[CLOSED["Position ID"]]]
            assert r[CLOSED["Sale Value"]] == pytest.approx(sale[CASH["Amount"]], abs=0.01)
            expected_profit = r[CLOSED["Sale Value"]] - r[CLOSED["Purchase Value"]]
            assert r[CLOSED["Profit/Loss"]] == pytest.approx(expected_profit, abs=0.01)
            assert r[CLOSED["Open Time (UTC)"]] < r[CLOSED["Close Time (UTC)"]]
            assert r[CLOSED["Category"]] == "STOCK"
        total_closed += len(closed)
    assert total_closed >= len(ACCOUNTS)  # sales happen on the accounts


def test_styling_mirrors_the_real_export(export):
    _, paths = export
    wb = load_workbook(paths[0])
    for layout in schema.SHEETS:
        ws = wb[layout.name]
        header = ws.cell(row=layout.header_row, column=1)
        assert header.fill.fgColor.rgb.endswith("000000") and header.font.bold
        assert ws["A2"].font.bold
    ws = wb[schema.OPEN_POSITIONS.name]
    assert ws["A8"].value == "Note" and ws["A8"].fill.fgColor.rgb.endswith("FFF2CC") and ws["B8"].font.italic
    first = schema.OPEN_POSITIONS.header_row + 1  # an instrument summary row
    assert ws.cell(row=first, column=1).font.bold and ws.cell(row=first, column=2).font.bold
    assert not ws.cell(row=first + 1, column=1).font.bold  # "My Trades" on a position row
    assert all(c.font.name == "Calibri" for sheet in wb.worksheets for row in sheet.iter_rows() for c in row if c.value)
    cash = wb[schema.CASH_OPERATIONS.name]
    amount = schema.CASH_OPERATIONS.columns.index("Amount") + 1
    for row in range(schema.CASH_OPERATIONS.header_row + 1, cash.max_row + 1):
        cell = cash.cell(row=row, column=amount)
        if cell.value:
            assert cell.font.color.rgb.endswith("00B050" if cell.value > 0 else "FF0000")
    net = schema.OPEN_POSITIONS.columns.index("Net Profit") + 1
    for row in range(first, ws.max_row + 1):
        cell = ws.cell(row=row, column=net)
        if cell.value:
            assert cell.font.color.rgb.endswith("00B050" if cell.value > 0 else "FF0000")


def test_dates_are_readable_in_excel(export):
    _, paths = export
    ws = load_workbook(paths[0])[schema.CASH_OPERATIONS.name]
    assert ws["B3"].number_format == "yyyy-mm-dd hh:mm:ss"
    assert ws["B3"].value.hour in (22, 23)  # Polish midnight, in UTC
    assert ws.column_dimensions["B"].width >= 19


def test_mock_contains_no_private_looking_data(export):
    import check_no_private_data as check

    _, paths = export
    for path in paths:
        wb = load_workbook(path, read_only=True)
        # One cell per line, as each value would appear on its own; joining cells with
        # spaces glues neighbouring IDs into card-number lookalikes.
        cells = [str(v) for ws in wb.worksheets for row in ws.iter_rows(values_only=True) for v in row if v]
        assert check.scan_text("\n".join(cells)) == [], path.name


@pytest.mark.parametrize("account", ACCOUNTS, ids=lambda a: a.prefix)
def test_amounts_are_consistent_across_sheets(export, account):
    """Every money figure must agree with the operations it comes from, to the cent."""
    _, paths = export
    path = next(p for p in paths if p.name.startswith(f"{account.prefix}_"))
    cash = _rows(path, schema.CASH_OPERATIONS)[:-1]
    opened = _rows(path, schema.OPEN_POSITIONS)
    closed = _rows(path, schema.CLOSED_POSITIONS)[:-1]
    buys = {r[CASH["Position ID"]]: r for r in cash if r[CASH["Type"]] == "Stock purchase"}
    sales = {r[CASH["Position ID"]]: r for r in cash if r[CASH["Type"]] == "Stock sell"}

    # Cash never goes negative.
    balance = 0.0
    for r in cash:
        balance = round(balance + r[CASH["Amount"]], 2)
        assert balance >= 0, r

    # Purchases: comment volume/price = position; on a USD account amount = volume x price.
    positions = [r for r in opened if r[OPEN["Type"]] == "BUY"]
    for r in positions:
        buy = buys[r[OPEN["Instrument/Position"]]]
        _, _, ticker, volume, _, price = buy[CASH["Comment"]].split()
        assert (ticker, float(volume), float(price)) == (r[OPEN["Ticker"]], r[OPEN["Volume"]], r[OPEN["Open price"]])
        # Net Profit = Value - what was paid.
        assert r[OPEN["Value"]] - r[OPEN["Net Profit"]] == pytest.approx(-buy[CASH["Amount"]], abs=0.011)
    if account.currency == "USD":
        for buy in buys.values():
            _, _, _, volume, _, price = buy[CASH["Comment"]].split()
            assert float(volume) * float(price) == pytest.approx(-buy[CASH["Amount"]], abs=0.011)

    # Summary rows and the header block are exact sums.
    summaries = [r for r in opened if r[OPEN["Category"]] is not None]
    for s in summaries:
        own = [r for r in positions if r[OPEN["Ticker"]] == s[OPEN["Ticker"]]]
        for column in ("Value", "Net Profit", "Gross Profit"):
            assert s[OPEN[column]] == pytest.approx(sum(r[OPEN[column]] for r in own), abs=0.005), column
    ws = load_workbook(path, read_only=True)[schema.OPEN_POSITIONS.name]
    value_row, profit_row = ws.iter_rows(min_row=5, max_row=6, values_only=True)
    assert value_row[2] == pytest.approx(sum(s[OPEN["Value"]] for s in summaries), abs=0.005)
    assert profit_row[2] == pytest.approx(sum(s[OPEN["Net Profit"]] for s in summaries), abs=0.005)

    # Closed positions: purchase and sale values are the cash amounts.
    for r in closed:
        position_id = r[CLOSED["Position ID"]]
        assert r[CLOSED["Purchase Value"]] == pytest.approx(-buys[position_id][CASH["Amount"]], abs=0.005)
        assert r[CLOSED["Sale Value"]] == pytest.approx(sales[position_id][CASH["Amount"]], abs=0.005)

    # Withholding tax is 15% of its dividend; interest tax 19% of its interest.
    def paired(kind, tax_kind):
        gross = {(r[CASH["Ticker"]], r[CASH["Time"]]): r[CASH["Amount"]] for r in cash if r[CASH["Type"]] == kind}
        return [(gross[(r[CASH["Ticker"]], r[CASH["Time"]])], -r[CASH["Amount"]])
                for r in cash if r[CASH["Type"]] == tax_kind]

    for gross, tax in paired("Dividend", "Withholding tax"):
        assert tax == pytest.approx(round(gross * 0.15, 2), abs=0.001)
    for gross, tax in paired("Free funds interest", "Free funds interest tax"):
        assert tax == pytest.approx(round(gross * 0.19, 2), abs=0.001)

    # On a USD account a dividend is shares held on the pay date x dividend per share.
    if account.currency == "USD":
        for d in (r for r in cash if r[CASH["Type"]] == "Dividend"):
            per_share = float(d[CASH["Comment"]].split()[2].rstrip("/"))
            held = sum(
                float(b[CASH["Comment"]].split()[3])
                for pid, b in buys.items()
                if b[CASH["Ticker"]] == d[CASH["Ticker"]] and b[CASH["Time"]] < d[CASH["Time"]]
                and (pid not in sales or sales[pid][CASH["Time"]] > d[CASH["Time"]])
            )
            assert held * per_share == pytest.approx(d[CASH["Amount"]], abs=0.011)
