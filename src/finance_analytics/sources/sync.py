"""Files in data/ -> projection tables in SQLite (D-002, D-015, D-016).

`import_xtb` archives export files under data/raw/xtb/<account number>/.
`sync` rebuilds every projection table when any source file, the accounts file or
the parser version changed since the last sync; otherwise it does nothing. The market
cache (later migrations) is never touched here.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath

import yaml

from finance_analytics.config import Settings
from finance_analytics.db import connect, migrate
from finance_analytics.sources import bonds as bond_files
from finance_analytics.sources import cash as cash_files
from finance_analytics.sources import instruments as instrument_files
from finance_analytics.sources.accounts import (
    load_accounts,
    register_bond_accounts,
    register_xtb_accounts,
    xtb_account_id,
)
from finance_analytics.sources.xtb.parser import (
    OPEN_BUY_RE,
    PARSER_VERSION,
    ParsedFile,
    Position,
    XtbFormatError,
    parse_file,
    parse_file_name,
)

PROJECTION_TABLES = (
    "cash_snapshots", "bond_lots", "bond_rates", "bond_series", "bond_reference_rate",
    "import_issues", "cash_ledger", "positions", "instruments", "accounts", "source_files",
)
YAHOO_SUFFIX = {".US": "", ".UK": ".L", ".DE": ".DE", ".PL": ".WA"}  # XTB suffix -> Yahoo suffix
# A symbol whose Yahoo ticker is not the suffix rule's result is mapped by the user in config/yahoo_tickers.yaml
# (`XTB_SYMBOL: YAHOO_TICKER`, D-039). No built-in list: it would reveal which instruments the author holds.


def yahoo_tickers_file(config_dir: Path) -> Path:
    return config_dir / "yahoo_tickers.yaml"


def load_yahoo_overrides(config_dir: Path) -> dict[str, str]:
    """User overrides from config/yahoo_tickers.yaml; a broken file is ignored (the built-in rules still apply)."""
    path = yahoo_tickers_file(config_dir)
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k).strip(): str(v).strip() for k, v in data.items() if k and v}


def yahoo_ticker(xtb_symbol: str, overrides: dict[str, str] | None = None) -> str | None:
    if overrides and xtb_symbol in overrides:
        return overrides[xtb_symbol]
    base, dot, suffix = xtb_symbol.rpartition(".")
    if not dot or f".{suffix}" not in YAHOO_SUFFIX:
        return None
    return base + YAHOO_SUFFIX[f".{suffix}"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _iso(moment: datetime | None) -> str | None:
    """One fixed text format for every timestamp; exports can carry milliseconds, which are dropped."""
    return moment.replace(microsecond=0).isoformat(sep=" ") if moment else None


MATCH_WINDOW_SECONDS = 600  # a cash operation and its position may be stamped a few minutes apart


def _fill(op) -> tuple[float | None, float | None]:
    """(volume of this fill, volume of the whole order) from an "OPEN BUY" comment, when present."""
    found = OPEN_BUY_RE.match(op.comment or "")
    if not found:
        return None, None
    volume = float(found["volume"])
    return volume, float(found["order"]) if found["order"] else volume


def _match(positions: dict, ops: dict[tuple, list], when) -> dict[tuple, list]:
    """Pair cash operations (buys or sells) with positions: position key -> its operations.

    One position can have several operations: an order for fractional shares is filled in
    parts (D-048), and the parts may carry different IDs. First by position ID; the rest is
    paired by account, ticker, order volume (from the "OPEN BUY" comment when present) and
    the nearest time within MATCH_WINDOW_SECONDS. A position takes parts until their volumes
    add up to its own. `when(position)` gives the position's time to compare with.
    """
    matched = {key: list(ops[key]) for key in positions if key in ops}
    used = {id(op) for group in matched.values() for op in group}

    def room(key) -> float:
        p = positions[key][0]
        taken = 0.0
        for op in matched.get(key, []):
            volume, _ = _fill(op)
            taken += p.volume if volume is None else volume
        return p.volume - taken

    pending = sorted(((key, op) for key, group in ops.items() for op in group), key=lambda kv: kv[1].ts)
    for (account_id, _), op in pending:
        if id(op) in used:
            continue
        volume, order = _fill(op)
        candidates = [
            (abs((when(p) - op.ts).total_seconds()), key)
            for key, (p, _) in positions.items()
            if key[0] == account_id and p.symbol == op.symbol and when(p) is not None
            and abs((when(p) - op.ts).total_seconds()) <= MATCH_WINDOW_SECONDS
            and (order is None or abs(p.volume - order) < 1e-6)
            and room(key) >= (volume if volume is not None else p.volume) - 1e-6
        ]
        if candidates:
            key = min(candidates)[1]
            matched.setdefault(key, []).append(op)
            used.add(id(op))
    return matched


# ------------------------------------------------------------------------ import


@dataclass
class ImportResult:
    copied: list[Path] = field(default_factory=list)
    unchanged: list[Path] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)


def store_xtb_file(name: str, data: bytes, settings: Settings) -> tuple[Path, bool]:
    """Archive one export file. Returns (path in data/raw, whether anything was written)."""
    _, number, _, _ = parse_file_name(name)
    target_dir = settings.raw_dir / "xtb" / number
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / name
    digest = hashlib.sha256(data).hexdigest()
    if target.exists():
        if _sha256(target) == digest:
            return target, False
        # Same name, different content (e.g. exported again the same day): keep both.
        target = target_dir / f"{target.stem}__{digest[:8]}.xlsx"
        if target.exists():
            return target, False
    target.write_bytes(data)
    return target, True


MAX_ZIP_ENTRY_BYTES = 100 * 1024 * 1024  # an export file is a few hundred kB; guards against zip bombs


def is_export_name(name: str) -> bool:
    base = PurePosixPath(name).name
    return (base.lower().endswith(".xlsx") and not base.startswith(("~$", "._"))
            and "__MACOSX" not in PurePosixPath(name).parts)


def zip_export_files(data: bytes, label: str) -> Iterator[tuple[str, str, bytes]]:
    """The .xlsx files inside an export zip (as xStation saves it): (display name, file name, content)."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for entry in archive.infolist():
            if entry.is_dir() or not is_export_name(entry.filename):
                continue
            if entry.file_size > MAX_ZIP_ENTRY_BYTES:
                raise XtbFormatError(f"{entry.filename}: too large for an export file")
            yield f"{label}/{entry.filename}", PurePosixPath(entry.filename).name, archive.read(entry)


