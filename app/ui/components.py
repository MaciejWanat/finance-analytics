"""Page building blocks: header, KPI tiles, empty state (D-012)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import streamlit as st

from ui.fmt import MINUS


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
        )


def empty_state(title: str, body: str, *, icon: str = ":material/inbox:", steps: Sequence[str] = ()) -> None:
    with st.container(border=True):
        st.markdown(f"#### {icon} {title}")
        st.markdown(body)
        if steps:
            st.markdown("\n".join(f"{i}. {step}" for i, step in enumerate(steps, start=1)))
