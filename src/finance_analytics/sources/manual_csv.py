"""Small helpers shared by the hand-maintained CSV files in data/manual/ (R-011, D-002, D-026, D-027).

The files are plain CSV that the user may also edit in a spreadsheet: `,` or `;` as the separator,
a UTF-8 BOM tolerated. Rows are numbered from 1 after the header, empty lines skipped, exactly as
`csv.DictReader` yields them, so the number identifies a row for deletion.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from pathlib import Path


def dialect(text: str) -> str:
    """The separator of a CSV text, from its header line."""
    header = text.splitlines()[0] if text else ""
    return ";" if header.count(";") > header.count(",") else ","


def template(columns: Sequence[str]) -> str:
    """An empty file: the header only."""
    return ",".join(columns) + "\n"


def append_row(path: Path, columns: Sequence[str], values: Sequence[object]) -> None:
    """Add one row at the end of the file (created with a header when missing or empty)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or not path.read_text(encoding="utf-8-sig").strip()
    if not new:
        text = path.read_text(encoding="utf-8-sig")
        delimiter = dialect(text)
        prefix = "" if text.endswith("\n") else "\n"
    else:
        delimiter, prefix = ",", ""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\n")
    if new:
        writer.writerow(columns)
    writer.writerow(values)
    with path.open("w" if new else "a", encoding="utf-8", newline="") as handle:
        handle.write(prefix + buffer.getvalue())


def _rows(path: Path) -> tuple[list[list[str]], str, dict[int, int]]:
    """All CSV rows, the separator, and data row number -> index in the rows list."""
    text = path.read_text(encoding="utf-8-sig")
    delimiter = dialect(text)
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    data_index = [i for i, r in enumerate(rows) if i > 0 and r]
    return rows, delimiter, {n: i for n, i in enumerate(data_index, start=1)}


def _write(path: Path, rows: list[list[str]], delimiter: str) -> None:
    buffer = io.StringIO()
    csv.writer(buffer, delimiter=delimiter, lineterminator="\n").writerows(rows)
    path.write_text(buffer.getvalue(), encoding="utf-8")


def replace_row(path: Path, row: int, values: Sequence[object]) -> bool:
    """Overwrite data row `row` in place (same numbering as delete_row). Returns whether it existed.

    Values follow the file's columns; extra columns a user added by hand keep their content.
    """
    if not path.exists():
        return False
    rows, delimiter, numbered = _rows(path)
    if row not in numbered:
        return False
    old = rows[numbered[row]]
    new = [str(v) for v in values]
    rows[numbered[row]] = new + old[len(new):]
    _write(path, rows, delimiter)
    return True


def delete_row(path: Path, row: int) -> bool:
    """Remove data row `row` (numbered as read_* functions do). Returns whether it existed."""
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8-sig")
    delimiter = dialect(text)
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if not rows or row < 1 or row >= len(rows):
        return False
    data_index = [i for i, r in enumerate(rows) if i > 0 and r]
    numbered = {n: i for n, i in enumerate(data_index, start=1)}
    if row not in numbered:
        return False
    del rows[numbered[row]]
    buffer = io.StringIO()
    csv.writer(buffer, delimiter=delimiter, lineterminator="\n").writerows(rows)
    path.write_text(buffer.getvalue(), encoding="utf-8")
    return True
