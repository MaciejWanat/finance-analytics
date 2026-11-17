#!/usr/bin/env python3
"""Describe the structure of an XTB (xStation) export without revealing its data.

Run it locally on the exported folder (one subfolder per XTB account, xlsx files
named PLN..., EUR..., USD..., IKE..., IKZE...) or on a single xlsx file:

    python scripts/inspect_xtb_export.py <export_folder_or_file> --out data/samples/xtb_report.md

The report lists sheets, header rows, columns, value types and enumerations. All
values are masked:
- digits become 9;
- words outside a small financial vocabulary become Xxxx;
- account folders become konto_1, konto_2, ...;
- instrument symbols become AAAA.US (real symbols only with --show-symbols).

Review the report before sharing it. The input files are opened read-only and never
modified. Requires openpyxl.

The report feeds the XTB parser and the synthetic test fixtures (docs/decisions.md, D-006).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

KNOWN_PREFIXES = ("IKZE", "IKE", "PLN", "EUR", "USD")  # IKZE before IKE: longest match first
CURRENCIES = {"PLN", "EUR", "USD", "GBP", "CHF", "CZK", "HUF", "SEK", "NOK", "DKK", "JPY", "CAD", "AUD"}

# Words that may stay readable in masked text: generic financial/report terms in
# English and Polish. Anything else (names, addresses, company names) is masked.
VOCAB = {
    # english
    "account", "accounts", "acc", "adjustment", "amount", "and", "at", "balance", "blik", "buy",
    "by", "card", "cash", "category", "class", "client", "close", "closed", "closing", "comment",
    "commission", "conversion", "correction", "cost", "credit", "currency", "date", "debit",
    "deposit", "description", "dist", "divident", "dividend", "dividends", "equity", "etf", "fee",
    "fees", "for", "free", "from", "funds", "gross", "history", "id", "in", "interest", "margin",
    "market", "name", "net", "nominal", "number", "of", "on", "open", "opening", "operation",
    "operations", "order", "orders", "out", "pending", "period", "pln", "position", "positions",
    "price", "profit", "loss", "purchase", "rate", "report", "rollover", "sale", "sell", "share",
    "shares", "shr", "stock", "stocks", "sub", "subaccount", "summary", "surname", "swap", "symbol",
    "tax", "taxes", "time", "to", "total", "trade", "transaction", "transfer", "type", "ucits",
    "unit", "units", "value", "volume", "wht", "withdrawal", "withholding", "with", "frac", "fractional",
    "ike", "ikze", "inc", "corp", "plc", "sa", "ag", "nv", "se", "ltd", "spa", "asa", "oyj",
    "gain", "result", "sl", "tp", "pip", "pips", "lots", "lot", "instrument", "ticker", "isin",
    # polish
    "rachunek", "rachunku", "konto", "konta", "waluta", "saldo", "kapitał", "depozyt", "wolne",
    "środki", "zysk", "strata", "data", "od", "do", "okres", "klient", "typ", "numer", "imię",
    "nazwisko", "wpłata", "wypłata", "dywidenda", "podatek", "odsetki", "prowizja", "opłata",
    "zakup", "kupno", "sprzedaż", "akcji", "akcje", "pozycja", "pozycje", "otwarcie", "zamknięcie",
    "otwarte", "zamknięte", "cena", "wartość", "wolumen", "komentarz", "opis", "kwota", "suma",
    "przelew", "korekta", "zlecenie", "zlecenia", "historia", "operacje", "operacja", "gotówkowe",
    "gotówka", "kurs", "brutto", "netto", "razem", "w", "z", "na", "i",
}

SYMBOL_HEADER_RE = re.compile(r"symbol|ticker|instrument|isin", re.IGNORECASE)
FREE_TEXT_HEADER_RE = re.compile(r"comment|komentarz|description|opis|name|nazw|title|tytu", re.IGNORECASE)
TOKEN_RE = re.compile(r"[^\W\d_]+|\d+|\s+|.", re.UNICODE)
NUMBER_TEXT_RE = re.compile(r"^[+\-−]?\d{1,3}([  .,]?\d{3})*([.,]\d+)?$|^[+\-−]?\d+([.,]\d+)?$")
MAX_ENUM_VALUES = 30
HEADER_SCAN_ROWS = 40


# ----------------------------------------------------------------------- masking


def _shape(word: str) -> str:
    return "".join("X" if ch.isupper() else "x" for ch in word)


def mask_text(text: str) -> str:
    """Keep structure and vocabulary words; digits -> 9, other words -> Xxxx."""
    out = []
    for token in TOKEN_RE.findall(text):
        if token[0].isdigit():
            out.append("9" * len(token))
        elif token[0].isalpha():
            keep = token.lower() in VOCAB or token.upper() in CURRENCIES
            out.append(token if keep else _shape(token))
        else:
            out.append(token)
    return "".join(out)


def mask_symbol(text: str) -> str:
    """'AAPL.US' -> 'AAAA.US': the exchange suffix stays, the ticker does not."""
    base, dot, suffix = text.rpartition(".")
    if not dot or not re.fullmatch(r"[A-Z]{1,4}", suffix):
        base, dot, suffix = text, "", ""
    masked = "".join("9" if ch.isdigit() else "A" if ch.isalpha() else ch for ch in base)
    return masked + dot + suffix


def mask_filename(name: str) -> str:
    return re.sub(r"\d", "9", name)


def split_prefix(filename: str) -> str | None:
    upper = filename.upper()
    for prefix in KNOWN_PREFIXES:
        if upper.startswith(prefix):
            return prefix
    return None


# ------------------------------------------------------------------- cell typing


def cell_kind(value: object) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return "empty"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "int" if value.is_integer() else "float"
    if isinstance(value, datetime):
        return "datetime" if value.time() != time(0, 0) else "date"
    if isinstance(value, date):
        return "date"
    if isinstance(value, time):
        return "time"
    if isinstance(value, str):
        stripped = value.strip()
        if NUMBER_TEXT_RE.match(stripped):
            return "text-number"
        if re.fullmatch(r"[\d.\-/: T]+", stripped) and sum(ch.isdigit() for ch in stripped) >= 6:
            return "text-date"
        return "text"
    return type(value).__name__


def decimals_of(value: float) -> int:
    text = f"{value:.10f}".rstrip("0")
    return len(text.split(".")[1]) if "." in text else 0


def describe_cell(value: object, symbol_like: bool, show_symbols: bool) -> str:
    """Masked one-cell description for metadata and tail rows."""
    kind = cell_kind(value)
    if kind == "empty":
        return ""
    if kind == "text":
        text = str(value).strip()
        if symbol_like and not show_symbols:
            return f"`{mask_symbol(text)}`"
        return f"`{mask_text(text)}`"
    if kind in ("text-number", "text-date"):
        return f"`{mask_text(str(value).strip())}` ({kind})"
    return f"<{kind}>"


# --------------------------------------------------------------- data structures


@dataclass
class Sheet:
    name: str
    rows: list[tuple]
    header_index: int | None = None  # 0-based
    headers: list[str] = field(default_factory=list)

    @property
    def data_rows(self) -> list[tuple]:
        if self.header_index is None:
            return []
        return [r for r in self.rows[self.header_index + 1 :] if any(cell_kind(c) != "empty" for c in r)]


@dataclass
class ExportFile:
    account: str  # masked, e.g. konto_1
    masked_name: str
    prefix: str | None
    sheets: list[Sheet]

    @property
    def label(self) -> str:
        return f"{self.account}/{self.masked_name}"

    def signature(self) -> tuple:
        return tuple((s.name, tuple(s.headers)) for s in self.sheets)


def detect_header(rows: Sequence[tuple]) -> int | None:
    """The header is the row (within the first rows) with the most text cells."""
    best_index, best_count = None, 1
    for index, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        count = sum(1 for c in row if cell_kind(c) == "text")
        if count > best_count:
            best_index, best_count = index, count
    return best_index


def load_sheet(ws) -> Sheet:
    # xStation exports can declare a stale used range (e.g. A1) although the
    # worksheet contains data. In read-only mode OpenPyXL otherwise trusts it.
    ws.reset_dimensions()
    rows = [tuple(row) for row in ws.iter_rows(values_only=True)]
    width = max((max((i + 1 for i, c in enumerate(r) if cell_kind(c) != "empty"), default=0) for r in rows), default=0)
    rows = [tuple(r[:width]) + (None,) * (width - len(r[:width])) for r in rows]
    while rows and all(cell_kind(c) == "empty" for c in rows[-1]):
        rows.pop()
    sheet = Sheet(name=ws.title, rows=rows)
    sheet.header_index = detect_header(rows)
    if sheet.header_index is not None:
        sheet.headers = [
            re.sub(r"\d", "9", str(c).strip()) if cell_kind(c) != "empty" else "" for c in rows[sheet.header_index]
        ]
    return sheet


def load_file(path: Path, account: str) -> ExportFile:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheets = [load_sheet(ws) for ws in workbook.worksheets]
    finally:
        workbook.close()
    return ExportFile(
        account=account, masked_name=mask_filename(path.name), prefix=split_prefix(path.name), sheets=sheets
    )


def discover(input_path: Path) -> list[tuple[str, Path]]:
    """(masked account label, file) pairs. Account = the file's parent folder."""
    if input_path.is_file():
        return [("konto_1", input_path)]
    files = sorted(p for p in input_path.rglob("*.xlsx") if not p.name.startswith("~$"))
    labels: dict[Path, str] = {}
    for f in files:
        labels.setdefault(f.parent, f"konto_{len(labels) + 1}")
    return [(labels[f.parent], f) for f in files]


