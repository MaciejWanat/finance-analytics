"""Shared test setup. Tests never touch the network or real data."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src" / "finance_analytics" / "app"

# The Streamlit app imports its design layer as `ui.*` and the standalone tools
# live in scripts/; make both importable the same way they are at runtime.
for extra in (APP, ROOT / "scripts"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))


def go_online(settings) -> None:
    """Switch a test data directory to online mode (offline is the default, D-021)."""
    from finance_analytics.preferences import Preferences, save_preferences

    save_preferences(settings, Preferences(network="online"))
