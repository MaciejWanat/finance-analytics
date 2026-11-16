#!/usr/bin/env python3
"""Block commits that could contain real financial data.

Usage:
    python scripts/check_no_private_data.py           # files staged for commit (default)
    python scripts/check_no_private_data.py --all     # every tracked file
    python scripts/check_no_private_data.py PATH ...  # given working-tree files

Rules (docs/decisions.md, D-014):
  1. Nothing under data/ or data-*/ (local data directories).
  2. No spreadsheets, statements, documents, databases or secrets, except
     allowlisted public data and *.example.* files that hold fake values.
  3. YAML only in allowlisted places (*.example.yaml, .github/, package resources).
  4. No text that looks like a bank account number (IBAN or Polish NRB, checksum
     validated) or a payment card number (Luhn validated).

A line containing the marker "privacy-check: allow" is skipped by rule 4. Use it
only for synthetic values, and never bypass this check with `git commit --no-verify`.

Standard library only, so the git hook can run it without the project venv.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ALLOW_MARKER = "privacy-check: allow"

# Public data and fake examples that may be committed despite their extension.
ALLOWLIST = (
    "*.example.*",
    "src/finance_analytics/resources/*",
    ".github/*",
)

BLOCKED_EXTENSIONS = {
    # spreadsheets and tabular exports
    ".xlsx", ".xlsm", ".xls", ".ods", ".csv", ".tsv",
    # statements and documents
    ".pdf", ".mt940", ".sta", ".ofx", ".qif", ".qfx",
    # databases and dataframes
    ".db", ".db-journal", ".db-wal", ".db-shm", ".sqlite", ".sqlite3",
    ".parquet", ".feather", ".pkl", ".pickle",
}
YAML_EXTENSIONS = {".yaml", ".yml"}
BLOCKED_NAMES = {".env", "secrets.toml"}
DATA_DIR_RE = re.compile(r"^(data|data-[^/]+)/")

# IBAN lengths per country (ISO 13616 registry). Unknown prefixes are ignored,
# which keeps ISINs (e.g. "US...") and random identifiers out of the results.
IBAN_LENGTHS = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16, "BG": 22,
    "BH": 22, "BR": 29, "BY": 28, "CH": 21, "CR": 22, "CY": 28, "CZ": 24, "DE": 22,
    "DK": 18, "DO": 28, "EE": 20, "EG": 29, "ES": 24, "FI": 18, "FO": 18, "FR": 27,
    "GB": 22, "GE": 22, "GI": 23, "GL": 18, "GR": 27, "GT": 28, "HR": 21, "HU": 28,
    "IE": 22, "IL": 23, "IS": 26, "IT": 27, "JO": 30, "KW": 30, "KZ": 20, "LB": 28,
    "LC": 32, "LI": 21, "LT": 20, "LU": 20, "LV": 21, "MC": 27, "MD": 24, "ME": 22,
    "MK": 19, "MR": 27, "MT": 31, "MU": 30, "NL": 18, "NO": 15, "PK": 24, "PL": 28,
    "PS": 29, "PT": 25, "QA": 29, "RO": 24, "RS": 22, "SA": 24, "SE": 24, "SI": 19,
    "SK": 24, "SM": 27, "TN": 24, "TR": 26, "UA": 29, "VG": 24, "XK": 20,
}

IBAN_RE = re.compile(r"\b([A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30})")
NRB_RE = re.compile(r"(?<![\dA-Z])(\d{2}(?: ?\d{4}){6})(?!\d)")
CARD_RE = re.compile(r"(?<!\d)((?:\d[ -]?){14,15}\d)(?!\d)")


# --------------------------------------------------------------------------- checks


def iban_is_valid(iban: str) -> bool:
    """ISO 13616 mod-97 check on a compact (no spaces) IBAN."""
    if IBAN_LENGTHS.get(iban[:2]) != len(iban):
        return False
    rearranged = iban[4:] + iban[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


def luhn_is_valid(number: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _looks_like_card(number: str) -> bool:
    if len(number) == 15:
        return number[:2] in {"34", "37"} and luhn_is_valid(number)
    if len(number) == 16:
        known_prefix = number[0] == "4" or 51 <= int(number[:2]) <= 55 or 2221 <= int(number[:4]) <= 2720
        return known_prefix and luhn_is_valid(number)
    return False


def check_path(path: str) -> list[str]:
    """Problems detectable from the path alone (rules 1-3)."""
    p = PurePosixPath(path.replace("\\", "/"))
    posix = p.as_posix()
    name = p.name.lower()
    suffix = p.suffix.lower()
    if DATA_DIR_RE.match(posix):
        return ["inside a local data directory (data/ or data-*/)"]
    if any(fnmatch.fnmatch(posix, pattern) for pattern in ALLOWLIST):
        return []
    if name in BLOCKED_NAMES or name.startswith(".env."):
        return ["secrets file"]
    if suffix in BLOCKED_EXTENSIONS:
        return [f"blocked file type '{suffix}' (financial data / documents / databases)"]
    if suffix in YAML_EXTENSIONS:
        return ["YAML outside the allowlist (use *.example.yaml with fake values)"]
    return []


def scan_text(text: str) -> list[str]:
    """Problems found in file content (rule 4). Returns 'line N: reason' entries."""
    problems: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line:
            continue
        for match in IBAN_RE.finditer(line):
            compact = match.group(1).replace(" ", "")
            expected = IBAN_LENGTHS.get(compact[:2])
            if expected and len(compact) >= expected and iban_is_valid(compact[:expected]):
                problems.append(f"line {lineno}: looks like a bank account number (IBAN)")
        for match in NRB_RE.finditer(line):
            if iban_is_valid("PL" + match.group(1).replace(" ", "")):
                problems.append(f"line {lineno}: looks like a Polish bank account number (NRB)")
        for match in CARD_RE.finditer(line):
            if _looks_like_card(re.sub(r"[ -]", "", match.group(1))):
                problems.append(f"line {lineno}: looks like a payment card number")
    return problems


def check_file(path: str, content: bytes | None) -> list[str]:
    problems = check_path(path)
    if problems or content is None:
        return problems
    if b"\x00" in content[:8192]:  # binary file, nothing to scan as text
        return []
    return scan_text(content.decode("utf-8", errors="replace"))


# ----------------------------------------------------------------------------- git


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def _split_z(output: bytes) -> list[str]:
    return [p for p in output.decode("utf-8").split("\0") if p]


def _index_content(path: str) -> bytes | None:
    try:
        return _git("show", f":{path}")
    except subprocess.CalledProcessError:
        return None


def collect(mode: str, paths: list[str]) -> dict[str, list[str]]:
    if mode == "paths":
        targets = [(p, Path(p).read_bytes() if Path(p).is_file() else None) for p in paths]
    else:
        listed = (
            _git("ls-files", "-z")
            if mode == "all"
            else _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
        )
        targets = [(p, _index_content(p)) for p in _split_z(listed)]
    report = {}
    for path, content in targets:
        problems = check_file(path, content)
        if problems:
            report[path] = problems
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", help="working-tree files to check instead of git")
    parser.add_argument("--all", action="store_true", help="check every tracked file")
    parser.add_argument("--staged", action="store_true", help="check staged files (default)")
    args = parser.parse_args(argv)
    mode = "paths" if args.paths else "all" if args.all else "staged"

    try:
        report = collect(mode, args.paths)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"privacy check: could not run git ({exc})", file=sys.stderr)
        return 2

    if not report:
        print(f"privacy check: OK ({mode})")
        return 0

    print("privacy check: BLOCKED - possible private financial data", file=sys.stderr)
    for path, problems in sorted(report.items()):
        for problem in problems:
            print(f"  {path}: {problem}", file=sys.stderr)
    print(
        "\nOnly synthetic mock data may be committed (generate it in code, or use\n"
        "*.example.* files with fake values). Unstage with: git restore --staged <file>\n"
        "Never bypass this check with --no-verify.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
