"""Chart builders. Pages create charts only through these functions (D-012).

Form choices follow the data's job:
- one series over time (total value)      -> area_total: 2px line + 10% wash
- several series over time (comparison)   -> line_chart
- composition over time (value per part)  -> stacked_bars (e.g. monthly)
Part-to-whole at a glance is a segmented bar, not a donut (added with the
allocation view).
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ui.theme import PLOTLY_CONFIG, TOKENS, Mode, color_map, template

HOVER_PLN = "%{y:,.2f} zł"

# Numeric date formats keep the axis Polish without loading a Plotly locale.
_DATE_TICK_STOPS = [
    {"dtickrange": [None, "M1"], "value": "%d.%m"},
    {"dtickrange": ["M1", "M12"], "value": "%m.%Y"},
    {"dtickrange": ["M12", None], "value": "%Y"},
]


def current_mode() -> Mode:
    """Light or dark, following the theme the viewer picked in Streamlit."""
    return "dark" if st.context.theme.type == "dark" else "light"


def _rgba(hex_color: str, alpha: float) -> str:
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{alpha})"


def _base(mode: Mode, height: int) -> go.Figure:
    tokens = TOKENS[mode]
    fig = go.Figure(layout={"template": template(mode), "height": height})
    fig.update_xaxes(
        tickformatstops=_DATE_TICK_STOPS,
        hoverformat="%d.%m.%Y",
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikethickness=1,
        spikedash="solid",
        spikecolor=tokens.baseline,
    )
    fig.update_yaxes(tickformat=",.0f")
    return fig


def area_total(series: pd.Series, *, name: str, mode: Mode, height: int = 360) -> go.Figure:
    """One series over time, e.g. total portfolio value. No legend: the title names it."""
    color = TOKENS[mode].series[0]
    fig = _base(mode, height)
    fig.add_trace(
        go.Scatter(
            x=series.index,
            y=series.values,
            name=name,
            mode="lines",
            line={"color": color, "width": 2},
            fill="tozeroy",
            fillcolor=_rgba(color, 0.10),
            hovertemplate=f"{HOVER_PLN}<extra></extra>",
        )
    )
    fig.update_layout(showlegend=False)
    return fig


def line_chart(
    df: pd.DataFrame,
    *,
    mode: Mode,
    colors: dict[str, str] | None = None,
    height: int = 360,
    hover: str = HOVER_PLN,
    y_tickformat: str = ",.0f",
) -> go.Figure:
    """Several series over time. Index: dates; one column per series, in a stable order."""
    colors = colors or color_map(list(df.columns), mode)
    fig = _base(mode, height)
    for column in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df[column],
                name=str(column),
                mode="lines",
                line={"color": colors[column], "width": 2},
                hovertemplate=hover,
            )
        )
    fig.update_yaxes(tickformat=y_tickformat)
    fig.update_layout(showlegend=len(df.columns) > 1)
    return fig


def stacked_bars(
    df: pd.DataFrame,
    *,
    mode: Mode,
    colors: dict[str, str] | None = None,
    height: int = 360,
    hover: str = HOVER_PLN,
) -> go.Figure:
    """Composition over time. Index: periods; one column per part, in a stable order.

    Segments are separated by a thin line in the surface colour (the "surface gap"),
    and the top of each stack has 4px rounded corners.
    """
    tokens = TOKENS[mode]
    colors = colors or color_map(list(df.columns), mode)
    fig = _base(mode, height)
    for column in df.columns:
        fig.add_trace(
            go.Bar(
                x=df.index,
                y=df[column],
                name=str(column),
                marker={"color": colors[column], "line": {"color": tokens.surface, "width": 1}},
                hovertemplate=hover,
            )
        )
    fig.update_xaxes(showspikes=False)
    fig.update_layout(barmode="stack", barcornerradius=4, showlegend=len(df.columns) > 1)
    return fig


def show(fig: go.Figure, *, key: str | None = None) -> None:
    """Render with our own template (theme=None) and the trimmed modebar."""
    st.plotly_chart(fig, theme=None, config=PLOTLY_CONFIG, key=key)
