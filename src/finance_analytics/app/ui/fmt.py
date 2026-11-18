"""Polish number, money and date formatting for the UI.

Polish conventions: decimal comma, space as the thousands separator, currency after
the amount ("12 345,67 zł"). A non-breaking space keeps numbers on one line and a
real minus sign (U+2212) matches what Plotly renders on axes.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, tzinfo

NBSP = " "
MINUS = "−"
CURRENCY_SUFFIX = {"PLN": "zł"}


def _is_missing(value: float | None) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def fmt_number(value: float | None, decimals: int = 0, signed: bool = False) -> str:
    """12345.678 -> '12 345,68' (decimals=2)."""
    if _is_missing(value):
        return "–"
    text = f"{abs(value):,.{decimals}f}".replace(",", NBSP).replace(".", ",")
    if value < 0 and text.strip("0, "):
        return MINUS + text
    if signed and value > 0:
        return "+" + text
    return text


def fmt_money(value: float | None, currency: str = "PLN", decimals: int = 2, signed: bool = False) -> str:
    """12345.6 -> '12 345,60 zł'; other currencies keep their ISO code: '99,00 USD'."""
    if _is_missing(value):
        return "–"
    return f"{fmt_number(value, decimals, signed)}{NBSP}{CURRENCY_SUFFIX.get(currency, currency)}"


def fmt_money_compact(value: float | None, currency: str = "PLN") -> str:
    """Short form for tiles: 1 284 zł, 12,9 tys. zł, 4,2 mln zł."""
    if _is_missing(value):
        return "–"
    suffix = CURRENCY_SUFFIX.get(currency, currency)
    magnitude = abs(value)
    if magnitude >= 1_000_000:
        return f"{fmt_number(value / 1_000_000, 2)}{NBSP}mln{NBSP}{suffix}"
    if magnitude >= 100_000:
        return f"{fmt_number(value / 1_000, 1)}{NBSP}tys.{NBSP}{suffix}"
    return f"{fmt_number(value, 0)}{NBSP}{suffix}"


def fmt_pct(value: float | None, decimals: int = 1, signed: bool = True) -> str:
    """0.034 -> '+3,4%'. Input is a fraction, not percentage points."""
    if _is_missing(value):
        return "–"
    return f"{fmt_number(value * 100, decimals, signed)}%"


def fmt_date(value: date | datetime | None) -> str:
    """date(2026, 11, 16) -> '16.11.2026'."""
    if value is None:
        return "–"
    return value.strftime("%d.%m.%Y")


def plural(count: int, one: str, few: str, many: str) -> str:
    """Polish plural: 1 wypłata, 2-4 wypłaty (also 22-24, 32-34...), 5+ wypłat; with the number."""
    if count == 1:
        word = one
    elif count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        word = few
    else:
        word = many
    return f"{count}{NBSP}{word}"


WEEKDAYS = ("pon.", "wt.", "śr.", "czw.", "pt.", "sob.", "niedz.")


def fmt_duration(delta: timedelta) -> str:
    """timedelta(hours=2, minutes=5) -> '2 h 05 min', '45 min'; a day or more -> '2 d 09 h'. Two-digit parts keep
    a column of durations aligned; rounded up to a whole minute, so never '0 min'."""
    days, minutes = divmod(max(1, math.ceil(delta.total_seconds() / 60)), 24 * 60)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days}{NBSP}d {hours:02d}{NBSP}h"
    return f"{hours}{NBSP}h {minutes:02d}{NBSP}min" if hours else f"{minutes}{NBSP}min"


def fmt_when(moment: datetime, now: datetime, tz: tzinfo | None = None) -> str:
    """A moment relative to now, in local time (or `tz`): 'dziś 15:30', 'jutro 15:30', 'pon. 15:30', '24.12 15:30'."""
    moment, now = moment.astimezone(tz), now.astimezone(tz)
    days = (moment.date() - now.date()).days
    if days in (0, 1):
        day = ("dziś", "jutro")[days]
    else:
        day = WEEKDAYS[moment.weekday()] if 1 < days < 7 else f"{moment:%d.%m}"
    return f"{day} {moment:%H:%M}"


PHASES = {"open": "Otwarta", "closed": "Zamknięta", "pre": "Pre-market", "post": "Post-market"}


def market_text(status, now: datetime, tz: tzinfo | None = None) -> tuple[str, str, str]:
    """(label, time, hover) for one exchange in the sidebar list (D-068); `status` is a `market.hours.MarketStatus`.

    The label and the time count to the regular open, or to the regular close while the exchange is open;
    pre-market and post-market show only in the lamp and the hover, which also gives the exact local (or `tz`)
    moments: "Zamknięta · pre-market dziś 10:00 · otwarcie dziś 15:30".
    """
    if status.phase == "open":
        moment = status.next_change
        return "do zamknięcia", fmt_duration(moment - now), f"Otwarta · zamknięcie {fmt_when(moment, now, tz)}"
    hover = PHASES[status.phase]
    if status.phase == "post":
        hover += f" do {status.next_change.astimezone(tz):%H:%M}"
    elif status.next_phase == "pre":
        hover += f" · pre-market {fmt_when(status.next_change, now, tz)}"
    hover += f" · otwarcie {fmt_when(status.next_open, now, tz)}"
    return "do otwarcia", fmt_duration(status.next_open - now), hover


def interval_text(seconds: int) -> str:
    """A refresh interval: '5 s', '30 s', '1 min', '15 min', '1 h'."""
    if seconds < 60 or seconds % 60:
        return f"{seconds} s"
    if seconds % 3600 == 0:
        return f"{seconds // 3600} h"
    return f"{seconds // 60} min"
