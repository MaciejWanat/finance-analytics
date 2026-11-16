"""Treasury bonds entered by hand, and the public parameters of every series (R-008, R-011, D-026).

Three inputs, all files (D-002):
- `resources/bond_series.csv` (shipped, public): one row per series with the first-period rate,
  the margin and the early-redemption fee, from the issue letters;
- `resources/bond_rates.csv` (shipped, public): the official rate of every later interest period
  already published by the Ministry of Finance; `resources/nbp_reference_rate.csv`: NBP history;
- `data/config/bond_series.yaml` (optional, private): the user's additions and corrections,
  merged over the shipped series, e.g. a series newer than this version of the app;
- `data/manual/bonds.csv` (private): the user's purchases, one row per purchase.

Validation problems become messages; nothing here raises on bad user data.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from importlib import resources
from pathlib import Path

import yaml

from finance_analytics.portfolio.bonds import TYPES, maturity, series_maturity_month
from finance_analytics.sources.manual_csv import append_row, dialect
from finance_analytics.sources.manual_csv import delete_row as _delete_row

BONDS_PARSER_VERSION = 1
LOT_COLUMNS = ["account_id", "series", "purchase_date", "quantity", "note"]
SERIES_COLUMNS = ["series", "type", "first_rate", "margin", "early_fee"]
SERIES_RE = re.compile(r"^(OTS|ROR|DOR|TOS|COI|EDO|ROS|ROD)(0[1-9]|1[0-2])(\d{2})$")
RESOURCE_FILES = ("bond_series.csv", "bond_rates.csv", "nbp_reference_rate.csv")

DEFAULT_ACCOUNT_ID = "pko-obligacje"
DEFAULT_ACCOUNT_ALIAS = "Obligacje skarbowe"


def bonds_file(manual_dir: Path) -> Path:
    return manual_dir / "bonds.csv"


def series_overrides_file(config_dir: Path) -> Path:
    return config_dir / "bond_series.yaml"


def resource_bytes(name: str) -> bytes:
    return resources.files("finance_analytics").joinpath("resources", name).read_bytes()


def _read_resource(name: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(resource_bytes(name).decode("utf-8"))))


def _decimal(value) -> Decimal | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {value!r}") from exc


# ------------------------------------------------------------------------------ series


@dataclass
class SeriesTable:
    """Merged series parameters and official period rates, ready for the projection tables."""

    series: dict[str, dict] = field(default_factory=dict)  # code -> {type, first_rate, margin, early_fee, ...}
    rates: dict[tuple[str, int], tuple[Decimal, str]] = field(default_factory=dict)  # (code, period) -> (%, origin)
    reference: list[tuple[str, Decimal]] = field(default_factory=list)  # (date_from ISO, %)
    errors: list[str] = field(default_factory=list)


def load_series(config_dir: Path) -> SeriesTable:
    table = SeriesTable()
    for row in _read_resource("bond_series.csv"):
        table.series[row["series"]] = {
            "type": row["type"], "first_rate": _decimal(row["first_rate"]), "margin": _decimal(row["margin"]),
            "early_fee": _decimal(row["early_fee"]), "maturity_interest": _decimal(row["maturity_interest"]),
            "origin": "shipped",
        }
    for row in _read_resource("bond_rates.csv"):
        table.rates[(row["series"], int(row["period"]))] = (_decimal(row["rate"]), "shipped")
    table.reference = [(row["date_from"], _decimal(row["rate"])) for row in _read_resource("nbp_reference_rate.csv")]
    path = series_overrides_file(config_dir)
    if path.exists():
        _merge_overrides(table, path)
    return table


def _merge_overrides(table: SeriesTable, path: Path) -> None:
    """data/config/bond_series.yaml: `series: {CODE: {type, first_rate, margin, early_fee, rates: {2: 6.1}}}`."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        table.errors.append(f"{path.name}: niepoprawny YAML ({exc}); użyto tylko wbudowanych serii")
        return
    entries = data.get("series") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        table.errors.append(f"{path.name}: brak sekcji `series:`; plik pominięto")
        return
    for code, entry in entries.items():
        code = str(code).strip().upper()
        try:
            _merge_entry(table, code, entry or {})
        except (ValueError, TypeError) as exc:
            table.errors.append(f"{path.name}, {code}: {exc}; wpis pominięto")


def _merge_entry(table: SeriesTable, code: str, entry: dict) -> None:
    match = SERIES_RE.match(code)
    if not match:
        raise ValueError("kod serii ma postać np. EDO0736 (typ, miesiąc i rok wykupu)")
    unknown = set(entry) - {"type", "first_rate", "margin", "early_fee", "maturity_interest", "rates"}
    if unknown:
        raise ValueError(f"nieznane pola {sorted(unknown)}")
    current = dict(table.series.get(code) or {"type": match.group(1), "margin": None, "maturity_interest": None})
    if "type" in entry and entry["type"] != match.group(1):
        raise ValueError(f"typ {entry['type']} nie zgadza się z kodem serii")
    for name in ("first_rate", "margin", "early_fee", "maturity_interest"):
        if name in entry:
            current[name] = _decimal(entry[name])
    if current.get("first_rate") is None or current.get("early_fee") is None:
        raise ValueError("nowa seria wymaga pól first_rate i early_fee")
    if TYPES[current["type"]].index is not None and current.get("margin") is None:
        raise ValueError("seria o zmiennym oprocentowaniu wymaga pola margin")
    current["origin"] = "user"
    rates = entry.get("rates") or {}
    if not isinstance(rates, dict):
        raise ValueError("`rates` to słownik okres: stopa, np. {2: 6.1}")
    parsed = {int(k): _decimal(v) for k, v in rates.items()}
    table.series[code] = current
    for period, rate in parsed.items():
        table.rates[(code, period)] = (rate, "user")


