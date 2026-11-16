"""data/config/accounts.yaml: the list of accounts (source of truth, D-002).

Broker accounts are added automatically on import; the user edits aliases there.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

HEADER = """\
# Accounts known to finance-analytics. This file is private: data/ is git-ignored.
# XTB accounts are added here automatically when an export is imported, and a bonds
# account when data/manual/bonds.csv names one that is missing (set tax_wrapper: IKE
# yourself for bonds held in an IKE).
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


def register_xtb_accounts(path: Path, found: list[tuple[str, str, str, str | None]]) -> list[AccountConfig]:
    """Add XTB accounts (number, prefix, currency, tax_wrapper) missing from the file.

    Existing entries, including edited aliases, are left untouched. Returns the added ones.
    """
    accounts = load_accounts(path)
    known = {a.id for a in accounts}
    aliases = {a.alias for a in accounts}
    added = []
    for number, prefix, currency, wrapper in found:
        account_id = xtb_account_id(number)
        if account_id in known:
            continue
        alias = XTB_ALIASES[prefix]
        if alias in aliases:
            alias = f"{alias} …{number[-3:]}"
        account = AccountConfig(
            id=account_id, institution="xtb", kind="broker", currency=currency, alias=alias,
            external_no=number, tax_wrapper=wrapper,
        )
        accounts.append(account)
        added.append(account)
        known.add(account_id)
        aliases.add(alias)
    if added:
        save_accounts(path, accounts)
    return added