def _export_paths(source: Path) -> list[Path]:
    if source.is_file():
        return [source]
    return sorted(p for p in source.rglob("*") if p.is_file() and p.suffix.lower() in (".xlsx", ".zip"))


def import_xtb(source: Path, settings: Settings) -> ImportResult:
    """Copy an export folder, an export zip or a single file into data/raw/xtb (D-044).

    A folder may hold .xlsx files and zips. Zips are read in memory, never extracted to
    disk, and the source is never modified.
    """
    result = ImportResult()
    for path in _export_paths(source):
        if path.suffix.lower() == ".zip":
            try:
                files = list(zip_export_files(path.read_bytes(), str(path)))
            except (zipfile.BadZipFile, XtbFormatError) as exc:
                result.skipped.append((path, f"not a readable export zip: {exc}"))
                continue
        elif is_export_name(path.name):
            files = [(str(path), path.name, path.read_bytes())]
        else:
            continue
        for shown, name, data in files:
            try:
                stored, written = store_xtb_file(name, data, settings)
            except XtbFormatError as exc:
                result.skipped.append((Path(shown), str(exc)))
                continue
            (result.copied if written else result.unchanged).append(stored)
    return result


# -------------------------------------------------------------------------- sync


@dataclass
class SyncResult:
    rebuilt: bool
    files: int = 0
    accounts_added: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _source_state(settings: Settings) -> dict[str, tuple[str, int]]:
    state = {}
    for path in sorted((settings.raw_dir / "xtb").glob("*/*.xlsx")):
        state[path.relative_to(settings.data_dir).as_posix()] = (_sha256(path), PARSER_VERSION)
    if settings.accounts_file.exists():
        state[settings.accounts_file.relative_to(settings.data_dir).as_posix()] = (
            _sha256(settings.accounts_file), 1,
        )
    overrides_path = yahoo_tickers_file(settings.config_dir)
    if overrides_path.exists():
        state[overrides_path.relative_to(settings.data_dir).as_posix()] = (_sha256(overrides_path), 1)
    for path in _bond_sources(settings):
        state[path.relative_to(settings.data_dir).as_posix()] = (_sha256(path), bond_files.BONDS_PARSER_VERSION)
    overrides_path = instrument_files.instruments_file(settings.config_dir)
    if overrides_path.exists():
        state[overrides_path.relative_to(settings.data_dir).as_posix()] = (_sha256(overrides_path), 1)
    cash_path = cash_files.cash_file(settings.manual_dir)
    if cash_path.exists():
        state[cash_path.relative_to(settings.data_dir).as_posix()] = (_sha256(cash_path),
                                                                      cash_files.CASH_PARSER_VERSION)
    for name in bond_files.RESOURCE_FILES:  # shipped with the app: a new version re-syncs
        state[f"{RESOURCE_PREFIX}{name}"] = (hashlib.sha256(bond_files.resource_bytes(name)).hexdigest(),
                                             bond_files.BONDS_PARSER_VERSION)
    return state