# ----------------------------------------------------------------------- profile


def profile_column(header: str, values: list[object], show_symbols: bool) -> tuple[str, str, str]:
    """Returns (types, empty count, details) for one column across all data rows."""
    kinds = Counter(cell_kind(v) for v in values)
    empty = kinds.pop("empty", 0)
    types = ", ".join(f"{k} ({n})" for k, n in kinds.most_common()) or "empty"
    present = [v for v in values if cell_kind(v) != "empty"]
    details: list[str] = []

    numbers = [float(v) for v in present if cell_kind(v) in ("int", "float")]
    if numbers:
        signs = []
        if any(n < 0 for n in numbers):
            signs.append("negative")
        if any(n > 0 for n in numbers):
            signs.append("positive")
        if any(n == 0 for n in numbers):
            signs.append("zero")
        details.append("signs: " + "/".join(signs))
        details.append(f"decimals: {min(map(decimals_of, numbers))}–{max(map(decimals_of, numbers))}")
        if all(n.is_integer() for n in numbers):
            lengths = [len(str(abs(int(n)))) for n in numbers]
            unique = "unique" if len(set(numbers)) == len(numbers) else "repeats"
            details.append(f"{unique}, {min(lengths)}–{max(lengths)} digits")

    moments = [v for v in present if isinstance(v, (datetime, date))]
    if moments:
        has_seconds = any(isinstance(v, datetime) and v.second for v in moments)
        details.append("Excel dates" + (" with seconds" if has_seconds else ""))

    texts = [str(v).strip() for v in present if isinstance(v, str)]
    if texts:
        symbol_like = bool(SYMBOL_HEADER_RE.search(header))
        free_text = bool(FREE_TEXT_HEADER_RE.search(header))
        distinct = Counter(texts)
        if symbol_like:
            if show_symbols:
                details.append("symbols: " + ", ".join(f"`{s}`" for s in sorted(distinct)))
            else:
                suffixes = Counter(mask_symbol(t) for t in texts)
                details.append("symbol patterns: " + ", ".join(f"`{p}` ({n})" for p, n in suffixes.most_common(12)))
        elif (
            not free_text
            and len(distinct) <= MAX_ENUM_VALUES
            and len(distinct) <= max(3, len(texts) // 2)
        ):
            shown = [
                (value if not any(ch.isdigit() for ch in value) else mask_text(value), n)
                for value, n in distinct.most_common()
            ]
            details.append("values: " + ", ".join(f"`{v}` ({n})" for v, n in shown))
        else:
            patterns = Counter(mask_text(t) for t in texts)
            top = ", ".join(f"`{p}` ({n})" for p, n in patterns.most_common(8))
            more = f" … +{len(patterns) - 8} more patterns" if len(patterns) > 8 else ""
            details.append(f"{len(distinct)} distinct; patterns: {top}{more}")
    return types, str(empty), "; ".join(details)


# ------------------------------------------------------------------------ report


def _row_cells(row: Iterable[object], headers: Sequence[str], show_symbols: bool) -> str:
    cells = []
    for i, value in enumerate(row):
        header = headers[i] if i < len(headers) else ""
        described = describe_cell(value, bool(SYMBOL_HEADER_RE.search(header)), show_symbols)
        if described:
            cells.append(f"{get_column_letter(i + 1)}: {described}")
    return " · ".join(cells) if cells else "(empty)"


def build_report(files: list[ExportFile], show_symbols: bool) -> str:
    lines = [
        "# XTB export structure report",
        "",
        "Generated by `scripts/inspect_xtb_export.py`. Values are masked: digits → 9,",
        "words outside a financial vocabulary → Xxxx, account folders → konto_N,",
        "symbols → AAAA.SUFFIX" + (" (**real symbols shown: --show-symbols**)" if show_symbols else "") + ".",
        "**Review this report before sharing it.**",
        "",
        "## Folder layout",
        "",
        "| Account | File (masked) | Prefix | Sheets (data rows) |",
        "|---|---|---|---|",
    ]
    for f in files:
        sheets = ", ".join(f"{s.name} ({len(s.data_rows)})" for s in f.sheets)
        lines.append(f"| {f.account} | `{f.masked_name}` | {f.prefix or '**unknown**'} | {sheets} |")

    groups: dict[tuple, list[ExportFile]] = defaultdict(list)
    for f in files:
        groups[f.signature()].append(f)

    lines += ["", "## Structure groups", ""]
    if len(groups) == 1:
        lines.append(f"All {len(files)} file(s) share identical sheets and column headers.")
    else:
        lines.append(f"{len(groups)} different structures:")
        for n, members in enumerate(groups.values(), start=1):
            lines.append(f"- Group {n}: " + ", ".join(m.label for m in members))

    for n, (_, members) in enumerate(groups.items(), start=1):
        lines += ["", f"## Group {n}: " + ", ".join(m.label for m in members), ""]
        first = members[0]
        for s_index, sheet in enumerate(first.sheets):
            all_rows = [row for m in members for row in m.sheets[s_index].data_rows]
            header_rows = sorted({m.sheets[s_index].header_index for m in members}, key=lambda x: (x is None, x))
            header_at = ", ".join("none" if h is None else str(h + 1) for h in header_rows)
            lines += [
                f"### Sheet `{sheet.name}`",
                "",
                f"- header row (1-based): {header_at}; data rows (all files in group): {len(all_rows)}; "
                f"columns: {len(sheet.headers)}",
            ]
            if sheet.header_index:
                lines += ["- rows above the header (first file, masked):"]
                for r_index, row in enumerate(sheet.rows[: sheet.header_index], start=1):
                    if any(cell_kind(c) != "empty" for c in row):
                        lines.append(f"  - row {r_index}: {_row_cells(row, [], show_symbols)}")
            if not sheet.headers:
                lines.append("- no header detected")
                continue
            lines += ["", "| Col | Header | Types | Empty | Details |", "|---|---|---|---|---|"]
            for c_index, header in enumerate(sheet.headers):
                values = [row[c_index] if c_index < len(row) else None for row in all_rows]
                types, empty, details = profile_column(header, values, show_symbols)
                cell = header.replace("|", "\\|") if header else "*(blank)*"
                lines.append(f"| {get_column_letter(c_index + 1)} | {cell} | {types} | {empty} | {details} |")
            tail = sheet.data_rows[-3:]
            if tail:
                lines += ["", "Last rows (first file, masked), to spot summary/total rows:"]
                for row in tail:
                    lines.append(f"- {_row_cells(row, sheet.headers, show_symbols)}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="export folder (or a single .xlsx file)")
    parser.add_argument("--out", type=Path, help="write the Markdown report here (default: stdout)")
    parser.add_argument("--show-symbols", action="store_true", help="show real instrument symbols")
    args = parser.parse_args(argv)

    if not args.input.exists():
        parser.error(f"not found: {args.input}")
    source_root = args.input if args.input.is_dir() else args.input.parent
    if args.out and args.out.resolve().is_relative_to(source_root.resolve()):
        parser.error("--out must not point inside the export folder (the input stays untouched)")

    found = discover(args.input)
    if not found:
        parser.error("no .xlsx files found")
    files = [load_file(path, account) for account, path in found]
    report = build_report(files, args.show_symbols)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        print(f"Report written: {args.out} ({len(files)} file(s)). Review it before sharing.")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
