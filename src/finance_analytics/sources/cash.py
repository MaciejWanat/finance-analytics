"""Cash at banks, entered by hand as balances on dates (R-007, R-011, D-027).

`data/manual/cash_balances.csv` (private, the source of truth, D-002): one row per balance snapshot,
`account_id,date,balance,note`. The balance is in the account's currency. The accounts themselves live
in `data/config/accounts.yaml` with `kind: bank`.

Validation problems become messages; nothing here raises on bad user data.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from finance_analytics.sources.bonds import parse_date
from finance_analytics.sources.manual_csv import append_row, dialect
from finance_analytics.sources.manual_csv import delete_row as _delete_row
from finance_analytics.sources.manual_csv import replace_row as _replace_row

CASH_PARSER_VERSION = 1
SNAPSHOT_COLUMNS = ["account_id", "date", "balance", "note"]
CURRENCIES = ["PLN", "EUR", "USD", "GBP", "CHF"]


def cash_file(manual_dir: Path) -> Path:
    return manual_dir / "cash_balances.csv"


@dataclass(frozen=True)
class Snapshot:
    row: int  # 1-based data row in cash_balances.csv (header excluded); identifies the row for deletion
    account_id: str
    day: date
    balance: Decimal
    note: str


@dataclass
class SnapshotsResult:
    snapshots: list[Snapshot] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def parse_balance(text: str) -> Decimal:
    """'12 345,67' / '12345.67' / '-80' -> Decimal; anything else is a ValueError."""
    cleaned = text.strip().replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"saldo {text!r} nie jest liczbą") from None
    if not value.is_finite() or not math.isfinite(float(value)):
        raise ValueError(f"saldo {text!r} nie jest liczbą")
    return value


def check_snapshot(account_id: str, day: date, kinds: dict[str, str], today: date | None = None) -> str | None:
    """Why a snapshot is invalid, or None: the account must be a known bank account, the date not in the future."""
    if account_id not in kinds:
        return f"konto {account_id} jest nieznane; dodaj je w aplikacji albo w data/config/accounts.yaml"
    if kinds[account_id] != "bank":
        return f"rachunek {account_id} nie jest kontem bankowym (kind: bank w accounts.yaml)"
    if today is not None and day > today:
        return f"data salda {day:%d.%m.%Y} jest w przyszłości"
    return None


def read_snapshots(path: Path, kinds: dict[str, str], today: date | None = None) -> SnapshotsResult:
    """Parse cash_balances.csv. Bad rows are reported with their row number and skipped."""
    if not path.exists():
        return SnapshotsResult()
    return parse_snapshots(path.read_text(encoding="utf-8-sig"), path.name, kinds, today)


def parse_snapshots(text: str, name: str, kinds: dict[str, str], today: date | None = None) -> SnapshotsResult:
    """Parse the text of a balances CSV (the file, or an upload to be previewed).

    `kinds` maps account id -> kind for every known account. A second row for the same account and
    date is an error (the later row is skipped): a day has one balance.
    """
    result = SnapshotsResult()
    reader = csv.DictReader(io.StringIO(text), delimiter=dialect(text))
    missing = [c for c in SNAPSHOT_COLUMNS[:3] if c not in (reader.fieldnames or [])]
    if missing:
        result.errors.append(f"{name}: brak kolumn {missing}; oczekiwane: {','.join(SNAPSHOT_COLUMNS)}")
        return result
    seen: dict[tuple[str, date], int] = {}
    for number, raw in enumerate(reader, start=1):
        row = {k: (v or "").strip() for k, v in raw.items() if k}
        if not any(row.values()):
            continue
        where = f"{name}, wiersz {number}"
        try:
            account_id = row["account_id"]
            if not account_id:
                raise ValueError("brak account_id")
            day = parse_date(row["date"], "data salda")
            balance = parse_balance(row["balance"])
            problem = check_snapshot(account_id, day, kinds, today)
            if problem:
                raise ValueError(problem)
            if (account_id, day) in seen:
                raise ValueError(f"saldo konta {account_id} na dzień {day:%d.%m.%Y} jest już w wierszu "
                                 f"{seen[(account_id, day)]}")
        except ValueError as exc:
            result.errors.append(f"{where}: {exc}. Wiersz pominięto.")
            continue
        seen[(account_id, day)] = number
        result.snapshots.append(Snapshot(number, account_id, day, balance, row.get("note", "")))
    return result


def append_snapshot(path: Path, account_id: str, day: date, balance: Decimal, note: str = "") -> None:
    """Add one balance at the end of cash_balances.csv (created with a header when missing)."""
    append_row(path, SNAPSHOT_COLUMNS, [account_id, day.isoformat(), f"{balance:f}", note])


def check_table(rows: list[tuple[str | None, date | None, object, str]], kinds: dict[str, str],
                today: date | None = None) -> tuple[list[tuple[str, date, Decimal, str]], list[str]]:
    """Validate a whole edited table of balances (account, day, balance, note), as on "Gotówka" (D-053).

    Returns the clean rows and a Polish error per bad row (1-based as shown). Nothing is written.
    """
    clean, errors, seen = [], [], {}
    for number, (account_id, day, balance, note) in enumerate(rows, start=1):
        try:
            if not account_id:
                raise ValueError("wybierz konto")
            if day is None:
                raise ValueError("wpisz datę salda")
            if balance is None or (isinstance(balance, float) and math.isnan(balance)):
                raise ValueError("wpisz saldo")
            amount = parse_balance(str(balance))
            problem = check_snapshot(account_id, day, kinds, today)
            if problem:
                raise ValueError(problem)
            if (account_id, day) in seen:
                raise ValueError(f"to samo konto i dzień co w wierszu {seen[(account_id, day)]}")
        except ValueError as exc:
            errors.append(f"Wiersz {number}: {exc}.")
            continue
        seen[(account_id, day)] = number
        clean.append((account_id, day, amount, (note or "").strip()))
    return clean, errors


def write_snapshots(path: Path, rows: list[tuple[str, date, Decimal, str]]) -> None:
    """Replace cash_balances.csv with these rows, oldest first, keeping the file's separator."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=dialect(text) if text.strip() else ",", lineterminator="\n")
    writer.writerow(SNAPSHOT_COLUMNS)
    for account_id, day, balance, note in sorted(rows, key=lambda r: (r[1], r[0])):
        writer.writerow([account_id, day.isoformat(), f"{balance:f}", note])
    path.write_text(buffer.getvalue(), encoding="utf-8")


