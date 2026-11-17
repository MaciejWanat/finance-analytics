"""Where the app lives and the filesystem layout of the local data directory.

Everything private lives under one data directory (D-002, D-014):
- ``FA_DATA_DIR`` when set;
- ``data/`` in the repository when running from a source checkout (git-ignored);
- otherwise, for an installed package, a per-user folder that is never synced to a cloud
  drive (D-065): ``%LOCALAPPDATA%\\finance-analytics\\data`` on Windows,
  ``~/Library/Application Support/finance-analytics/data`` on macOS and
  ``~/.local/share/finance-analytics/data`` (or ``$XDG_DATA_HOME``) elsewhere.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

DATA_DIR_ENV = "FA_DATA_DIR"
DB_FILENAME = "finance.db"
APP_NAME = "finance-analytics"

PACKAGE_DIR = Path(__file__).resolve().parent
APP_DIR = PACKAGE_DIR / "app"  # the Streamlit UI and its .streamlit/config.toml, shipped inside the package
SOURCE_ROOT = PACKAGE_DIR.parents[1]  # the repository root when running from a checkout (src layout)


def is_source_checkout() -> bool:
    """True when the package runs from the repository (editable install), not from an installed wheel."""
    return PACKAGE_DIR.parent.name == "src" and (SOURCE_ROOT / "pyproject.toml").is_file()


def user_data_root() -> Path:
    """The per-user folder of an installed app. Deliberately not Documents, which is often synced to OneDrive."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        xdg = os.environ.get("XDG_DATA_HOME", "")
        base = Path(xdg) if os.path.isabs(xdg) else Path.home() / ".local" / "share"
    return base / APP_NAME


def default_data_dir() -> Path:
    return SOURCE_ROOT / "data" if is_source_checkout() else user_data_root() / "data"


def demo_data_dir() -> Path:
    """Synthetic data for `fa demo`; next to the real data directory, never inside it."""
    return SOURCE_ROOT / "data-demo" if is_source_checkout() else user_data_root() / "demo"


@dataclass(frozen=True)
class Settings:
    data_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / DB_FILENAME

    @property
    def raw_dir(self) -> Path:
        """Archived broker exports, e.g. raw/xtb/<account_no>/USD_....xlsx."""
        return self.data_dir / "raw"

    @property
    def manual_dir(self) -> Path:
        """Hand-maintained CSV files (cash balances, bonds)."""
        return self.data_dir / "manual"

    @property
    def config_dir(self) -> Path:
        """YAML configuration (accounts, preferences, bond series overrides)."""
        return self.data_dir / "config"

    @property
    def samples_dir(self) -> Path:
        """Local, masked inspector reports."""
        return self.data_dir / "samples"

    @property
    def accounts_file(self) -> Path:
        return self.config_dir / "accounts.yaml"

    @property
    def preferences_file(self) -> Path:
        """Network mode and refresh interval (D-021)."""
        return self.config_dir / "settings.yaml"

    def all_dirs(self) -> list[Path]:
        return [self.data_dir, self.raw_dir, self.manual_dir, self.config_dir, self.samples_dir]


def get_settings() -> Settings:
    """Read settings from the environment on every call, so tests can override them."""
    override = os.environ.get(DATA_DIR_ENV)
    return Settings(data_dir=Path(override).resolve() if override else default_data_dir())
