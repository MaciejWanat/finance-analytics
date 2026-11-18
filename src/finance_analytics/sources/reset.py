"""Reset the user's data and make a backup first (D-038).

Only paths inside the data directory are ever touched, and only the known kinds of
files. Preferences (settings.yaml) and the inbox folder are never removed. After a
reset the projection is rebuilt from whatever is left, so the database never shows
data whose source files are gone.
"""

from __future__ import annotations

import io
import zipfile
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from finance_analytics.config import Settings
from finance_analytics.db import connect, migrate
from finance_analytics.sources.bonds import bonds_file, series_overrides_file
from finance_analytics.sources.cash import cash_file
from finance_analytics.sources.sync import SyncResult, sync

MARKET_TABLES = (
    "prices", "corporate_actions", "ticker_info", "fx_rates", "cpi_monthly", "live_quotes", "intraday_quotes",
    "fetch_log",
)


@dataclass(frozen=True)
class ResetChoice:
    exports: bool = True  # data/raw: archived broker exports
    manual: bool = True  # data/manual: bonds.csv, cash_balances.csv
    accounts: bool = True  # data/config/accounts.yaml and bond_series.yaml
    market: bool = False  # cached prices, FX rates, CPI (public; can be downloaded again)


@dataclass
class ResetResult:
    removed: list[Path] = field(default_factory=list)
    market_cleared: bool = False
    sync: SyncResult | None = None


def _inside(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def files_for(settings: Settings, choice: ResetChoice) -> list[Path]:
    """Every existing file the choice would remove (for the preview and the backup)."""
    paths: list[Path] = []
    if choice.exports and settings.raw_dir.exists():
        paths += sorted(p for p in settings.raw_dir.rglob("*") if p.is_file())
    if choice.manual:
        paths += [p for p in (bonds_file(settings.manual_dir), cash_file(settings.manual_dir)) if p.exists()]
    if choice.accounts:
        paths += [p for p in (settings.accounts_file, series_overrides_file(settings.config_dir)) if p.exists()]
    return [p for p in paths if _inside(p, settings.data_dir)]


def backup_zip(settings: Settings) -> bytes:
    """A zip of everything the user maintains: exports, manual CSVs and configuration."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for folder in (settings.raw_dir, settings.manual_dir, settings.config_dir):
            if not folder.exists():
                continue
            for path in sorted(p for p in folder.rglob("*") if p.is_file()):
                archive.write(path, path.relative_to(settings.data_dir).as_posix())
    return buffer.getvalue()


def reset_data(settings: Settings, choice: ResetChoice) -> ResetResult:
    result = ResetResult()
    for path in files_for(settings, choice):
        path.unlink()
        result.removed.append(path)
    if choice.exports and settings.raw_dir.exists():
        for folder in sorted((p for p in settings.raw_dir.rglob("*") if p.is_dir()), reverse=True):
            if _inside(folder, settings.raw_dir) and not any(folder.iterdir()):
                folder.rmdir()
    if settings.db_path.exists():
        with closing(connect(settings.db_path)) as conn:
            migrate(conn)
            if choice.market:
                with conn:
                    for table in MARKET_TABLES:
                        conn.execute(f"DELETE FROM {table}")
                result.market_cleared = True
        result.sync = sync(settings, force=True)  # the projection follows the remaining files
    return result