def update_snapshot(path: Path, row: int, account_id: str, day: date, balance: Decimal, note: str = "") -> bool:
    """Overwrite one balance in cash_balances.csv (row as numbered by read_snapshots)."""
    return _replace_row(path, row, [account_id, day.isoformat(), f"{balance:f}", note])


def delete_row(path: Path, row: int) -> bool:
    """Remove data row `row` (as numbered by read_snapshots). Returns whether it existed."""
    return _delete_row(path, row)


def merge_upload(path: Path, text: str, name: str, kinds: dict[str, str], today: date | None = None
                 ) -> tuple[SnapshotsResult, list[Snapshot]]:
    """Validate an uploaded balances CSV against the file it would be appended to.

    Returns the parse result and the rows that can be appended: valid and not clashing with a
    balance already saved for the same account and date. Clashes are added to `errors`; the
    existing file is never changed here and never overwritten.
    """
    result = parse_snapshots(text, name, kinds, today)
    existing = {(s.account_id, s.day) for s in read_snapshots(path, kinds, None).snapshots}
    fresh = []
    for snapshot in result.snapshots:
        if (snapshot.account_id, snapshot.day) in existing:
            result.errors.append(f"{name}, wiersz {snapshot.row}: saldo konta {snapshot.account_id} na dzień "
                                 f"{snapshot.day:%d.%m.%Y} już jest w pliku. Wiersz pominięto.")
        else:
            fresh.append(snapshot)
    return result, fresh