RESOURCE_PREFIX = "resources/"


def _bond_sources(settings: Settings) -> list[Path]:
    """The user's bond files that exist: purchases and series overrides."""
    candidates = [bond_files.bonds_file(settings.manual_dir), bond_files.series_overrides_file(settings.config_dir)]
    return [path for path in candidates if path.exists()]


def sync(settings: Settings, *, force: bool = False) -> SyncResult:
    with closing(connect(settings.db_path)) as conn:
        migrate(conn)
        recorded = {
            row["path"]: (row["sha256"], row["parser_version"])
            for row in conn.execute("SELECT path, sha256, parser_version FROM source_files")
        }
        if not force and recorded == _source_state(settings):
            return SyncResult(rebuilt=False, files=sum(1 for p in recorded if p.startswith("raw/")))

        # Parse outside the transaction; a broken file becomes an error, not a crash.
        parsed: list[tuple[Path, ParsedFile | None, str | None]] = []
        for path in sorted((settings.raw_dir / "xtb").glob("*/*.xlsx")):
            try:
                parsed.append((path, parse_file(path), None))
            except XtbFormatError as exc:
                parsed.append((path, None, str(exc)))
            except Exception as exc:  # unreadable workbook etc.
                parsed.append((path, None, f"cannot read the file: {exc}"))

        found = sorted(
            {(p.account_number, p.prefix, p.currency, p.tax_wrapper, p.parent_number) for _, p, _ in parsed if p},
            key=lambda item: tuple(value or "" for value in item),
        )
        added = register_xtb_accounts(settings.accounts_file, found)
        series = bond_files.load_series(settings.config_dir)
        lots = bond_files.read_lots(bond_files.bonds_file(settings.manual_dir), series.series, date.today())
        added += register_bond_accounts(settings.accounts_file, sorted({lot.account_id for lot in lots.lots}))
        accounts = load_accounts(settings.accounts_file)
        result = SyncResult(rebuilt=True, files=len(parsed), accounts_added=[a.alias for a in added])

        with conn:  # one transaction: readers never see a half-built projection
            for table in PROJECTION_TABLES:
                conn.execute(f"DELETE FROM {table}")
            _write(conn, settings, accounts, parsed, result)
            _write_bonds(conn, settings, accounts, series, lots, result)
            _write_cash(conn, settings, accounts, result)
    return result


def _float(value) -> float | None:
    return None if value is None else float(value)


