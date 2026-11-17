"""Parse one xStation account-history xlsx file into plain records.

Pure function of the file: no database, no network. Layout comes from `schema`.
The parser is strict (D-006, D-007): a header that differs from the schema, an
unknown cash operation type or an unsupported instrument category makes the whole
file fail with `XtbFormatError`, so that partial data never reaches the valuation.
Softer findings (assumed formats, small mismatches) become warnings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook

from finance_analytics.sources.xtb import schema

PARSER_VERSION = 11  # bump when parsing or projection changes; `fa sync` then rebuilds everything

FILE_NAME_RE = re.compile(
    r"^(?P<prefix>IKZE|IKE|PLN|EUR|USD)_(?P<number>\d+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})"
    r"(?:__[0-9a-f]+)?\.xlsx$"
)
OPEN_BUY_RE = re.compile(r"^OPEN BUY (?P<ticker>\S+) (?P<volume>[\d.]+) @ (?P<price>[\d.]+)$")

# Export label -> ledger type. Labels in ASSUMED are accepted with a warning.
CASH_TYPE_MAP = {
    "Deposit": "DEPOSIT",
    "Stock purchase": "BUY",
    "Dividend": "DIVIDEND",
    "Withholding tax": "WHT",
    "Free funds interest": "INTEREST",
    "Free funds interest tax": "INTEREST_TAX",
    "Stock sale": "SELL",  # assumed (schema.CASH_TYPES_ASSUMED)
}
CATEGORY_TO_ASSET_CLASS = {"ETF": "etf", "STOCK": "stock", "ETC": "other", "ETN": "other"}
ACCOUNT_CURRENCY = {"PLN": "PLN", "EUR": "EUR", "USD": "USD", "IKE": "PLN", "IKZE": "PLN"}


class XtbFormatError(ValueError):
    """The file does not match the known export layout; nothing from it is imported."""


@dataclass(frozen=True)
class InstrumentInfo:
    symbol: str
    name: str | None
    category: str | None


@dataclass(frozen=True)
class CashOperation:
    broker_type: str
    ledger_type: str
    ts: datetime
    amount: float
    operation_id: str
    symbol: str | None
    position_id: str | None
    comment: str | None


@dataclass(frozen=True)
class Position:
    position_id: str
    symbol: str
    volume: float
    open_time: datetime
    open_price: float
    close_time: datetime | None = None
    close_price: float | None = None
    purchase_value: float | None = None
    sale_value: float | None = None


@dataclass
class ParsedFile:
    path: Path
    prefix: str
    account_number: str
    currency: str
    tax_wrapper: str | None
    date_from: date
    date_to: date
    empty: bool = False
    # B1 of a sub-account (IKE, IKZE, …) holds the main account's number; the file name holds
    # the sub-account's own number, which identifies the account (D-015, D-033).
    parent_number: str | None = None
    cash: list[CashOperation] = field(default_factory=list)
    open_positions: list[Position] = field(default_factory=list)
    closed_positions: list[Position] = field(default_factory=list)
    instruments: dict[str, InstrumentInfo] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


# ----------------------------------------------------------------------- helpers


def parse_file_name(name: str) -> tuple[str, str, date, date]:
    match = FILE_NAME_RE.match(name)
    if not match:
        raise XtbFormatError(
            f"unexpected file name {name!r}; expected <PLN|EUR|USD|IKE|IKZE>_<number>_<from>_<to>.xlsx"
        )
    return (
        match["prefix"],
        match["number"],
        date.fromisoformat(match["start"]),
        date.fromisoformat(match["end"]),
    )


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _id(value: object) -> str | None:
    """IDs are text in the export; tolerate numbers (e.g. after re-saving in Excel)."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return _text(value)


