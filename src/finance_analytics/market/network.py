"""The single gate in front of every network call (D-021, R-015).

Every entry point in `market/` that may reach the internet calls `require_online`
first. In offline mode it raises, so nothing leaves the machine.
"""

from __future__ import annotations

from finance_analytics.config import Settings
from finance_analytics.preferences import load_preferences


class OfflineError(RuntimeError):
    """Raised instead of making a network call while the app is in offline mode."""


OFFLINE_MESSAGE = (
    "Tryb offline: aplikacja nie łączy się z internetem. "
    "Włącz tryb online w Ustawieniach (albo `fa settings --online`), żeby pobrać dane rynkowe."
)


def is_online(settings: Settings) -> bool:
    return load_preferences(settings).online


def require_online(settings: Settings) -> None:
    if not is_online(settings):
        raise OfflineError(OFFLINE_MESSAGE)
