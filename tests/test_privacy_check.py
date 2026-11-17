"""D-014: the pre-commit privacy check.

Account and card numbers used here are generated at runtime (valid checksums), so
no number that would trip the check is ever written into this file.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

import check_no_private_data as check
import pytest
from conftest import ROOT


def fake_pl_iban(bban: str = "109010140000071219812874") -> str:
    """Valid-checksum Polish IBAN for a synthetic 24-digit BBAN."""
    check_digits = 98 - int(bban + "2521" + "00") % 97  # P=25, L=21
    return f"PL{check_digits:02d}{bban}"


def fake_card(prefix: str = "411111111111111") -> str:
    """Luhn-valid 16-digit number for a synthetic 15-digit prefix."""
    for last in "0123456789":
        if check.luhn_is_valid(prefix + last):
            return prefix + last
    raise AssertionError("unreachable")


@pytest.mark.parametrize(
    "path",
    [
        "data/finance.db",
        "data/raw/xtb/123/USD_123.xlsx",
        "data-demo/anything.txt",
        "exports/USD_2025.xlsx",
        "notes/balances.csv",
        "statement.pdf",
        "backup.sqlite3",
        "my.mt940",
        ".env",
        ".streamlit/secrets.toml",
        "config/accounts.yaml",
    ],
)
def test_blocks_private_paths(path):
    assert check.check_path(path), path


@pytest.mark.parametrize(
    "path",
    [
        "src/finance_analytics/cli.py",
        "docs/decisions.md",
        "accounts.example.yaml",
        "docs/cash_balances.example.csv",
        "src/finance_analytics/resources/bond_series.csv",
        ".github/workflows/ci.yml",
        ".streamlit/config.toml",
        "src/finance_analytics/app/.streamlit/config.toml",
    ],
)
def test_allows_code_docs_and_examples(path):
    assert check.check_path(path) == [], path


def test_detects_iban_nrb_and_card_numbers():
    iban = fake_pl_iban()
    spaced = " ".join([iban[:4]] + [iban[i : i + 4] for i in range(4, 28, 4)])
    nrb = iban[2:]
    assert check.iban_is_valid(iban)
    assert check.scan_text(f"transfer from {iban}")
    assert check.scan_text(f"konto: {spaced}")
    assert check.scan_text(f"nrb {nrb}")
    assert check.scan_text(f"card {fake_card()}")


def test_ignores_lookalikes_and_allow_marker():
    iban = fake_pl_iban()
    broken = iban[:-1] + str((int(iban[-1]) + 1) % 10)  # checksum no longer valid
    assert check.scan_text(f"value {broken}") == []
    assert check.scan_text("ISIN US0378331005, timestamp 1731753600000, id 12345678") == []
    assert check.scan_text(f"{iban}  # {check.ALLOW_MARKER}") == []


@pytest.mark.skipif(shutil.which("git") is None or not (ROOT / ".git").exists(), reason="needs a git checkout")
def test_tracked_and_staged_files_are_clean():
    for mode in ("--all", "--staged"):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "check_no_private_data.py"), mode],
            cwd=ROOT, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
