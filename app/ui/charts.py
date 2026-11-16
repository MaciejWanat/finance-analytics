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

from ui.fmt import fmt_pct
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


def drawdown_chart(series: pd.Series, *, mode: Mode, height: int = 220) -> go.Figure:
    """Underwater chart: how far below its previous peak the series is (values <= 0)."""
    color = TOKENS[mode].bad
    fig = _base(mode, height)
    fig.add_trace(
        go.Scatter(
            x=series.index, y=series.values, name="Spadek od szczytu", mode="lines",
            line={"color": color, "width": 2}, fill="tozeroy", fillcolor=_rgba(color, 0.10),
            hovertemplate="%{y:.1%}<extra></extra>",
        )
    )
    fig.update_yaxes(tickformat=".0%", rangemode="tozero")
    fig.update_layout(showlegend=False)
    return fig


MONTHS_PL = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"]
_DIVERGING = {  # red (loss) <- neutral grey -> blue (gain); validated diverging pair
    "light": ["#e34948", "#f0efec", "#2a78d6"],
    "dark": ["#e66767", "#383835", "#3987e5"],
}


def returns_heatmap(grid: pd.DataFrame, *, mode: Mode, cap: float = 0.08) -> go.Figure:
    """Monthly returns: rows = years, columns = months; diverging colour around 0.

    The scale is symmetric and capped at +/- `cap`, so one extreme month does not wash
    out the rest. Every cell prints its value; empty months stay blank.
    """
    tokens = TOKENS[mode]
    low, mid, high = _DIVERGING[mode]
    months = grid[list(range(1, 13))]
    text = [[fmt_pct(v, 1) if pd.notna(v) else "" for v in row] for row in months.to_numpy()]
    fig = go.Figure(layout={"template": template(mode), "height": 70 + 38 * len(months)})
    fig.add_trace(
        go.Heatmap(
            z=months.to_numpy(), x=MONTHS_PL, y=[str(y) for y in months.index],
            zmin=-cap, zmax=cap, zmid=0, colorscale=[[0, low], [0.5, mid], [1, high]], showscale=False,
            text=text, texttemplate="%{text}", textfont={"size": 12, "color": tokens.ink_primary},
            xgap=2, ygap=2, hovertemplate="%{x} %{y}: <b>%{text}</b><extra></extra>",
        )
    )
    fig.update_xaxes(side="top", showgrid=False, showline=False, tickformatstops=None)
    fig.update_yaxes(autorange="reversed", showgrid=False, type="category")
    fig.update_layout(hovermode="closest", margin={"l": 8, "r": 8, "t": 30, "b": 8})
    return fig


_DARK_TEXT_ON = {"#eda100", "#c98500"}  # yellow slots carry near-black labels


def segmented_bar(
    values: pd.Series,
    *,
    mode: Mode,
    colors: dict[str, str] | None = None,
    hover_unit: str = "zł",
) -> go.Figure:
    """One whole split into parts (allocation), as a single tall bar.

    Each part shows its share inside when it is wide enough; name, amount and share
    are in the legend and the tooltip.
    """
    tokens = TOKENS[mode]
    values = values[values > 0]
    colors = colors or color_map(list(values.index), mode)
    total = float(values.sum()) or 1.0
    fig = go.Figure(layout={"template": template(mode), "height": 110})
    for label, value in values.items():
        share = value / total
        color = colors[label]
        fig.add_trace(
            go.Bar(
                x=[value], y=[""], orientation="h", name=str(label),
                marker={"color": color, "line": {"color": tokens.surface, "width": 2}},
                text=[fmt_pct(share, 0, signed=False) if share >= 0.06 else ""],
                textposition="inside", insidetextanchor="start",
                textfont={"color": "#0b0b0b" if color in _DARK_TEXT_ON else "#ffffff", "size": 13},
                customdata=[[share * 100]],
                hovertemplate=f"<b>%{{x:,.0f}} {hover_unit}</b> · %{{customdata[0]:.1f}}%<extra>{label}</extra>",
            )
        )
    fig.update_layout(
        barmode="stack", barcornerradius=4, bargap=0, hovermode="closest",
        margin={"l": 0, "r": 0, "t": 30, "b": 0},
        xaxis={"visible": False, "range": [0, total]}, yaxis={"visible": False},
    )
    return fig


def show(fig: go.Figure, *, key: str | None = None) -> None:
    """Render with our own template (theme=None) and the trimmed modebar."""
    st.plotly_chart(fig, theme=None, config=PLOTLY_CONFIG, key=key)
