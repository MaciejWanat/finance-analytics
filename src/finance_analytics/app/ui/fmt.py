"""Polish number, money and date formatting for the UI.

Polish conventions: decimal comma, space as the thousands separator, currency after
the amount ("12 345,67 zł"). A non-breaking space keeps numbers on one line and a
real minus sign (U+2212) matches what Plotly renders on axes.
"""

from __future__ import annotations

import math
from datetime import date, datetime

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
