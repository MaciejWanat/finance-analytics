"""User preferences in data/config/settings.yaml (D-021).

The network mode lives here: "offline" (default, no network calls at all) or "online"
(public market data is fetched and kept live).
"""

from __future__ import annotations

from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from finance_analytics.config import Settings

HEADER = """\
# finance-analytics preferences. Private: data/ is git-ignored.
# network: offline (default) - the app makes no network calls and uses cached data only.
#          online - prices and FX rates are fetched from Yahoo and NBP and kept up to date, and the
#          public CPI file from GUS once a day. Only tickers, currency codes and dates are sent;
#          nothing about your accounts.
# live_source: how live prices arrive in online mode (D-069). poll (default) - the app asks Yahoo every
#              poll_seconds; stream - one open connection, Yahoo pushes every new price.
# poll_seconds: how often prices are polled, 120-3600 (not more often than every 2 minutes, so Yahoo
#               does not refuse). Older files with refresh_minutes are read and converted.
# stream_seconds: with the stream, how often Portfel redraws with the new prices, 5-60.
# inbox_dir: folder where xStation exports are saved; new ones are imported automatically
#            (read only, D-028). Empty = off.
# today_tile: how the "Dzisiaj" tile on Portfel counts a day (D-067). calendar_day (default) - from
#             midnight; us_session - from one US session to the next: it starts at the open and keeps
#             the result after the close. us_session applies only to a portfolio with US instruments.
"""


POLL_SECONDS = (120, 3600)  # polling more often than every 2 minutes risks Yahoo refusing (D-069)
STREAM_SECONDS = (5, 60)  # with the stream: how often Portfel redraws
POLL_REDRAW_SECONDS = 30


class Preferences(BaseModel):
    model_config = ConfigDict(extra="ignore")

    network: Literal["offline", "online"] = "offline"
    live_source: Literal["poll", "stream"] = "poll"
    poll_seconds: int = Field(default=300, ge=POLL_SECONDS[0], le=POLL_SECONDS[1])
    stream_seconds: int = Field(default=5, ge=STREAM_SECONDS[0], le=STREAM_SECONDS[1])
    inbox_dir: str | None = None
    today_tile: Literal["calendar_day", "us_session"] = "calendar_day"

    @model_validator(mode="before")
    @classmethod
    def _older_interval(cls, data: object) -> object:
        """Settings saved before D-069 hold `refresh_minutes` (or, briefly, `refresh_seconds`): keep the user's
        polling interval, raised to the 2-minute minimum."""
        if isinstance(data, dict) and "poll_seconds" not in data:
            seconds = data.get("refresh_seconds")
            minutes = data.get("refresh_minutes")
            if seconds is None and isinstance(minutes, int | float) and not isinstance(minutes, bool):
                seconds = minutes * 60
            if isinstance(seconds, int | float) and not isinstance(seconds, bool) and seconds > 0:
                data = {**data, "poll_seconds": min(max(int(seconds), POLL_SECONDS[0]), POLL_SECONDS[1])}
        return data

    @property
    def online(self) -> bool:
        return self.network == "online"

    @property
    def streaming(self) -> bool:
        return self.online and self.live_source == "stream"

    @property
    def redraw_seconds(self) -> int:
        """How often live pages redraw: the stream's setting, or every 30 s while polling, so a new poll shows
        within half a minute whenever it lands."""
        return self.stream_seconds if self.live_source == "stream" else POLL_REDRAW_SECONDS


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