def _write_bonds(conn, settings: Settings, accounts, series: bond_files.SeriesTable, lots: bond_files.LotsResult,
                 result: SyncResult) -> None:
    """Series parameters, official rates, the NBP reference rate and the user's purchases (D-026)."""
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    for name in bond_files.RESOURCE_FILES:
        conn.execute(
            "INSERT INTO source_files (kind, path, sha256, parser_version, imported_at) "
            "VALUES ('resource', ?, ?, ?, ?)",
            (f"{RESOURCE_PREFIX}{name}", hashlib.sha256(bond_files.resource_bytes(name)).hexdigest(),
             bond_files.BONDS_PARSER_VERSION, now),
        )
    file_ids = {}
    for path in _bond_sources(settings):
        kind = "manual_bonds" if path.suffix == ".csv" else "config"
        file_ids[path] = conn.execute(
            "INSERT INTO source_files (kind, path, sha256, parser_version, imported_at, rows_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (kind, path.relative_to(settings.data_dir).as_posix(), _sha256(path), bond_files.BONDS_PARSER_VERSION,
             now, json.dumps({"bond_lots": len(lots.lots)}) if kind == "manual_bonds" else None),
        ).lastrowid

    def issue(file_id, account_id, message):
        conn.execute(
            "INSERT INTO import_issues (source_file_id, account_id, severity, message) VALUES (?, ?, 'error', ?)",
            (file_id, account_id, message),
        )
        result.errors.append(message)

    overrides = bond_files.series_overrides_file(settings.config_dir)
    for message in series.errors:
        issue(file_ids.get(overrides), None, message)
    for code, entry in sorted(series.series.items()):
        conn.execute(
            "INSERT INTO bond_series (series, type, first_rate, margin, early_fee, maturity_interest, origin) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (code, entry["type"], float(entry["first_rate"]), _float(entry["margin"]), float(entry["early_fee"]),
             _float(entry.get("maturity_interest")), entry["origin"]),
        )
    conn.executemany(
        "INSERT INTO bond_rates (series, period, rate, origin) VALUES (?, ?, ?, ?)",
        [(code, period, float(rate), origin) for (code, period), (rate, origin) in sorted(series.rates.items())],
    )
    conn.executemany(
        "INSERT INTO bond_reference_rate (date_from, rate) VALUES (?, ?)",
        [(day, float(rate)) for day, rate in series.reference],
    )

    csv_path = bond_files.bonds_file(settings.manual_dir)
    csv_id = file_ids.get(csv_path)
    for message in lots.errors:
        issue(csv_id, None, message)
    kinds = {a.id: a.kind for a in accounts}
    for lot in lots.lots:
        if kinds.get(lot.account_id) != "bonds":
            issue(csv_id, lot.account_id,
                  f"{csv_path.name}, wiersz {lot.row}: rachunek {lot.account_id} nie jest rachunkiem obligacji "
                  "(kind: bonds w accounts.yaml). Wiersz pominięto.")
            continue
        conn.execute(
            "INSERT INTO bond_lots (account_id, series, purchase_date, quantity, note, row_no, source_file_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (lot.account_id, lot.series, lot.purchase_date.isoformat(), lot.quantity, lot.note or None, lot.row,
             csv_id),
        )


def _write_cash(conn, settings: Settings, accounts, result: SyncResult) -> None:
    """Balance snapshots of the bank accounts from cash_balances.csv (D-027)."""
    path = cash_files.cash_file(settings.manual_dir)
    if not path.exists():
        return
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    parsed = cash_files.read_snapshots(path, {a.id: a.kind for a in accounts}, date.today())
    file_id = conn.execute(
        "INSERT INTO source_files (kind, path, sha256, parser_version, imported_at, rows_json) "
        "VALUES ('manual_cash', ?, ?, ?, ?, ?)",
        (path.relative_to(settings.data_dir).as_posix(), _sha256(path), cash_files.CASH_PARSER_VERSION, now,
         json.dumps({"cash_snapshots": len(parsed.snapshots)})),
    ).lastrowid
    for message in parsed.errors:
        conn.execute(
            "INSERT INTO import_issues (source_file_id, account_id, severity, message) VALUES (?, NULL, 'error', ?)",
            (file_id, message),
        )
        result.errors.append(message)
    conn.executemany(
        "INSERT INTO cash_snapshots (account_id, date, balance, note, row_no, source_file_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(s.account_id, s.day.isoformat(), float(s.balance), s.note or None, s.row, file_id)
         for s in parsed.snapshots],
    )


