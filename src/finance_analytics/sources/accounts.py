"""data/config/accounts.yaml: the list of accounts (source of truth, D-002).

Broker accounts are added automatically on import; the user edits aliases there.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

HEADER = """\
# Accounts known to finance-analytics. This file is private: data/ is git-ignored.
# XTB accounts are added here automatically when an export is imported, and a bonds
# account when data/manual/bonds.csv names one that is missing (set tax_wrapper: IKE
# yourself for bonds held in an IKE). Bank accounts are added on the "Gotówka" page.
# Change `alias` (the name the UI shows) whenever you like; keep `id` stable.
#
# Fields: id, institution, kind (broker | bank | bonds), currency, alias,
#         external_no (account number, stays local), tax_wrapper (null | IKE | IKZE)
"""

XTB_ALIASES = {"PLN": "XTB PLN", "EUR": "XTB EUR", "USD": "XTB USD", "IKE": "XTB IKE", "IKZE": "XTB IKZE"}


class AccountConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    institution: str
    kind: Literal["broker", "bank", "bonds"]
    currency: str
    alias: str
    external_no: str | None = None
    parent_no: str | None = None  # main account of a sub-account (e.g. the PLN account an IKE belongs to)
    tax_wrapper: Literal["IKE", "IKZE"] | None = None


class AccountsFileError(ValueError):
    pass


def xtb_account_id(number: str) -> str:
    return f"xtb-{number}"


def load_accounts(path: Path) -> list[AccountConfig]:
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        accounts = [AccountConfig(**item) for item in data.get("accounts") or []]
    except (yaml.YAMLError, ValidationError, TypeError, AttributeError) as exc:
        raise AccountsFileError(f"{path}: {exc}") from exc
    ids = [a.id for a in accounts]
    if len(ids) != len(set(ids)):
        raise AccountsFileError(f"{path}: duplicate account ids")
    return accounts


def save_accounts(path: Path, accounts: list[AccountConfig]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(
        {"accounts": [a.model_dump() for a in accounts]}, sort_keys=False, allow_unicode=True
    )
    path.write_text(HEADER + "\n" + body, encoding="utf-8")


BOND_ALIAS = "Obligacje skarbowe"


def register_bond_accounts(path: Path, account_ids: list[str]) -> list[AccountConfig]:
    """Add a bonds account (PKO, PLN) for every id used in bonds.csv but missing from the file.

    `tax_wrapper` stays null; set it to IKE by hand for bonds held in an IKE (D-026).
    """
    accounts = load_accounts(path)
    known = {a.id for a in accounts}
    aliases = {a.alias for a in accounts}
    added = []
    for account_id in account_ids:
        if account_id in known:
            continue
        alias = BOND_ALIAS if BOND_ALIAS not in aliases else f"{BOND_ALIAS} ({account_id})"
        account = AccountConfig(id=account_id, institution="pko", kind="bonds", currency="PLN", alias=alias)
        accounts.append(account)
        added.append(account)
        known.add(account_id)
        aliases.add(alias)
    if added:
        save_accounts(path, accounts)
    return added


def slug(text: str) -> str:
    """'Konto oszczędnościowe' -> 'konto-oszczednosciowe' (Polish letters folded to ASCII)."""
    folded = text.strip().lower().replace("ł", "l")
    folded = unicodedata.normalize("NFKD", folded).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")


def add_bank_account(path: Path, alias: str, currency: str, institution: str = "") -> AccountConfig:
    """Append a bank account; the id is `bank-<alias slug>`, made unique with a number.

    Existing entries are kept as they are. Raises ValueError for an empty or taken alias or a bad currency.
    """
    alias = alias.strip()
    currency = currency.strip().upper()
    if not alias:
        raise ValueError("nazwa konta nie może być pusta")
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError(f"waluta {currency!r} nie jest kodem ISO (np. PLN, EUR)")
    accounts = load_accounts(path)
    if alias.lower() in {a.alias.lower() for a in accounts}:
        raise ValueError(f"konto o nazwie {alias!r} już istnieje")
    name = slug(alias) or "konto"
    base = name if name.startswith("bank-") else f"bank-{name}"
    known = {a.id for a in accounts}
    account_id, n = base, 2
    while account_id in known:
        account_id, n = f"{base}-{n}", n + 1
    account = AccountConfig(id=account_id, institution=institution.strip() or "bank", kind="bank",
                            currency=currency, alias=alias)
    save_accounts(path, [*accounts, account])
    return account


def register_xtb_accounts(
    path: Path, found: list[tuple[str, str, str, str | None, str | None]]
) -> list[AccountConfig]:
    """Add XTB accounts (number, prefix, currency, tax_wrapper, parent number) missing from the file.

    Existing entries, including edited aliases, are left untouched. Returns the added ones.
    """
    accounts = load_accounts(path)
    known = {a.id for a in accounts}
    aliases = {a.alias for a in accounts}
    added = []
    for number, prefix, currency, wrapper, parent in found:
        account_id = xtb_account_id(number)
        if account_id in known:
            continue
        alias = XTB_ALIASES[prefix]
        if alias in aliases:
            alias = f"{alias} …{number[-3:]}"
        account = AccountConfig(
            id=account_id, institution="xtb", kind="broker", currency=currency, alias=alias,
            external_no=number, parent_no=parent, tax_wrapper=wrapper,
        )
        accounts.append(account)
        added.append(account)
        known.add(account_id)
        aliases.add(alias)
    if added:
        save_accounts(path, accounts)
    return added