def _number(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise XtbFormatError(f"{what}: expected a number, got {value!r}")
    return float(value)


def _moment(value: object, what: str) -> datetime:
    if not isinstance(value, datetime):
        raise XtbFormatError(f"{what}: expected a date-time, got {value!r}")
    return value


def _sheet_rows(sheet) -> list[tuple]:
    """Read all populated cells even when an export declares a stale worksheet dimension.

    Some xStation exports declare their used range as A1 despite containing data.
    Read-only OpenPyXL otherwise trusts that metadata and yields only an empty cell.
    """
    sheet.reset_dimensions()
    return [tuple(row) for row in sheet.iter_rows(values_only=True)]


def _check_header(sheet_rows: list[tuple], layout: schema.SheetLayout, header_row: int | None = None) -> int:
    """Validate a header and return its 1-based row number."""
    header_row = header_row or layout.header_row
    if len(sheet_rows) < header_row:
        raise XtbFormatError(f"sheet {layout.name!r}: no header row {header_row}")
    found = tuple(_text(c) for c in sheet_rows[header_row - 1])
    found = tuple(c for c in found if c is not None)
    if found != layout.columns:
        missing = [c for c in layout.columns if c not in found]
        extra = [c for c in found if c not in layout.columns]
        detail = f"missing {missing}, unexpected {extra}" if missing or extra else "same columns, different order"
        raise XtbFormatError(f"sheet {layout.name!r}: header row {header_row} does not match ({detail})")
    return header_row


def _records(
    sheet_rows: list[tuple], layout: schema.SheetLayout, header_row: int | None = None,
) -> list[dict[str, object]]:
    header_row = header_row or layout.header_row
    records = []
    for row in sheet_rows[header_row:]:
        if all(_text(c) is None for c in row):
            continue
        padded = tuple(row) + (None,) * (len(layout.columns) - len(row))
        records.append(dict(zip(layout.columns, padded, strict=False)))
    return records


def _remember(parsed: ParsedFile, symbol: str | None, name: object, category: object) -> None:
    if not symbol:
        return
    category = _text(category)
    if category is not None and category not in CATEGORY_TO_ASSET_CLASS:
        raise XtbFormatError(
            f"{symbol}: unsupported instrument category {category!r} (v1 supports stocks and ETFs only, D-007)"
        )
    known = parsed.instruments.get(symbol)
    parsed.instruments[symbol] = InstrumentInfo(
        symbol=symbol,
        name=_text(name) or (known.name if known else None),
        category=category or (known.category if known else None),
    )


# ------------------------------------------------------------------------ sheets


def _has_table(rows: list[tuple], layout: schema.SheetLayout) -> bool:
    """True when the sheet reaches its header row and that row is not empty."""
    return len(rows) >= layout.header_row and any(_text(c) is not None for c in rows[layout.header_row - 1])


def _open_positions_header_row(rows: list[tuple]) -> int | None:
    """Find the position-table header after its variable-length summary table.

    XTB puts a Product / Metric / Amount / Currency summary before this table. Its
    number of rows varies by account, so the position-table header cannot be tied to
    a fixed row number. The first two header cells distinguish it from the summary.
    """
    layout = schema.OPEN_POSITIONS
    for row_number, row in enumerate(rows, start=1):
        first = _text(row[0]) if len(row) > 0 else None
        second = _text(row[1]) if len(row) > 1 else None
        if first != layout.columns[0] or second != layout.columns[1]:
            continue
        return _check_header(rows, layout, row_number)
    return None


def _parse_cash(parsed: ParsedFile, rows: list[tuple]) -> None:
    layout = schema.CASH_OPERATIONS
    _check_header(rows, layout)
    records = _records(rows, layout)
    if not records:
        return  # a header without operations
    if records[-1]["Type"] != schema.CASH_TOTAL_ROW:
        raise XtbFormatError(f"sheet {layout.name!r}: missing the {schema.CASH_TOTAL_ROW!r} row at the end")
    *operations, total = records
    if not operations and total["Amount"] is None:
        return  # an empty account can still carry a blank Total row
    unknown = sorted({str(r["Type"]) for r in operations if r["Type"] not in CASH_TYPE_MAP})
    if unknown:
        raise XtbFormatError(f"unknown cash operation types {unknown}; the parser must learn them first (Q-006)")
    assumed = sorted({str(r["Type"]) for r in operations if r["Type"] in schema.CASH_TYPES_ASSUMED})
    if assumed:
        parsed.warnings.append(f"cash operation types {assumed} use an assumed, unconfirmed format (Q-006)")

    for i, r in enumerate(operations, start=layout.header_row + 1):
        where = f"{layout.name} row {i}"
        symbol = _text(r["Ticker"])
        _remember(parsed, symbol, r["Instrument"], r["Category"])
        operation_id = _id(r["ID"])
        if operation_id is None:
            raise XtbFormatError(f"{where}: missing ID")
        parsed.cash.append(
            CashOperation(
                broker_type=str(r["Type"]),
                ledger_type=CASH_TYPE_MAP[str(r["Type"])],
                ts=_moment(r["Time"], f"{where} Time"),
                amount=_number(r["Amount"], f"{where} Amount"),
                operation_id=operation_id,
                symbol=symbol,
                position_id=_id(r["Position ID"]),
                comment=_text(r["Comment"]),
            )
        )
    listed = round(sum(op.amount for op in parsed.cash), 2)
    if abs(listed - _number(total["Amount"], f"{layout.name} total")) > 0.011:
        parsed.warnings.append(f"{layout.name}: Total {total['Amount']} differs from the sum of rows {listed}")


def _parse_open(parsed: ParsedFile, rows: list[tuple]) -> None:
    layout = schema.OPEN_POSITIONS
    header_row = _open_positions_header_row(rows)
    if header_row is None:
        return
    current: dict[str, object] | None = None
    summaries: list[tuple[dict[str, object], list[Position]]] = []
    for i, r in enumerate(_records(rows, layout, header_row), start=header_row + 1):
        where = f"{layout.name} row {i}"
        symbol = _text(r["Ticker"])
        if not symbol:
            raise XtbFormatError(f"{where}: missing Ticker")
        if _text(r["Category"]) is not None:  # instrument summary row
            _remember(parsed, symbol, r["Instrument/Position"], r["Category"])
            current = r
            summaries.append((r, []))
            continue
        if r["Type"] != "BUY":
            raise XtbFormatError(f"{where}: unsupported position type {r['Type']!r} (only BUY is known)")
        if current is None or current["Ticker"] != symbol:
            raise XtbFormatError(f"{where}: position without its instrument summary row above it")
        position = Position(
            position_id=_id(r["Instrument/Position"]) or "",
            symbol=symbol,
            volume=_number(r["Volume"], f"{where} Volume"),
            open_time=_moment(r["Open time (UTC)"], f"{where} Open time"),
            open_price=_number(r["Open price"], f"{where} Open price"),
        )
        if not position.position_id:
            raise XtbFormatError(f"{where}: missing position ID")
        parsed.open_positions.append(position)
        summaries[-1][1].append(position)
    for summary, own in summaries:
        total = sum(p.volume for p in own)
        if abs(total - _number(summary["Volume"], f"{summary['Ticker']} summary Volume")) > 1e-6:
            parsed.warnings.append(
                f"{layout.name}: {summary['Ticker']} summary volume {summary['Volume']} != sum of positions {total:g}"
            )


def _parse_closed(parsed: ParsedFile, rows: list[tuple]) -> None:
    layout = schema.CLOSED_POSITIONS
    _check_header(rows, layout)
    records = _records(rows, layout)
    if records and records[-1]["Instrument"] == schema.CLOSED_TOTAL_ROW:
        records = records[:-1]
    for i, r in enumerate(records, start=layout.header_row + 1):
        where = f"{layout.name} row {i}"
        symbol = _text(r["Ticker"])
        if not symbol:
            raise XtbFormatError(f"{where}: missing Ticker")
        if r["Type"] != "BUY":
            raise XtbFormatError(f"{where}: unsupported position type {r['Type']!r} (only BUY is known)")
        _remember(parsed, symbol, r["Instrument"], r["Category"])
        position_id = _id(r["Position ID"])
        if not position_id:
            raise XtbFormatError(f"{where}: missing Position ID")
        parsed.closed_positions.append(
            Position(
                position_id=position_id,
                symbol=symbol,
                volume=_number(r["Volume"], f"{where} Volume"),
                open_time=_moment(r["Open Time (UTC)"], f"{where} Open Time"),
                open_price=_number(r["Open Price"], f"{where} Open Price"),
                close_time=_moment(r["Close Time (UTC)"], f"{where} Close Time"),
                close_price=_number(r["Close Price"], f"{where} Close Price"),
                purchase_value=_number(r["Purchase Value"], f"{where} Purchase Value"),
                sale_value=_number(r["Sale Value"], f"{where} Sale Value"),
            )
        )
    if parsed.closed_positions:
        parsed.warnings.append("Closed Positions values use an assumed, unconfirmed format (Q-006)")


# -------------------------------------------------------------------------- file


def parse_file(path: Path) -> ParsedFile:
    prefix, number, start, end = parse_file_name(path.name)
    parsed = ParsedFile(
        path=path,
        prefix=prefix,
        account_number=number,
        currency=ACCOUNT_CURRENCY[prefix],
        tax_wrapper=prefix if prefix in schema.TAX_WRAPPER_PREFIXES else None,
        date_from=start,
        date_to=end,
    )
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        names = [ws.title for ws in workbook.worksheets]
        expected = [layout.name for layout in schema.SHEETS]
        if names != expected:
            raise XtbFormatError(f"sheets {names} do not match the expected {expected}")
        sheets = {ws.title: _sheet_rows(ws) for ws in workbook.worksheets}
    finally:
        workbook.close()

    def is_empty(rows: list[tuple]) -> bool:
        return all(_text(c) is None for row in rows for c in row)

    if all(is_empty(rows) for rows in sheets.values()):
        parsed.empty = True  # an account with no activity in the exported range
        return parsed

    for layout in schema.SHEETS:
        rows = sheets[layout.name]
        if is_empty(rows):
            continue
        if rows[0][0] != schema.ACCOUNT_NUMBER_LABEL:
            raise XtbFormatError(f"sheet {layout.name!r}: no {schema.ACCOUNT_NUMBER_LABEL!r} in A1")
        in_file = _id(rows[0][1]) if len(rows[0]) > 1 else None
        if in_file and in_file != number:
            if parsed.parent_number not in (None, in_file):
                parsed.warnings.append("sheets name different main accounts in B1; the file name is used")
            parsed.parent_number = in_file
    # A sheet can carry only its header block (account number, title, dates) and no table:
    # the account had no operations or positions of that kind in the exported range.
    for layout, parse in (
        (schema.CASH_OPERATIONS, _parse_cash),
        (schema.OPEN_POSITIONS, _parse_open),
        (schema.CLOSED_POSITIONS, _parse_closed),
    ):
        has_table = (
            _open_positions_header_row(sheets[layout.name]) is not None
            if layout is schema.OPEN_POSITIONS
            else _has_table(sheets[layout.name], layout)
        )
        if has_table:
            parse(parsed, sheets[layout.name])

    for op in parsed.cash:
        if op.ledger_type != "BUY":
            continue
        match = OPEN_BUY_RE.match(op.comment or "")
        if not match or match["ticker"] != op.symbol:
            parsed.warnings.append(
                f"purchase {op.operation_id}: comment does not follow 'OPEN BUY <ticker> <volume> @ <price>'"
            )
    return parsed
