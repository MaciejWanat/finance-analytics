"""User preferences in data/config/settings.yaml (D-021).

The network mode lives here: "offline" (default, no network calls at all) or "online"
(public market data is fetched and kept live).
"""

from __future__ import annotations

from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from finance_analytics.config import Settings

HEADER = """\
# finance-analytics preferences. Private: data/ is git-ignored.
# network: offline (default) - the app makes no network calls and uses cached data only.
#          online - prices and FX rates are fetched from Yahoo and NBP and kept up to date, and the
#          public CPI file from GUS once a day. Only tickers, currency codes and dates are sent;
#          nothing about your accounts.
# refresh_minutes: how often live prices are refreshed in online mode (1-60).
# inbox_dir: folder where xStation exports are saved; new ones are imported automatically
#            (read only, D-028). Empty = off.
"""


class Preferences(BaseModel):
    model_config = ConfigDict(extra="ignore")

    network: Literal["offline", "online"] = "offline"
    refresh_minutes: int = Field(default=5, ge=1, le=60)
    inbox_dir: str | None = None

    @property
    def online(self) -> bool:
        return self.network == "online"


class PreferencesError(ValueError):
    pass


def load_preferences(settings: Settings) -> Preferences:
    path = settings.preferences_file
    if not path.exists():
        return Preferences()
    try:
        return Preferences(**(yaml.safe_load(path.read_text(encoding="utf-8")) or {}))
    except (yaml.YAMLError, ValidationError, TypeError) as exc:
        raise PreferencesError(f"{path}: {exc}") from exc


def save_preferences(settings: Settings, preferences: Preferences) -> None:
    path = settings.preferences_file
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(preferences.model_dump(), sort_keys=False)
    path.write_text(HEADER + "\n" + body, encoding="utf-8")
