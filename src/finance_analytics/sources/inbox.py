"""XTB inbox folder: exports saved there are imported by themselves (D-028).

The folder is set in preferences (`inbox_dir`). New .xlsx files are copied into
data/raw/xtb by the same code as `fa import xtb`; the source folder is only read.
Local only: no network, so it works offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from finance_analytics.config import Settings
from finance_analytics.preferences import load_preferences
from finance_analytics.sources.sync import SyncResult, import_xtb, sync


@dataclass
class InboxResult:
    folder: Path
    copied: list[Path] = field(default_factory=list)
    already_imported: int = 0
    skipped: list[tuple[Path, str]] = field(default_factory=list)
    sync: SyncResult | None = None
    error: str | None = None


def check_inbox(settings: Settings) -> InboxResult | None:
    """Import new exports from the inbox folder. None when no folder is configured."""
    preferences = load_preferences(settings)
    if not preferences.inbox_dir:
        return None
    folder = Path(preferences.inbox_dir)
    if not folder.is_dir():
        return InboxResult(folder=folder, error=f"Folder skrzynki nie istnieje: {folder}")
    try:
        imported = import_xtb(folder, settings)
    except OSError as exc:  # e.g. a file locked by Excel
        return InboxResult(folder=folder, error=f"Nie udało się odczytać folderu skrzynki: {exc}")
    result = InboxResult(
        folder=folder, copied=imported.copied, already_imported=len(imported.unchanged), skipped=imported.skipped,
    )
    if imported.copied:
        result.sync = sync(settings)
    return result
