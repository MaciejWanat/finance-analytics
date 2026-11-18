"""Chart builders. Pages create charts only through these functions (D-012).

Form choices follow the data's job:
- one series over time (total value)      -> area_total: 2px line + 10% wash
- several series over time (comparison)   -> line_chart
- composition over time (value per part)  -> stacked_bars (e.g. monthly)
- one series during one day (the 1D range) -> intraday_chart: line, wash, dashed previous close (D-070)
Part-to-whole at a glance is a segmented bar, not a donut (added with the
allocation view).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

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


def _time_axis(fig: go.Figure) -> None:
    """Hours instead of dates, for charts within one day (1D, D-070)."""
    fig.layout.xaxis.tickformatstops = ()  # update_xaxes(tickformatstops=[]) would keep the date stops of _base
    fig.update_xaxes(tickformat="%H:%M", hoverformat="%H:%M")


def is_intraday(index: pd.Index) -> bool:
    """Moments within a day carry a time zone; daily dates do not."""
    return isinstance(index, pd.DatetimeIndex) and index.tz is not None


def current_mode() -> Mode:
    """Light or dark, following the theme the viewer picked in Streamlit."""
    return "dark" if st.context.theme.type == "dark" else "light"


def _rgba(hex_color: str, alpha: float) -> str:
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{alpha})"


def _base(mode: Mode, height: int) -> go.Figure:
    tokens = TOKENS[mode]
    # A constant uirevision keeps the viewer's zoom and pan when a live fragment redraws the chart (D-069).
    fig = go.Figure(layout={"template": template(mode), "height": height, "uirevision": "keep"})
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
    until: datetime | None = None,
) -> go.Figure:
    """Several series over time. Index: dates, or moments within one day (hours on the axis, up to `until`);
    one column per series, in a stable order."""
    colors = colors or color_map(list(df.columns), mode)
    fig = _base(mode, height)
    if is_intraday(df.index):
        _time_axis(fig)
        if until is not None and len(df):
            fig.update_xaxes(range=[df.index[0], until])
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
    """Composition over time. Index: periods (or hours within one day); one column per part, in a stable order.

    Segments are separated by a thin line in the surface colour (the "surface gap"),
    and the top of each stack has 4px rounded corners.
    """
    tokens = TOKENS[mode]
    colors = colors or color_map(list(df.columns), mode)
    fig = _base(mode, height)
    if is_intraday(df.index):
        _time_axis(fig)
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


def intraday_chart(
    series: pd.Series, *, baseline: float | None, baseline_label: str, until: datetime, mode: Mode,
    height: int = 340,
) -> go.Figure:
    """One series during one day, the 1D range (D-070): a 2px line with a 10% wash down to the lowest point (a
    day's moves would vanish on an axis from zero), a dashed line at the previous close (a real threshold, named
    in ink), hours on the axis up to `until`, so the line grows to the right while the day lasts. The hover adds
    the change since that close."""
    tokens = TOKENS[mode]
    color = tokens.series[0]
    fig = _base(mode, height)
    _time_axis(fig)
    values = series.astype(float)
    low, high = float(values.min()), float(values.max())
    if baseline is not None:
        low, high = min(low, baseline), max(high, baseline)
    pad = (high - low) * 0.12 or abs(high) * 0.002 or 1.0
    floor = low - pad
    fig.add_trace(go.Scatter(x=series.index, y=[floor] * len(series), mode="lines", line={"width": 0},
                             hoverinfo="skip", showlegend=False))
    change = (values / baseline - 1).to_numpy() if baseline else [0.0] * len(values)
    fig.add_trace(go.Scatter(
        x=series.index, y=values, name="Portfel", mode="lines", line={"color": color, "width": 2},
        fill="tonexty", fillcolor=_rgba(color, 0.10), customdata=change,
        hovertemplate=f"{HOVER_PLN} · %{{customdata:+.2%}}<extra></extra>" if baseline else
        f"{HOVER_PLN}<extra></extra>",
    ))
    if baseline is not None:
        fig.add_hline(y=baseline, line={"color": tokens.ink_muted, "width": 1, "dash": "dash"},
                      annotation={"text": baseline_label, "font": {"color": tokens.ink_secondary, "size": 12}},
                      annotation_position="top left")
    fig.update_xaxes(range=[series.index[0], until])
    fig.update_yaxes(range=[floor, high + pad])
    fig.update_layout(showlegend=False)
    return fig


def drawdown_chart(series: pd.Series, *, mode: Mode, height: int = 220) -> go.Figure:
    """Underwater chart: how far below its previous peak the series is (values <= 0)."""
    color = TOKENS[mode].bad
    fig = _base(mode, height)
    if is_intraday(series.index):
        _time_axis(fig)
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


def category_bars(
    values: pd.Series,
    *,
    mode: Mode,
    colors: dict[str, str] | None = None,
    height: int = 320,
    hover_unit: str = "zł",
) -> go.Figure:
    """Value per part today, one column each (e.g. cash per bank account), with its share.

    Index: part names; values > 0. The column's colour follows the part, never its
    rank; the share of the whole is printed above the column and in the tooltip.
    No legend: the x-axis names every column.
    """
    values = values[values > 0]
    colors = colors or color_map(sorted(str(k) for k in values.index), mode)
    total = float(values.sum()) or 1.0
    shares = values / total
    names = [str(k) for k in values.index]
    fig = go.Figure(layout={"template": template(mode), "height": height})
    fig.add_trace(
        go.Bar(
            x=names, y=values.values, name="",
            marker={"color": [colors[n] for n in names]},
            text=[fmt_pct(s, 0, signed=False) for s in shares], textposition="outside", cliponaxis=False,
            textfont={"color": TOKENS[mode].ink_primary, "size": 13},
            customdata=(shares * 100).to_numpy(),
            hovertemplate=f"<b>%{{y:,.2f}} {hover_unit}</b> · %{{customdata:.1f}}%<extra>%{{x}}</extra>",
        )
    )
    fig.update_yaxes(tickformat=",.0f", rangemode="tozero")
    fig.update_xaxes(type="category", showgrid=False)
    fig.update_layout(showlegend=False, bargap=0.45, barcornerradius=4, hovermode="closest",
                      margin={"t": 30})
    return fig


SPARK_HOVER = {"money": "%{y:,.2f} zł", "pct": "%{y:+.1%}"}


def sparkline(values: Sequence[float], *, color: str, kind: str = "money", mode: Mode, height: int = 56,
              water: bool = False) -> go.Figure:
    """KPI tile sparkline: area down to the lowest point, Polish number format in the hover (12 345,67 zł).

    `water=True` fills from the zero line instead: red below it (under water), green above it.
    """
    tokens = TOKENS[mode]
    y = [float(v) for v in values]
    fig = go.Figure(layout={"template": template(mode), "height": height})
    x = list(range(len(y)))
    if water:
        for part, fill in (([min(v, 0.0) for v in y], tokens.bad), ([max(v, 0.0) for v in y], tokens.good)):
            if any(part):
                fig.add_trace(go.Scatter(x=x, y=part, mode="lines", fill="tozeroy", fillcolor=_rgba(fill, 0.30),
                                         line={"width": 0}, hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(
            x=x, y=y, mode="lines", line={"color": tokens.ink_secondary, "width": 1.5},
            hovertemplate=f"{SPARK_HOVER[kind]}<extra></extra>", showlegend=False,
        ))
        fig.add_hline(y=0, line={"color": tokens.baseline, "width": 1})
    else:
        floor = min(y)
        fig.add_trace(go.Scatter(x=x, y=[floor] * len(y), mode="lines", line={"width": 0}, hoverinfo="skip",
                                 showlegend=False))
        fig.add_trace(go.Scatter(
            x=x, y=y, mode="lines", fill="tonexty", fillcolor=_rgba(color, 0.18), line={"color": color, "width": 2},
            hovertemplate=f"{SPARK_HOVER[kind]}<extra></extra>", showlegend=False,
        ))
    fig.update_layout(
        margin={"l": 0, "r": 0, "t": 4, "b": 0}, hovermode="x", showlegend=False,
        hoverlabel={"bgcolor": tokens.surface, "bordercolor": tokens.gridline},
    )
    # The axis stays "visible" but bare: Plotly draws the hover line (spike) only on a visible axis.
    fig.update_xaxes(
        visible=True, showticklabels=False, showgrid=False, zeroline=False, showline=False, ticks="",
        fixedrange=True, showspikes=True, spikemode="across", spikesnap="data", spikethickness=1,
        spikedash="solid", spikecolor=tokens.ink_muted,
    )
    fig.update_yaxes(visible=False, fixedrange=True)
    return fig


DETAIL_HOVER = {"money": "%{y:,.2f} zł", "pct": "%{y:+.2%}"}
# Range buttons of the full chart; "Okres" = the window picked on the page.
_RANGE_BUTTONS = [
    {"count": 1, "label": "1M", "step": "month", "stepmode": "backward"},
    {"count": 6, "label": "6M", "step": "month", "stepmode": "backward"},
    {"count": 1, "label": "YTD", "step": "year", "stepmode": "todate"},
    {"count": 1, "label": "1R", "step": "year", "stepmode": "backward"},
    {"count": 3, "label": "3L", "step": "year", "stepmode": "backward"},
    {"label": "Maks.", "step": "all"},
]
DETAIL_CONFIG = {**PLOTLY_CONFIG, "scrollZoom": True, "displayModeBar": True}


def detail_chart(
    series: pd.Series, *, name: str, mode: Mode, kind: str = "money", start: pd.Timestamp | None = None,
    height: int = 520,
) -> go.Figure:
    """Full history of one KPI for the enlarged view: zoom with the wheel or a box, a range slider
    below and range buttons above. Opens on `start` (the page's period) when given. A series within one day
    (1D, D-070) gets hours on the axis and no slider or range buttons."""
    tokens = TOKENS[mode]
    color = tokens.series[0]
    fig = _base(mode, height)
    fig.add_trace(go.Scatter(
        x=series.index, y=series.values, name=name, mode="lines", line={"color": color, "width": 2},
        fill="tozeroy", fillcolor=_rgba(color, 0.10), hovertemplate=f"{DETAIL_HOVER[kind]}<extra></extra>",
    ))
    fig.update_layout(showlegend=False, hovermode="x", dragmode="zoom", margin={"t": 48})
    if is_intraday(series.index):
        # A day's moves would vanish on an axis from zero: the line alone, on an axis that fits it.
        _time_axis(fig)
        fig.update_traces(fill="none")
        fig.update_yaxes(tickformat=",.1%" if kind == "pct" else ",.0f", fixedrange=False, rangemode="normal")
        return fig
    fig.update_xaxes(
        rangeslider={"visible": True, "thickness": 0.08, "bgcolor": tokens.surface, "bordercolor": tokens.gridline},
        rangeselector={
            "buttons": _RANGE_BUTTONS, "x": 0, "y": 1.08, "bgcolor": tokens.surface, "activecolor": tokens.gridline,
            "bordercolor": tokens.gridline, "borderwidth": 1, "font": {"color": tokens.ink_secondary, "size": 12},
        },
    )
    if start is not None and len(series) and start > series.index[0]:
        fig.update_xaxes(range=[start, series.index[-1]])
    fig.update_yaxes(tickformat=",.0%" if kind == "pct" else ",.0f", fixedrange=False)
    return fig


def show_detail(fig: go.Figure, *, key: str) -> None:
    st.plotly_chart(fig, theme=None, config=DETAIL_CONFIG, key=key)


def show_spark(fig: go.Figure, *, key: str) -> None:
    st.plotly_chart(fig, theme=None, config={"displayModeBar": False}, key=key)


def show(fig: go.Figure, *, key: str | None = None) -> None:
    """Render with our own template (theme=None) and the trimmed modebar."""
    st.plotly_chart(fig, theme=None, config=PLOTLY_CONFIG, key=key)
