"""Page building blocks: header, KPI tiles, empty state (D-012)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import pandas as pd
import streamlit as st

from ui.charts import current_mode
from ui.fmt import MINUS, fmt_number, fmt_pct
from ui.theme import TOKENS


@dataclass(frozen=True)
class Kpi:
    label: str  # sentence case, no trailing colon
    value: str  # already formatted, e.g. fmt_money_compact(...)
    delta: str | None = None  # signed, e.g. "+3,4%"; say vs what in `help`
    delta_color: Literal["normal", "inverse", "off"] = "normal"
    help: str | None = None
    trend: Sequence[float] | None = None  # sparkline, e.g. last 12 months


_CSS = """
<style>
/* KPI tiles: values like "205,4 tys. zł" must fit four tiles in a row. */
[data-testid="stMetricValue"] { font-size: 1.7rem; font-weight: 600; }
[data-testid="stMetricLabel"] p { font-size: 0.85rem; }
</style>
"""


def apply_global_styles() -> None:
    """Small CSS refinements on top of the Streamlit theme. Call once per run (main.py)."""
    st.html(_CSS)


def page_header(title: str, caption: str | None = None) -> None:
    st.title(title)
    if caption:
        st.caption(caption)


def section(title: str, caption: str | None = None) -> None:
    st.subheader(title)
    if caption:
        st.caption(caption)


def kpi_row(kpis: Sequence[Kpi]) -> None:
    for column, kpi in zip(st.columns(len(kpis)), kpis, strict=True):
        # Streamlit reads the delta's direction from a leading ASCII "-".
        delta = kpi.delta.replace(MINUS, "-") if kpi.delta else None
        column.metric(
            kpi.label,
            kpi.value,
            delta,
            delta_color=kpi.delta_color,
            help=kpi.help,
            border=True,
            chart_data=list(kpi.trend) if kpi.trend else None,
            chart_type="area",
            height="stretch",  # equal heights across the row
        )


def table(
    df: pd.DataFrame,
    *,
    numbers: dict[str, int] | None = None,
    signed: Sequence[str] = (),
    datetimes: Sequence[str] = (),
    percents: Sequence[str] = (),
    trends: Sequence[str] = (),
    labels: dict[str, str] | None = None,
) -> None:
    """A dataframe with Polish number formatting that still sorts numerically.

    numbers: column -> decimals; signed: columns coloured green/red by sign;
    datetimes: columns shown as YYYY-MM-DD HH:MM; percents: fractions shown as +3,4%;
    trends: columns holding lists of numbers, drawn as sparklines;
    labels: column -> header text. Empty cells show as "–" instead of None/NaN.
    """
    tokens = TOKENS[current_mode()]
    labels = labels or {}
    # Rename instead of column_config labels: Streamlit drops Styler display values
    # for columns that have a column_config entry.
    df = df.rename(columns=labels)
    # Streamlit paints empty text cells as a grey "None"; show a dash instead.
    text_columns = df.select_dtypes(include=["object", "string"]).columns
    df[text_columns] = df[text_columns].astype(object).where(df[text_columns].notna(), "–")
    numbers = {labels.get(col, col): d for col, d in (numbers or {}).items()}
    signed = [labels.get(col, col) for col in signed]
    datetimes = [labels.get(col, col) for col in datetimes]
    percents = [labels.get(col, col) for col in percents]
    trends = [labels.get(col, col) for col in trends]
    # One format() call: each call with a dict resets every column it does not name.
    formatters: dict[str, object] = {col: (lambda v, d=d: fmt_number(v, d)) for col, d in numbers.items()}
    formatters |= {col: (lambda v: v.strftime("%Y-%m-%d %H:%M")) for col in datetimes}
    formatters |= {col: (lambda v, sg=col in signed: fmt_pct(v, 1, signed=sg)) for col in percents}
    formatters |= {col: (lambda v: str(v)) for col in df.columns if col not in formatters and col not in trends}
    styler = df.style.format(formatters, na_rep="–")

    def sign_color(value: object) -> str:
        if isinstance(value, (int, float)) and value == value and value:
            return f"color: {tokens.good if value > 0 else tokens.bad}"
        return ""

    if signed:
        styler = styler.map(sign_color, subset=list(signed))
    # Sparkline columns are the one place column_config is used (it overrides the Styler there).
    config = {col: st.column_config.LineChartColumn(col, width="small") for col in trends}
    st.dataframe(styler, hide_index=True, width="stretch", column_config=config)


def empty_state(title: str, body: str, *, icon: str = ":material/inbox:", steps: Sequence[str] = ()) -> None:
    with st.container(border=True):
        st.markdown(f"#### {icon} {title}")
        st.markdown(body)
        if steps:
            st.markdown("\n".join(f"{i}. {step}" for i, step in enumerate(steps, start=1)))
