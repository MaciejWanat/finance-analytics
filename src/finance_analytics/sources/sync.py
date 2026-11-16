"""Files in data/ -> projection tables in SQLite (D-002, D-015, D-016).

`import_xtb` archives export files under data/raw/xtb/<account number>/.
`sync` rebuilds every projection table when any source file, the accounts file or
the parser version changed since the last sync; otherwise it does nothing. The market
cache (later migrations) is never touched here.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from finance_analytics.config import Settings
from finance_analytics.db import connect, migrate
from finance_analytics.sources import bonds as bond_files
from finance_analytics.sources import cash as cash_files
from finance_analytics.sources.accounts import (
    load_accounts,
    register_bond_accounts,
    register_xtb_accounts,
    xtb_account_id,
)
from finance_analytics.sources.xtb.parser import (
    CATEGORY_TO_ASSET_CLASS,
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
YAHOO_SUFFIX = {".US": "", ".UK": ".L"}  # XTB suffix -> Yahoo suffix; only suffixes seen so far


def yahoo_ticker(xtb_symbol: str) -> str | None:
    base, dot, suffix = xtb_symbol.rpartition(".")
    if not dot or f".{suffix}" not in YAHOO_SUFFIX:
        return None
    return base + YAHOO_SUFFIX[f".{suffix}"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat(sep=" ") if moment else None


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


def import_xtb(source: Path, settings: Settings) -> ImportResult:
    """Copy an export folder (or a single file) into data/raw/xtb. Never modifies the source."""
    files = [source] if source.is_file() else sorted(source.rglob("*.xlsx"))
    result = ImportResult()
    for path in files:
        if path.name.startswith("~$"):  # Excel lock file
            continue
        try:
            stored, written = store_xtb_file(path.name, path.read_bytes(), settings)
        except XtbFormatError as exc:
            result.skipped.append((path, str(exc)))
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
    for path in _bond_sources(settings):
        state[path.relative_to(settings.data_dir).as_posix()] = (_sha256(path), bond_files.BONDS_PARSER_VERSION)
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

        found = sorted({(p.account_number, p.prefix, p.currency, p.tax_wrapper) for _, p, _ in parsed if p})
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

    accounts_file = settings.accounts_file
    if accounts_file.exists():
        conn.execute(
            "INSERT INTO source_files (kind, path, sha256, parser_version, imported_at) VALUES ('config', ?, ?, 1, ?)",
            (accounts_file.relative_to(settings.data_dir).as_posix(), _sha256(accounts_file), now),
        )

    # Merge all files; later exports (by end date) win for the state of a position.
    instruments: dict[str, dict] = {}
    positions: dict[tuple[str, str], tuple[Position, int]] = {}
    cash: dict[tuple[str, str], tuple] = {}
    latest_open: dict[str, tuple[str, set[str]]] = {}  # account -> (date_to, open position ids)
    seen_open: dict[tuple[str, str], str] = {}  # (account, position) -> file name that listed it open

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
            existing = positions.get(key)
            if existing is None or existing[0].close_time is None:
                positions[key] = (position, file_id)
        for position in data.closed_positions:
            positions[(account_id, position.position_id)] = (position, file_id)
        if data.date_to.isoformat() >= latest_open.get(account_id, ("", set()))[0]:
            latest_open[account_id] = (data.date_to.isoformat(), open_ids)

    instrument_ids = {}
    for symbol, info in sorted(instruments.items()):
        category = info["category"]
        ticker = yahoo_ticker(symbol)
        instrument_ids[symbol] = conn.execute(
            "INSERT INTO instruments (xtb_symbol, name, category, asset_class, yahoo_ticker) VALUES (?, ?, ?, ?, ?)",
            (symbol, info["name"], category, CATEGORY_TO_ASSET_CLASS.get(category or "", "other"), ticker),
        ).lastrowid
        if ticker is None:
            issue(None, None, "warning", f"{symbol}: no rule maps this ticker to Yahoo yet (YAHOO_SUFFIX in "
                  "sources/sync.py), so it has no market price and is valued at purchase cost")

    buys = {(acc, op.position_id): op for (acc, _), (op, _) in cash.items() if op.ledger_type == "BUY"}
    sells = {(acc, op.position_id): op for (acc, _), (op, _) in cash.items() if op.ledger_type == "SELL"}
    for (account_id, _), (op, file_id) in sorted(cash.items(), key=lambda kv: kv[1][0].ts):
        conn.execute(
            "INSERT INTO cash_ledger (account_id, ts, type, amount, instrument_id, position_id, broker_type, "
            "comment, source_ref, source_file_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, _iso(op.ts), op.ledger_type, op.amount, instrument_ids.get(op.symbol or ""),
             op.position_id, op.broker_type, op.comment, op.operation_id, file_id),
        )

    for (account_id, position_id), (p, file_id) in sorted(positions.items(), key=lambda kv: kv[1][0].open_time):
        buy, sell = buys.get((account_id, position_id)), sells.get((account_id, position_id))
        purchase = p.purchase_value if p.purchase_value is not None else (-buy.amount if buy else None)
        sale = p.sale_value if p.sale_value is not None else (sell.amount if sell else None)
        conn.execute(
            "INSERT INTO positions (account_id, position_id, instrument_id, side, volume, open_time, open_price, "
            "close_time, close_price, purchase_value, sale_value, source_file_id) "
            "VALUES (?, ?, ?, 'BUY', ?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, position_id, instrument_ids[p.symbol], p.volume, _iso(p.open_time), p.open_price,
             _iso(p.close_time), p.close_price, purchase, sale, file_id),
        )
    _reconcile(issue, positions, buys, sells, latest_open, seen_open)


def _reconcile(issue, positions, buys, sells, latest_open, seen_open) -> None:
    """Cross-check sheets and exports; findings are warnings, never silent fixes."""
    for (account_id, position_id), op in buys.items():
        if (account_id, position_id) not in positions:
            issue(None, account_id, "warning",
                  f"purchase {op.symbol} on {op.ts:%Y-%m-%d} (position {position_id}) has no matching position; "
                  "it was probably sold outside the exported date ranges")
    for (account_id, position_id), op in sells.items():
        position = positions.get((account_id, position_id))
        if position is None or position[0].close_time is None:
            issue(None, account_id, "warning",
                  f"sale {op.symbol} on {op.ts:%Y-%m-%d} (position {position_id}) has no closed position")
    for (account_id, position_id), (p, _) in positions.items():
        _, open_now = latest_open.get(account_id, ("", set()))
        if p.close_time is None and position_id not in open_now:
            issue(None, account_id, "warning",
                  f"{p.symbol} position {position_id} was open in {seen_open.get((account_id, position_id))} "
                  "but is missing from the newest export; export a range that covers its sale")
