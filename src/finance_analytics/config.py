"""Filesystem layout of the local data directory.

Everything private lives under one data directory (default ``./data``, override with
the ``FA_DATA_DIR`` environment variable). It is git-ignored; see D-002 and D-014 in
docs/decisions.md.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DATA_DIR_ENV = "FA_DATA_DIR"
DB_FILENAME = "finance.db"


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
        """YAML configuration (accounts, instrument overrides)."""
        return self.data_dir / "config"

    @property
    def samples_dir(self) -> Path:
        """Local, masked inspector reports."""
        return self.data_dir / "samples"

    @property
    def accounts_file(self) -> Path:
        return self.config_dir / "accounts.yaml"

    def all_dirs(self) -> list[Path]:
        return [self.data_dir, self.raw_dir, self.manual_dir, self.config_dir, self.samples_dir]


def get_settings() -> Settings:
    """Read settings from the environment on every call, so tests can override them."""
    return Settings(data_dir=Path(os.environ.get(DATA_DIR_ENV, "data")).resolve())
