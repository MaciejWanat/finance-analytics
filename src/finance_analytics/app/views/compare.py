"""Porównanie: instruments, asset classes, the whole portfolio and the S&P 500 side by side (D-086). Every
portfolio series is a part of the portfolio measured like a portfolio of its own (D-085); "1D": every 5 minutes
(D-070)."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from ui.charts import HOVER_PLN, current_mode, line_chart, show
from ui.components import empty_state, page_header, section, table
from ui.data import (
    ONE_DAY,
    RANGES,
    load_benchmark,
    load_intraday,
    load_valuation,
    one_day,
    period_start,
    require_valued_data,
)
from ui.fmt import fmt_date
from ui.glossary import G
from ui.theme import ASSET_CLASS_LABELS, TOKENS

from finance_analytics import reports
from finance_analytics.config import get_settings
from finance_analytics.market.intraday import coverage
from finance_analytics.portfolio.compare import compare_parts, index_line, intraday_parts, intraday_twr
from finance_analytics.portfolio.slicing import Slice

PORTFOLIO, INDEX = "portfolio", "sp500"  # series keys; a class is "class:<asset_class>", an instrument "symbol:<s>"
RESERVED = {PORTFOLIO: 0, INDEX: 1}  # palette slots kept for the two references, as on Portfel
MAX_SERIES = 8  # the palette (D-086)
SERIES_KEY, COLORS_KEY = "compare_series", "compare_colors"  # kept in the session across pages
TWR, VALUE = "TWR", "Wartość w zł"

page_header("Porównanie", "Instrumenty, klasy aktywów i cały portfel obok siebie, na jednym wykresie.")
settings = get_settings()
require_valued_data(settings, "porównanie instrumentów i klas aktywów")
v, _ = load_valuation(settings)
total = v.total

# ------------------------------------------------------------------------------------------ the series offered
options = reports.filter_options(settings.db_path)
present = set(options["asset_class"])
classes = [c for c in ASSET_CLASS_LABELS if c in present] + sorted(present - set(ASSET_CLASS_LABELS))
names = dict(zip(options["symbol"], options["name"], strict=True))
labels = {PORTFOLIO: "Cały portfel", INDEX: "S&P 500"}
labels |= {f"class:{c}": f"{ASSET_CLASS_LABELS.get(c, c)} (klasa)" for c in classes}
labels |= {f"symbol:{s}": s if n == s else f"{s} · {n}" for s, n in names.items()}


def part_of(key: str) -> Slice:
    kind, _, value = key.partition(":")
    return Slice(classes=frozenset({value})) if kind == "class" else Slice(symbols=frozenset({value}))


if SERIES_KEY not in st.session_state:  # the first visit: the portfolio and every class held today
    held = v.daily[v.daily["date"] == v.daily["date"].max()]
    today_classes = [c for c in classes if c in set(held.loc[held["value_pln"] > 0, "asset_class"])]
    st.session_state[SERIES_KEY] = [PORTFOLIO, *(f"class:{c}" for c in today_classes)][:MAX_SERIES]
chosen = [key for key in st.session_state[SERIES_KEY] if key in labels]
st.session_state[f"_{SERIES_KEY}"] = chosen


def keep_series() -> None:
    """Copy the widget's value: Streamlit forgets the state of a widget on a page that does not draw it."""
    st.session_state[SERIES_KEY] = list(st.session_state[f"_{SERIES_KEY}"])


def colours(keys: list[str], mode) -> dict[str, str]:
    """Key -> palette colour. A series keeps its slot from when it was added until it is removed, so adding or
    removing one never repaints another; the portfolio and the S&P 500 prefer slots 1 and 2 (D-086)."""
    slots = {k: s for k, s in st.session_state.get(COLORS_KEY, {}).items() if k in keys}
    for key in keys:
        if key in slots:
            continue
        taken = set(slots.values())
        preferred = [RESERVED[key]] if key in RESERVED else []
        free = [s for s in (*preferred, *range(2, MAX_SERIES), 0, 1) if s not in taken]
        slots[key] = free[0]
    st.session_state[COLORS_KEY] = slots
    palette = TOKENS[mode].series
    return {key: palette[slot] for key, slot in slots.items()}


# ---------------------------------------------------------------------------------------------- page filter
period = st.segmented_control("Okres", RANGES, default="1R", key="compare_period", required=True,
                              help=G["periods"])
end = total.index[-1]
DAY = one_day(settings, v) if period == ONE_DAY else None
start = period_start(period, total.index[0], end, day_base=DAY.base if DAY else None)

