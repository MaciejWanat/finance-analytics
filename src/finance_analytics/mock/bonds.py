"""Synthetic treasury-bond purchases for the demo (mock values only, never real data)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from finance_analytics.sources.bonds import DEFAULT_ACCOUNT_ID, append_lot

# Real, public series codes with made-up dates and quantities.
DEMO_PURCHASES = [
    ("EDO0334", date(2024, 3, 12), 40, "demo: EDO z 2024"),
    ("COI1128", date(2024, 11, 20), 25, "demo: COI z kuponem co rok"),
    ("ROR0226", date(2025, 2, 10), 15, "demo: roczne, już wykupione"),
    ("EDO0735", date(2025, 7, 8), 30, "demo: EDO z 2025"),
    ("COI0929", date(2025, 9, 3), 20, "demo: COI z 2025"),
]


def write_mock_bonds(path: Path) -> Path:
    """Write data-demo/manual/bonds.csv from scratch."""
    path.unlink(missing_ok=True)
    for series, purchased, quantity, note in DEMO_PURCHASES:
        append_lot(path, DEFAULT_ACCOUNT_ID, series, purchased, quantity, note)
    return path
