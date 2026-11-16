"""Read-only queries over the projection tables, returned as DataFrames for the UI."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd


def open_readonly(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)


def _query(db_path: Path, sql: str, params: tuple = ()) -> pd.DataFrame:
    with closing(open_readonly(db_path)) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def accounts_overview(db_path: Path) -> pd.DataFrame:
    """One row per account: files, date range, operations, positions, cash balance."""
    return _query(
        db_path,
        """
        SELECT a.id, a.alias, a.currency, a.tax_wrapper, a.external_no,
               (SELECT COUNT(*) FROM source_files f WHERE f.account_id = a.id) AS files,
               (SELECT MIN(date_from) FROM source_files f WHERE f.account_id = a.id) AS date_from,
               (SELECT MAX(date_to) FROM source_files f WHERE f.account_id = a.id) AS date_to,
               (SELECT COUNT(*) FROM cash_ledger c WHERE c.account_id = a.id) AS operations,
               (SELECT COUNT(*) FROM positions p WHERE p.account_id = a.id AND p.close_time IS NULL) AS open_positions,
               (SELECT COUNT(*) FROM positions p WHERE p.account_id = a.id AND p.close_time IS NOT NULL)
                   AS closed_positions,
               (SELECT ROUND(COALESCE(SUM(amount), 0), 2) FROM cash_ledger c WHERE c.account_id = a.id) AS cash
        FROM accounts a
        ORDER BY a.alias
        """,
    )


def cash_ledger(db_path: Path, account_id: str) -> pd.DataFrame:
    df = _query(
        db_path,
        """
        SELECT c.ts, c.type, c.broker_type, i.xtb_symbol AS symbol, i.name, c.amount, c.comment, c.source_ref
        FROM cash_ledger c LEFT JOIN instruments i ON i.id = c.instrument_id
        WHERE c.account_id = ? ORDER BY c.ts DESC
        """,
        (account_id,),
    )
    df["ts"] = pd.to_datetime(df["ts"])
    return df


def positions(db_path: Path, account_id: str, *, open_only: bool) -> pd.DataFrame:
    condition = "p.close_time IS NULL" if open_only else "p.close_time IS NOT NULL"
    df = _query(
        db_path,
        f"""
        SELECT i.xtb_symbol AS symbol, i.name, i.asset_class, p.position_id, p.volume, p.open_time, p.open_price,
               p.close_time, p.close_price, p.purchase_value, p.sale_value
        FROM positions p JOIN instruments i ON i.id = p.instrument_id
        WHERE p.account_id = ? AND {condition}
        ORDER BY p.open_time DESC
        """,
        (account_id,),
    )
    for column in ("open_time", "close_time"):
        df[column] = pd.to_datetime(df[column])
    return df


def holdings(db_path: Path) -> pd.DataFrame:
    """Open volume per account and instrument (no prices yet)."""
    return _query(
        db_path,
        """
        SELECT a.alias AS account, i.xtb_symbol AS symbol, i.name, i.asset_class,
               ROUND(SUM(p.volume), 4) AS volume, COUNT(*) AS lots, ROUND(SUM(p.purchase_value), 2) AS cost,
               a.currency
        FROM positions p JOIN instruments i ON i.id = p.instrument_id JOIN accounts a ON a.id = p.account_id
        WHERE p.close_time IS NULL
        GROUP BY a.alias, i.xtb_symbol ORDER BY a.alias, i.xtb_symbol
        """,
    )


def price_coverage(db_path: Path) -> pd.DataFrame:
    """Per instrument: Yahoo ticker, currency, cached range and the last download error."""
    return _query(
        db_path,
        """
        SELECT i.xtb_symbol AS symbol, i.yahoo_ticker AS ticker, i.name, t.currency, t.exchange,
               (SELECT MIN(date) FROM prices p WHERE p.ticker = i.yahoo_ticker) AS first,
               (SELECT MAX(date) FROM prices p WHERE p.ticker = i.yahoo_ticker) AS last,
               (SELECT COUNT(*) FROM prices p WHERE p.ticker = i.yahoo_ticker) AS days,
               (SELECT COUNT(*) FROM corporate_actions a WHERE a.ticker = i.yahoo_ticker AND a.kind = 'SPLIT')
                   AS splits,
               f.last_error AS error
        FROM instruments i
        LEFT JOIN ticker_info t ON t.ticker = i.yahoo_ticker
        LEFT JOIN fetch_log f ON f.source = 'yahoo' AND f.key = i.yahoo_ticker
        ORDER BY i.xtb_symbol
        """,
    )


def fx_coverage(db_path: Path) -> pd.DataFrame:
    return _query(
        db_path,
        """
        SELECT r.currency, MIN(r.date) AS first, MAX(r.date) AS last, COUNT(*) AS days,
               (SELECT mid FROM fx_rates x WHERE x.currency = r.currency ORDER BY date DESC LIMIT 1) AS latest,
               f.last_error AS error
        FROM fx_rates r LEFT JOIN fetch_log f ON f.source = 'nbp' AND f.key = r.currency
        GROUP BY r.currency ORDER BY r.currency
        """,
    )


def cpi_monthly(db_path: Path) -> pd.DataFrame:
    """Published CPI by month (index points): columns `month` (first day, Timestamp), `mom`, `yoy`.

    Empty when the table does not exist yet (database not migrated) or nothing was fetched.
    """
    try:
        df = _query(db_path, "SELECT year, month, mom, yoy FROM cpi_monthly WHERE mom IS NOT NULL ORDER BY year, month")
    except (sqlite3.OperationalError, pd.errors.DatabaseError):
        df = pd.DataFrame(columns=["year", "month", "mom", "yoy"])
    months = pd.to_datetime(dict(year=df["year"], month=df["month"], day=1))
    return pd.DataFrame({"month": months, "mom": df["mom"], "yoy": df["yoy"]})


def price_series(db_path: Path, ticker: str) -> pd.Series:
    df = _query(db_path, "SELECT date, close FROM prices WHERE ticker = ? ORDER BY date", (ticker,))
    return pd.Series(df["close"].to_numpy(), index=pd.to_datetime(df["date"]), name=ticker)


def fx_series(db_path: Path, currency: str) -> pd.Series:
    df = _query(db_path, "SELECT date, mid FROM fx_rates WHERE currency = ? ORDER BY date", (currency,))
    return pd.Series(df["mid"].to_numpy(), index=pd.to_datetime(df["date"]), name=currency)


def issues(db_path: Path) -> pd.DataFrame:
    return _query(db_path, "SELECT severity, account_id, message FROM import_issues ORDER BY severity, id")


def source_files(db_path: Path) -> pd.DataFrame:
    return _query(
        db_path,
        "SELECT path, account_id, date_from, date_to, rows_json, imported_at FROM source_files "
        "WHERE kind = 'xtb' ORDER BY account_id, date_to",
    )


# ------------------------------------------------------------------------------- bonds (D-026)


def bond_lots(db_path: Path) -> pd.DataFrame:
    """Every bond purchase from bonds.csv with its account and series type."""
    df = _query(
        db_path,
        """
        SELECT l.row_no, l.account_id, a.alias AS account, a.tax_wrapper, l.series, s.type, l.purchase_date,
               l.quantity, l.note
        FROM bond_lots l JOIN accounts a ON a.id = l.account_id LEFT JOIN bond_series s ON s.series = l.series
        ORDER BY l.purchase_date, l.series
        """,
    )
    df["purchase_date"] = pd.to_datetime(df["purchase_date"])
    return df


def bond_accounts(db_path: Path) -> pd.DataFrame:
    return _query(db_path, "SELECT id, alias, tax_wrapper FROM accounts WHERE kind = 'bonds' ORDER BY alias")


def bond_series(db_path: Path) -> pd.DataFrame:
    """Known series with their parameters, newest first."""
    return _query(
        db_path,
        "SELECT series, type, first_rate, margin, early_fee, origin FROM bond_series "
        "ORDER BY substr(series, 6, 2) || substr(series, 4, 2) DESC, series",
    )


def bond_issues(db_path: Path) -> pd.DataFrame:
    """Problems found in bonds.csv and bond_series.yaml."""
    return _query(
        db_path,
        """
        SELECT i.severity, i.message FROM import_issues i JOIN source_files f ON f.id = i.source_file_id
        WHERE f.kind = 'manual_bonds' OR f.path LIKE '%bond_series.yaml'
        ORDER BY i.id
        """,
    )


# -------------------------------------------------------------------------- cash at banks (D-027)


def account_kinds(db_path: Path) -> dict[str, str]:
    """Account id -> kind, for validating uploaded CSV files."""
    df = _query(db_path, "SELECT id, kind FROM accounts")
    return dict(zip(df["id"], df["kind"], strict=True))


def bank_accounts(db_path: Path) -> pd.DataFrame:
    return _query(db_path, "SELECT id, alias, institution, currency FROM accounts WHERE kind = 'bank' ORDER BY alias")


def cash_snapshots(db_path: Path) -> pd.DataFrame:
    """Every saved balance with its account, oldest first."""
    df = _query(
        db_path,
        """
        SELECT s.row_no, s.account_id, a.alias AS account, a.currency, s.date, s.balance, s.note
        FROM cash_snapshots s JOIN accounts a ON a.id = s.account_id
        ORDER BY s.date, a.alias
        """,
    )
    df["date"] = pd.to_datetime(df["date"])
    return df


def cash_issues(db_path: Path) -> pd.DataFrame:
    """Problems found in cash_balances.csv."""
    return _query(
        db_path,
        """
        SELECT i.severity, i.message FROM import_issues i JOIN source_files f ON f.id = i.source_file_id
        WHERE f.kind = 'manual_cash' ORDER BY i.id
        """,
    )
