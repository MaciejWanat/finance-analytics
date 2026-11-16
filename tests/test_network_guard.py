"""D-011: only src/finance_analytics/market/ may talk to the network."""

from __future__ import annotations

import ast
from pathlib import Path

from conftest import ROOT

NETWORK_MODULES = {
    "requests", "urllib", "urllib3", "http", "httpx", "aiohttp", "socket", "ssl",
    "yfinance", "curl_cffi", "websocket", "websockets", "ftplib", "smtplib", "telnetlib",
}
ALLOWED = ROOT / "src" / "finance_analytics" / "market"
SCANNED = [ROOT / "src", ROOT / "app", ROOT / "scripts"]


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_network_imports_only_in_market_package():
    offenders = []
    for base in SCANNED:
        for path in base.rglob("*.py"):
            if ALLOWED in path.parents:
                continue
            bad = _imported_roots(path) & NETWORK_MODULES
            if bad:
                offenders.append(f"{path.relative_to(ROOT)}: {sorted(bad)}")
    assert not offenders, "network access outside market/:\n" + "\n".join(offenders)