left, right = st.columns([3, 1], vertical_alignment="bottom")
with left:
    st.multiselect("Linie na wykresie", list(labels), key=f"_{SERIES_KEY}", on_change=keep_series,
                   format_func=labels.get, max_selections=MAX_SERIES, help=G["compare_series"],
                   placeholder="Wybierz instrumenty lub klasy aktywów")
with right:
    unit = st.segmented_control("Miara", [TWR, VALUE], default=TWR, key="compare_unit", required=True,
                                help=G["compare_unit"])
chosen = st.session_state[f"_{SERIES_KEY}"]
if not chosen:
    empty_state("Wybierz, co porównać",
                "Dodaj w polu wyżej instrumenty, klasy aktywów, cały portfel albo S&P 500. Każda linia pokaże, ile "
                "zarobiło to, co z tej części faktycznie miałeś.", icon=":material/stacked_line_chart:")
    st.stop()

mode = current_mode()
colors = colours(chosen, mode)
parts = {key: (Slice() if key == PORTFOLIO else part_of(key)) for key in chosen if key != INDEX}
lines = compare_parts(v, parts, start, end)
if INDEX in chosen:
    index = index_line(load_benchmark(settings, total.index), start, end)
    if index is not None:
        lines[INDEX] = index
order = [key for key in chosen if key in lines]

# ---------------------------------------------------------------------------------------------- main chart
intra = load_intraday(settings, v, DAY) if DAY is not None else None
if intra is not None:
    section("Porównanie w czasie",
            f"{fmt_date(DAY.day)} co 5 minut, względem zamknięcia {fmt_date(DAY.base)}. S&P 500 nie ma notowań w "
            "ciągu dnia, więc jest tylko w tabeli.", help=G["compare_gaps"])
    if coverage(settings.db_path, DAY.start, DAY.end) is None:
        st.info("Brak notowań z tego dnia, więc linie są płaskie. W trybie online pobierają się same; offline "
                "pobierzesz je na stronie Portfel przy okresie 1D.", icon=":material/schedule:")
    day_parts = {key: parts[key] for key in order if key in parts}
    values = intraday_parts(intra.rows, day_parts)
    if unit == TWR:
        bases = {key: float(lines[key].value.iloc[0]) for key in day_parts}
        frame = intraday_twr(values, bases)
    else:
        frame = values
    frame = frame.rename(columns=labels)
    shown = {labels[key]: colors[key] for key in day_parts}
    show(line_chart(frame, mode=mode, colors=shown, height=380,
                    hover="%{y:.2%}" if unit == TWR else HOVER_PLN,
                    y_tickformat=".1%" if unit == TWR else ",.0f", until=DAY.until), key="compare")
else:
    section("Porównanie w czasie",
            f"{'Skumulowany TWR' if unit == TWR else 'Wartość w zł'}, od {fmt_date(start)} do {fmt_date(end)}."
            + (" 0% oznacza wynik zerowy." if unit == TWR else ""), help=G["compare_gaps"])
    drawn = [key for key in order if unit == TWR or key != INDEX]
    frame = pd.DataFrame({labels[key]: (lines[key].twr if unit == TWR else lines[key].value) for key in drawn})
    shown = {labels[key]: colors[key] for key in drawn}
    show(line_chart(frame, mode=mode, colors=shown, height=380,
                    hover="%{y:.1%}" if unit == TWR else HOVER_PLN,
                    y_tickformat=".0%" if unit == TWR else ",.0f"), key="compare")
if INDEX in chosen and INDEX not in lines:
    st.caption("Brak notowań S&P 500 w tym okresie; pobierzesz je na stronie Dane rynkowe.")

# ------------------------------------------------------------------------------------------------ the table
section("W okresie", "Każda linia liczona z własnymi zakupami i sprzedażami, w PLN.")
rows = pd.DataFrame([
    {"name": labels[key], "twr": lines[key].total_twr, "result": lines[key].result,
     "max_dd": lines[key].max_drawdown, "value": lines[key].end_value}
    for key in order
])
table(
    rows,
    numbers={"result": 2, "value": 2},
    percents=["twr", "max_dd"],
    signed=["twr", "result", "max_dd"],
    labels={"name": "Linia", "twr": "TWR", "result": "Wynik (zł)", "max_dd": "Maks. spadek",
            "value": "Wartość na koniec (zł)"},
    helps={"twr": G["twr"], "result": G["compare_result"], "max_dd": G["drawdown"]},
    missing_labels={"twr": "brak pozycji w okresie"},
    marks=[colors[key] for key in order],
    height="content",
)