# -------------------------------------------------------------------------------- lots


@dataclass(frozen=True)
class BondLot:
    row: int  # 1-based data row in bonds.csv (header excluded); identifies the row for deletion
    account_id: str
    series: str
    purchase_date: date
    quantity: int
    note: str


@dataclass
class LotsResult:
    lots: list[BondLot] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def parse_date(text: str, what: str = "data") -> date:
    text = text.strip()
    for pattern in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise ValueError(f"{what} {text!r} nie jest w formacie RRRR-MM-DD")


def _parse_date(text: str) -> date:
    return parse_date(text, "data zakupu")


def check_purchase(series: str, purchase: date, known: set[str] | dict, today: date | None = None) -> str | None:
    """Why a purchase is invalid, or None. The series must be known and its code must match the date."""
    match = SERIES_RE.match(series)
    if not match:
        return f"{series!r} nie jest kodem serii (np. EDO0736)"
    if series not in known:
        return f"seria {series} jest nieznana; dodaj ją w data/config/bond_series.yaml"
    if today is not None and purchase > today:
        return f"data zakupu {purchase:%d.%m.%Y} jest w przyszłości"
    end = maturity(match.group(1), purchase)
    year, month = series_maturity_month(series)
    if (end.year, end.month) != (year, month):
        return (f"{series} ma wykup w {month:02d}.{year}, a obligacja kupiona {purchase:%d.%m.%Y} "
                f"miałaby wykup {end:%d.%m.%Y}; sprawdź serię i datę zakupu")
    return None


def read_lots(path: Path, known_series: set[str] | dict, today: date | None = None) -> LotsResult:
    """Parse bonds.csv. Bad rows are reported with their row number and skipped."""
    if not path.exists():
        return LotsResult()
    return parse_lots(path.read_text(encoding="utf-8-sig"), path.name, known_series, today)


def parse_lots(text: str, name: str, known_series: set[str] | dict, today: date | None = None) -> LotsResult:
    """Parse the text of a bonds CSV (the file, or an upload to be previewed)."""
    result = LotsResult()
    reader = csv.DictReader(io.StringIO(text), delimiter=dialect(text))
    missing = [c for c in LOT_COLUMNS[:4] if c not in (reader.fieldnames or [])]
    if missing:
        result.errors.append(f"{name}: brak kolumn {missing}; oczekiwane: {','.join(LOT_COLUMNS)}")
        return result
    for number, raw in enumerate(reader, start=1):
        row = {k: (v or "").strip() for k, v in raw.items() if k}
        if not any(row.values()):
            continue
        where = f"{name}, wiersz {number}"
        try:
            account_id = row["account_id"]
            if not account_id:
                raise ValueError("brak account_id")
            series = row["series"].upper()
            purchase = _parse_date(row["purchase_date"])
            try:
                quantity = int(row["quantity"])
            except ValueError:
                raise ValueError(f"liczba sztuk {row['quantity']!r} nie jest liczbą całkowitą") from None
            if quantity <= 0:
                raise ValueError("liczba sztuk musi być większa od zera")
            problem = check_purchase(series, purchase, known_series, today)
            if problem:
                raise ValueError(problem)
        except ValueError as exc:
            result.errors.append(f"{where}: {exc}. Wiersz pominięto.")
            continue
        result.lots.append(BondLot(number, account_id, series, purchase, quantity, row.get("note", "")))
    return result


def merge_upload(path: Path, text: str, name: str, known_series: set[str] | dict, kinds: dict[str, str],
                 today: date | None = None) -> tuple[LotsResult, list[BondLot]]:
    """Validate an uploaded bonds CSV against the file it would be appended to.

    Returns the parse result and the rows that can be appended. A row identical to one already saved
    is skipped and reported, so uploading a file twice does not double the holdings; a row on an
    account that is not a bonds account is rejected. `kinds` maps account id -> kind; an unknown
    account id is fine (the sync registers it). The existing file is never overwritten.
    """
    result = parse_lots(text, name, known_series, today)
    saved = {(lot.account_id, lot.series, lot.purchase_date, lot.quantity, lot.note)
             for lot in read_lots(path, known_series, None).lots}
    fresh = []
    for lot in result.lots:
        if kinds.get(lot.account_id, "bonds") != "bonds":
            result.errors.append(f"{name}, wiersz {lot.row}: rachunek {lot.account_id} nie jest rachunkiem "
                                 "obligacji (kind: bonds w accounts.yaml). Wiersz pominięto.")
        elif (lot.account_id, lot.series, lot.purchase_date, lot.quantity, lot.note) in saved:
            result.errors.append(f"{name}, wiersz {lot.row}: taki sam zakup {lot.series} z "
                                 f"{lot.purchase_date:%d.%m.%Y} już jest w pliku. Wiersz pominięto.")
        else:
            fresh.append(lot)
    return result, fresh


def append_lot(path: Path, account_id: str, series: str, purchase: date, quantity: int, note: str = "") -> None:
    """Add one purchase at the end of bonds.csv (created with a header when missing)."""
    append_row(path, LOT_COLUMNS, [account_id, series, purchase.isoformat(), quantity, note])


def delete_row(path: Path, row: int) -> bool:
    """Remove data row `row` (as numbered by read_lots) from bonds.csv. Returns whether it existed."""
    return _delete_row(path, row)
