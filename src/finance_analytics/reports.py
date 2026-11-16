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


def issues(db_path: Path) -> pd.DataFrame:
    return _query(db_path, "SELECT severity, account_id, message FROM import_issues ORDER BY severity, id")


def source_files(db_path: Path) -> pd.DataFrame:
    return _query(
        db_path,
        "SELECT path, account_id, date_from, date_to, rows_json, imported_at FROM source_files "
        "WHERE kind = 'xtb' ORDER BY account_id, date_to",
    )
