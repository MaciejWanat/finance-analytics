"""Synthetic bank accounts and balances for the demo (mock values only, never real data)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from finance_analytics.sources.accounts import add_bank_account, load_accounts
from finance_analytics.sources.cash import append_snapshot

DEMO_ACCOUNTS = [("Bank PLN", "PLN", "Demo Bank"), ("Konto EUR", "EUR", "Demo Bank")]

# (account alias, date, balance, note): made-up salary-and-spending patterns.
DEMO_BALANCES = [
    ("Bank PLN", date(2024, 1, 15), "8200.00", "demo: start"),
    ("Bank PLN", date(2024, 6, 30), "11450.50", "demo"),
    ("Bank PLN", date(2024, 12, 31), "9800.00", "demo: święta"),
    ("Bank PLN", date(2025, 6, 30), "15230.75", "demo"),
    ("Bank PLN", date(2025, 12, 31), "12100.00", "demo"),
    ("Bank PLN", date(2026, 6, 30), "18400.00", "demo"),
    ("Bank PLN", date(2026, 11, 1), "16750.20", "demo"),
    ("Konto EUR", date(2024, 3, 1), "1500.00", "demo: start"),
    ("Konto EUR", date(2024, 12, 1), "2100.00", "demo"),
    ("Konto EUR", date(2025, 9, 1), "1800.00", "demo"),
    ("Konto EUR", date(2026, 5, 1), "2650.00", "demo"),
]


def write_mock_cash(accounts_file: Path, balances_file: Path) -> Path:
    """Add the two demo bank accounts (if missing) and write data-demo/manual/cash_balances.csv from scratch."""
    balances_file.unlink(missing_ok=True)
    ids = {}
    for alias, currency, institution in DEMO_ACCOUNTS:
        existing = next((a for a in load_accounts(accounts_file) if a.alias == alias), None)
        ids[alias] = (existing or add_bank_account(accounts_file, alias, currency, institution)).id
    for alias, day, balance, note in DEMO_BALANCES:
        append_snapshot(balances_file, ids[alias], day, Decimal(balance), note)
    return balances_file
