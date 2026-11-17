"""Chart look: palette, Plotly template and chart config (D-012).

The categorical palette is the validated reference palette: fixed slot order, light
and dark steps chosen separately, CVD-checked against the surfaces below. Light-mode
contrast is below 3:1 for three slots, so charts always ship a legend and pages a
table view.

Rules:
- colours follow the entity (an account, an instrument), never its rank; use color_map()
- never cycle the palette; past 8 series fold into "Inne" (other)
- text uses ink tokens, never a series colour
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import plotly.graph_objects as go

Mode = Literal["light", "dark"]

OTHER_LABEL = "Inne"
FONT_FAMILY = '"Source Sans Pro", "Source Sans 3", system-ui, -apple-system, "Segoe UI", sans-serif'


@dataclass(frozen=True)
class Tokens:
    surface: str
    ink_primary: str
    ink_secondary: str
    ink_muted: str
    gridline: str
    baseline: str
    border: str
    other: str  # the folded "Inne" series
    good: str  # positive change (text)
    bad: str  # negative change (text)
    series: tuple[str, ...]


TOKENS: dict[Mode, Tokens] = {
    "light": Tokens(
        surface="#fcfcfb",
        ink_primary="#0b0b0b",
        ink_secondary="#52514e",
        ink_muted="#898781",
        gridline="#e1e0d9",
        baseline="#c3c2b7",
        border="rgba(11,11,11,0.10)",
        other="#a8a69f",
        good="#006300",
        bad="#d03b3b",
        series=("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"),
    ),
    "dark": Tokens(
        surface="#1a1a19",
        ink_primary="#f0efec",
        ink_secondary="#c3c2b7",
        ink_muted="#898781",
        gridline="#2c2c2a",
        baseline="#383835",
        border="rgba(255,255,255,0.10)",
        other="#6b6a65",
        good="#0ca30c",
        bad="#e66767",
        series=("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#0ca30c", "#9085e9", "#e66767"),
    ),
}

# Passed to st.plotly_chart(config=...): no logo, no clutter, PNG export kept.
PLOTLY_CONFIG = {
    "displaylogo": False,
    "modeBarButtonsToRemove": [
        "select2d", "lasso2d", "autoScale2d", "toggleSpikelines",
        "hoverClosestCartesian", "hoverCompareCartesian",
    ],
    "toImageButtonOptions": {"format": "png", "scale": 2},
}


def color_map(keys: list[str], mode: Mode) -> dict[str, str]:
    """Assign palette slots to entities in the given (stable) order.

    Pass keys in a stable order (e.g. sorted account ids), not ranked by value, so a
    filter that hides one series does not repaint the others. Keys beyond the 8th
    slot get the neutral "other" colour; callers should fold them into OTHER_LABEL.
    """
    tokens = TOKENS[mode]
    mapping = {key: tokens.series[i] for i, key in enumerate(keys[: len(tokens.series)])}
    for key in keys[len(tokens.series):]:
        mapping[key] = tokens.other
    mapping[OTHER_LABEL] = tokens.other
    return mapping


def _axis(tokens: Tokens, grid: bool) -> dict:
    return {
        "showgrid": grid,
        "gridcolor": tokens.gridline,
        "gridwidth": 1,
        "zeroline": False,
        "showline": not grid,
        "linecolor": tokens.baseline,
        "linewidth": 1,
        "ticks": "",
        "tickfont": {"color": tokens.ink_muted, "size": 12},
        "title": {"font": {"color": tokens.ink_secondary, "size": 12}},
        "automargin": True,
    }


def template(mode: Mode) -> go.layout.Template:
    tokens = TOKENS[mode]
    return go.layout.Template(
        layout={
            "font": {"family": FONT_FAMILY, "color": tokens.ink_primary, "size": 13},
            "colorway": list(tokens.series),
            "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor": "rgba(0,0,0,0)",
            # Polish number format: decimal comma, space as thousands separator.
            "separators": ", ",
            "margin": {"l": 8, "r": 8, "t": 36, "b": 8},
            "xaxis": _axis(tokens, grid=False),
            "yaxis": _axis(tokens, grid=True),
            "legend": {
                "orientation": "h",
                "x": 0,
                "xanchor": "left",
                "y": 1.02,
                "yanchor": "bottom",
                "bgcolor": "rgba(0,0,0,0)",
                "font": {"color": tokens.ink_secondary, "size": 12},
                "title": {"text": ""},
            },
            "hovermode": "x unified",
            "hoverlabel": {
                "bgcolor": tokens.surface,
                "bordercolor": tokens.border,
                "font": {"family": FONT_FAMILY, "color": tokens.ink_primary, "size": 13},
            },
            "spikedistance": -1,
            "bargap": 0.35,
        },
        data={
            "scatter": [go.Scatter(line={"width": 2, "shape": "linear"}, marker={"size": 8})],
            "bar": [go.Bar(marker={"line": {"width": 0}})],
        },
    )