def _write(conn, settings: Settings, accounts, parsed, result: SyncResult) -> None:
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    for account in accounts:
        conn.execute(
            "INSERT INTO accounts (id, external_no, alias, institution, kind, currency, tax_wrapper) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (account.id, account.external_no, account.alias, account.institution, account.kind,
             account.currency, account.tax_wrapper),
        )
    known_accounts = {a.id for a in accounts}

    def issue(file_id, account_id, severity, message):
        conn.execute(
            "INSERT INTO import_issues (source_file_id, account_id, severity, message) VALUES (?, ?, ?, ?)",
            (file_id, account_id, severity, message),
        )
        (result.errors if severity == "error" else result.warnings).append(message)

    overrides_path = instrument_files.instruments_file(settings.config_dir)
    for config_file in (settings.accounts_file, overrides_path):
        if config_file.exists():
            conn.execute(
                "INSERT INTO source_files (kind, path, sha256, parser_version, imported_at) "
                "VALUES ('config', ?, ?, 1, ?)",
                (config_file.relative_to(settings.data_dir).as_posix(), _sha256(config_file), now),
            )
    try:
        overrides = instrument_files.load_overrides(overrides_path)
    except instrument_files.InstrumentsFileError as exc:
        overrides = {}
        issue(None, None, "error", f"{exc}; the class overrides are ignored until the file is fixed")

    # Merge all files; later exports (by end date) win for the state of a position.
    instruments: dict[str, dict] = {}
    positions: dict[tuple[str, str], tuple[Position, int]] = {}
    cash: dict[tuple[str, str], tuple] = {}
    latest_open: dict[str, tuple[str, set[str]]] = {}  # account -> (date_to, open position ids)
    seen_open: dict[tuple[str, str], str] = {}  # (account, position) -> file name that listed it open
    open_records: dict[tuple[str, str], tuple[Position, int, date]] = {}  # newest file listing it open
    closed_records: dict[tuple[str, str], tuple[Position, int]] = {}

    ordered = sorted(parsed, key=lambda item: (item[1].date_to if item[1] else datetime.min.date(), item[0].name))
    for path, data, error in ordered:
        rel = path.relative_to(settings.data_dir).as_posix()
        account_id = xtb_account_id(data.account_number) if data else None
        rows = None
        if data:
            rows = {"cash": len(data.cash), "open": len(data.open_positions), "closed": len(data.closed_positions)}
        file_id = conn.execute(
            "INSERT INTO source_files (kind, path, sha256, parser_version, imported_at, rows_json, account_id, "
            "date_from, date_to) VALUES ('xtb', ?, ?, ?, ?, ?, ?, ?, ?)",
            (rel, _sha256(path), PARSER_VERSION, now, json.dumps(rows) if rows else None, account_id,
             data.date_from.isoformat() if data else None, data.date_to.isoformat() if data else None),
        ).lastrowid
        if error:
            issue(file_id, None, "error", f"{path.name}: {error}. Nothing from this file was imported.")
            continue
        if account_id not in known_accounts:
            issue(file_id, None, "error", f"{path.name}: account {account_id} is missing from accounts.yaml")
            continue
        for warning in data.warnings:
            issue(file_id, account_id, "warning", f"{path.name}: {warning}")
        if data.empty:
            continue

        for info in data.instruments.values():
            entry = instruments.setdefault(info.symbol, {"name": None, "category": None})
            entry["name"] = info.name or entry["name"]
            entry["category"] = info.category or entry["category"]

        for op in data.cash:
            key = (account_id, op.operation_id)
            if key in cash and cash[key][0].amount != op.amount:
                issue(file_id, account_id, "warning",
                      f"{path.name}: operation {op.operation_id} differs from an earlier export; kept the first")
            cash.setdefault(key, (op, file_id))

        open_ids = set()
        for position in data.open_positions:
            key = (account_id, position.position_id)
            open_ids.add(position.position_id)
            seen_open[key] = path.name
            open_records[key] = (position, file_id, data.date_to)  # files go oldest first: the newest wins
        for position in data.closed_positions:
            closed_records[(account_id, position.position_id)] = (position, file_id)
        if data.date_to.isoformat() >= latest_open.get(account_id, ("", set()))[0]:
            latest_open[account_id] = (data.date_to.isoformat(), open_ids)

    positions.update(_merge_open_and_closed(open_records, closed_records))

    instrument_ids = {}
    ticker_overrides = load_yahoo_overrides(settings.config_dir)
    for symbol, info in sorted(instruments.items()):
        category = info["category"]
        ticker = yahoo_ticker(symbol, ticker_overrides)
        asset_class = instrument_files.classify(symbol, info["name"], category, overrides)
        instrument_ids[symbol] = conn.execute(
            "INSERT INTO instruments (xtb_symbol, name, category, asset_class, yahoo_ticker) VALUES (?, ?, ?, ?, ?)",
            (symbol, info["name"], category, asset_class, ticker),
        ).lastrowid
        if ticker is None:
            issue(None, None, "warning", f"{symbol}: no rule maps this ticker to Yahoo yet (YAHOO_SUFFIX in "
                  "sources/sync.py or config/yahoo_tickers.yaml), so it has no market price and is valued at "
                  "purchase cost")

    buys: dict[tuple, list] = {}
    sells: dict[tuple, list] = {}
    for (acc, _), (op, _) in sorted(cash.items(), key=lambda kv: kv[1][0].ts):
        if op.ledger_type in ("BUY", "SELL"):
            (buys if op.ledger_type == "BUY" else sells).setdefault((acc, op.position_id), []).append(op)
    for (account_id, _), (op, file_id) in sorted(cash.items(), key=lambda kv: kv[1][0].ts):
        conn.execute(
            "INSERT INTO cash_ledger (account_id, ts, type, amount, instrument_id, position_id, broker_type, "
            "comment, source_ref, source_file_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, _iso(op.ts), op.ledger_type, op.amount, instrument_ids.get(op.symbol or ""),
             op.position_id, op.broker_type, op.comment, op.operation_id, file_id),
        )

    buy_for = _match(positions, buys, lambda p: p.open_time)
    sell_for = _match(positions, sells, lambda p: p.close_time)
    _continue_split_closes(positions, sells, sell_for, issue)
    for (account_id, position_id), (p, file_id) in sorted(positions.items(), key=lambda kv: kv[1][0].open_time):
        bought, sold = buy_for.get((account_id, position_id), []), sell_for.get((account_id, position_id), [])
        # All parts of a split order (D-048); the Closed Positions sheet's own values win when present.
        purchase = p.purchase_value if p.purchase_value is not None else (
            round(-sum(op.amount for op in bought), 2) if bought else None)
        sale = p.sale_value if p.sale_value is not None else (
            round(sum(op.amount for op in sold), 2) if sold else None)
        if purchase is None and position_id.endswith("/rest"):
            purchase = _rest_cost(positions, buy_for, (account_id, position_id.removesuffix("/rest")), p)
        conn.execute(
            "INSERT INTO positions (account_id, position_id, instrument_id, side, volume, open_time, open_price, "
            "close_time, close_price, purchase_value, sale_value, source_file_id) "
            "VALUES (?, ?, ?, 'BUY', ?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, position_id, instrument_ids[p.symbol], p.volume, _iso(p.open_time), p.open_price,
             _iso(p.close_time), p.close_price, purchase, sale, file_id),
        )
        if p.close_time is None and purchase is None:
            issue(
                file_id,
                account_id,
                "warning",
                f"{p.symbol} position {position_id} has no purchase value; export a range that includes its purchase "
                "to calculate cost",
            )
    _reconcile(issue, positions, buys, sells, latest_open, seen_open, buy_for, sell_for)


