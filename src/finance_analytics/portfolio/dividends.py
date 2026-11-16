"""Dividends: gross, withholding tax, net, in PLN; and an estimate of the Polish tax due (D-024).

Source: the broker's cash operations (DIVIDEND and its WHT), so amounts are what was
actually received. One payment = one (account, instrument, day) group.

PLN conversion follows Polish income tax rules (D-008): the NBP mid rate of the last
business day *before* the payment day ("D-1"). For PLN accounts the broker already
credited PLN, so the amount is taken as is.

Tax estimate for regular accounts (PIT-38): 19% of the gross dividend in PLN, minus
the tax already withheld abroad, never below zero. IKE and IKZE pay no Polish tax on
dividends while the money stays in the account. This is an estimate, not tax advice.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np
import pandas as pd

BELKA = 0.19  # Polish capital income tax rate


def load_events(db_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Raw dividend and withholding-tax operations, and NBP rates (currency, date, mid)."""
    with closing(sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)) as conn:
        events = pd.read_sql_query(
            """
            SELECT c.account_id, a.alias AS account, a.currency, a.tax_wrapper, substr(c.ts, 1, 10) AS date,
                   i.xtb_symbol AS symbol, i.name, c.type, c.amount, c.comment
            FROM cash_ledger c
            JOIN accounts a ON a.id = c.account_id
            LEFT JOIN instruments i ON i.id = c.instrument_id
            WHERE c.type IN ('DIVIDEND', 'WHT')
            """,
            conn,
        )
        try:
            fx = pd.read_sql_query("SELECT currency, date, mid FROM fx_rates", conn)
        except sqlite3.OperationalError:  # no market cache yet
            fx = pd.DataFrame(columns=["currency", "date", "mid"])
    events["date"] = pd.to_datetime(events["date"])
    fx["date"] = pd.to_datetime(fx["date"])
    return events, fx


def payments(events: pd.DataFrame, fx: pd.DataFrame) -> pd.DataFrame:
    """One row per dividend payment with gross, WHT, net (account currency and PLN) and tax due."""
    columns = ["date", "account_id", "account", "tax_wrapper", "currency", "symbol", "name", "gross", "wht", "net",
               "rate", "gross_pln", "wht_pln", "net_pln", "tax_due_pln"]
    if events.empty:
        return pd.DataFrame(columns=columns)
    keys = ["date", "account_id", "account", "tax_wrapper", "currency", "symbol", "name"]
    signed = events.assign(
        gross=np.where(events["type"] == "DIVIDEND", events["amount"], 0.0),
        wht=np.where(events["type"] == "WHT", -events["amount"], 0.0),
    )
    grouped = signed.groupby(keys, dropna=False, as_index=False)[["gross", "wht"]].sum()
    grouped["net"] = grouped["gross"] - grouped["wht"]

    rates = {c: g.set_index("date")["mid"].sort_index() for c, g in fx.groupby("currency")}

    def d_minus_1(currency: str, day: pd.Timestamp) -> float:
        if currency == "PLN":
            return 1.0
        series = rates.get(currency)
        if series is None or series.empty:
            return np.nan
        return float(series.asof(day - pd.Timedelta(days=1)))  # last NBP table before the payment day

    grouped["rate"] = [d_minus_1(c, d) for c, d in zip(grouped["currency"], grouped["date"], strict=True)]
    for column in ("gross", "wht", "net"):
        grouped[f"{column}_pln"] = (grouped[column] * grouped["rate"]).round(2)
    regular = grouped["tax_wrapper"].isna()
    grouped["tax_due_pln"] = np.where(
        regular, (BELKA * grouped["gross_pln"] - grouped["wht_pln"]).clip(lower=0).round(2), 0.0
    )
    return grouped[columns].sort_values("date", ignore_index=True)


def per_company(paid: pd.DataFrame) -> pd.DataFrame:
    if paid.empty:
        return pd.DataFrame(columns=["symbol", "name", "payments", "gross_pln", "wht_pln", "net_pln", "tax_due_pln",
                                     "wht_rate", "last"])
    table = paid.groupby(["symbol", "name"], dropna=False, as_index=False).agg(
        payments=("date", "count"), gross_pln=("gross_pln", "sum"), wht_pln=("wht_pln", "sum"),
        net_pln=("net_pln", "sum"), tax_due_pln=("tax_due_pln", "sum"), last=("date", "max"),
    )
    table["wht_rate"] = (table["wht_pln"] / table["gross_pln"]).where(table["gross_pln"] > 0)
    return table.sort_values("net_pln", ascending=False, ignore_index=True)


def per_year(paid: pd.DataFrame) -> pd.DataFrame:
    """Tax-year summary (calendar year of the payment)."""
    if paid.empty:
        return pd.DataFrame(columns=["year", "gross_pln", "wht_pln", "net_pln", "tax_due_pln"])
    return (
        paid.assign(year=paid["date"].dt.year)
        .groupby("year", as_index=False)[["gross_pln", "wht_pln", "net_pln", "tax_due_pln"]].sum()
        .sort_values("year", ascending=False, ignore_index=True)
    )