def _technical_close(p: Position) -> bool:
    """Closed at its own open price for its own purchase value: how XTB books a stock split (D-051, D-056)."""
    if p.close_price is None or not p.open_price or abs(p.close_price / p.open_price - 1) > 1e-6:
        return False
    return p.sale_value is None or not p.purchase_value or abs(p.sale_value / p.purchase_value - 1) <= 1e-4


def _merge_open_and_closed(open_records: dict, closed_records: dict) -> dict:
    """One entry per position, from the Open and Closed Positions sheets of all exports (D-056).

    XTB keeps a position's ID when it closes it only in part, or only for a stock split: the same ID
    is then both in Closed Positions and, in an export that ends after that close, in Open Positions.
    Such a position is still open. A technical (split) close is dropped, since the open record already
    holds the shares in today's units from the original open date; after a partial sale the sold part
    stays as a closed lot and the rest becomes a lot of its own. An open record from an export that
    ends before the close is simply out of date.
    """
    merged: dict = {}
    for key in open_records.keys() | closed_records.keys():
        opened, closed = open_records.get(key), closed_records.get(key)
        if closed is None:
            merged[key] = opened[:2]
        elif opened is None or opened[2] < closed[0].close_time.date():
            merged[key] = closed
        elif _technical_close(closed[0]):
            merged[key] = opened[:2]
        else:
            merged[key] = closed
            rest = replace(opened[0], position_id=f"{key[1]}/rest")
            merged[(key[0], rest.position_id)] = (rest, opened[1])
    return merged


def _rest_cost(positions: dict, buy_for: dict, sold_key: tuple, rest: Position) -> float | None:
    """Cost of what is left after a partial sale (D-061).

    The purchases carry the position's own ID, so they pair with the sold part. What is left
    cost all purchases minus the sold part's purchase value; when that is not known, the
    purchases are split by volume.
    """
    bought = buy_for.get(sold_key, [])
    if not bought or sold_key not in positions:
        return None
    total = -sum(op.amount for op in bought)
    sold = positions[sold_key][0]
    if sold.purchase_value is not None and 0 < sold.purchase_value < total:
        return round(total - sold.purchase_value, 2)
    whole = sold.volume + rest.volume
    return round(total * rest.volume / whole, 2) if whole else None


CLOSE_PRICE_RE = re.compile(r"^CLOSE BUY .*@ (?P<price>[\d.]+)$")


def _continue_split_closes(positions: dict, sells: dict[tuple, list], sell_for: dict[tuple, list], issue) -> None:
    """A position XTB closed only for a stock split runs on until the shares are really sold (D-051).

    On a split XTB closes the old position at its own open price, with no sale in Cash Operations,
    and reopens the shares as a new position. When that new position is missing from the exports,
    the shares would vanish from the portfolio until their sale. Such a "technical" close is moved
    to the first day with sales of the same ticker on the account that no position claims; those
    sales become its sale value. The valuation then counts the old lot (split-adjusted) until then.
    """
    paired = {id(op) for group in sell_for.values() for op in group}
    for key, (p, file_id) in sorted(positions.items(), key=lambda kv: kv[1][0].close_time or datetime.max):
        if p.close_time is None or sell_for.get(key) or not _technical_close(p):
            continue
        later = sorted(
            (op for (account_id, _), group in sells.items() if account_id == key[0] for op in group
             if id(op) not in paired and op.symbol == p.symbol and op.ts > p.close_time),
            key=lambda op: op.ts,
        )
        if not later:
            issue(None, key[0], "warning",
                  f"{p.symbol} position {key[1]} was closed on {p.close_time:%Y-%m-%d} at its own open price "
                  "with no sale: probably a stock split, but the reopened position is not in the exports")
            continue
        day = later[0].ts.date()
        taken = [op for op in later if op.ts.date() == day]
        paired.update(id(op) for op in taken)
        sell_for[key] = taken
        found = CLOSE_PRICE_RE.match(taken[0].comment or "")
        positions[key] = (replace(p, close_time=taken[-1].ts, sale_value=round(sum(op.amount for op in taken), 2),
                                  close_price=float(found["price"]) if found else None), file_id)
        issue(None, key[0], "warning",
              f"{p.symbol} position {key[1]}: closed by XTB on {p.close_time:%Y-%m-%d} only for a stock split; "
              f"counted until its sale on {day:%Y-%m-%d}")


def _reconcile(issue, positions, buys, sells, latest_open, seen_open, buy_for, sell_for) -> None:
    """Cross-check sheets and exports; findings are warnings, never silent fixes."""
    paired_buys = {id(op) for group in buy_for.values() for op in group}
    paired_sells = {id(op) for group in sell_for.values() for op in group}
    for (account_id, position_id), group in buys.items():
        for op in group:
            if id(op) not in paired_buys:
                issue(None, account_id, "warning",
                      f"purchase {op.symbol} on {op.ts:%Y-%m-%d} (position {position_id}) has no matching position; "
                      "it was probably sold outside the exported date ranges")
    for (account_id, position_id), group in sells.items():
        for op in group:
            if id(op) not in paired_sells:
                issue(None, account_id, "warning",
                      f"sale {op.symbol} on {op.ts:%Y-%m-%d} (position {position_id}) has no closed position")
    for key, group in buy_for.items():
        p = positions[key][0]
        volumes = [_fill(op)[0] for op in group]
        if len(group) > 1 and None not in volumes and abs(sum(volumes) - p.volume) > 1e-6:
            issue(None, key[0], "warning",
                  f"{p.symbol} position {key[1]}: the purchases found add up to {sum(volumes):g} of "
                  f"{p.volume:g} units, so its cost is incomplete")
    for (account_id, position_id), (p, _) in positions.items():
        _, open_now = latest_open.get(account_id, ("", set()))
        listed_id = position_id.removesuffix("/rest")  # the rest after a partial sale keeps XTB's ID (D-056)
        if p.close_time is None and listed_id not in open_now:
            issue(None, account_id, "warning",
                  f"{p.symbol} position {listed_id} was open in {seen_open.get((account_id, listed_id))} "
                  "but is missing from the newest export; export a range that covers its sale")
