"""Page building blocks: header, KPI tiles, empty state (D-012)."""

from __future__ import annotations

import html
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import pandas as pd
import streamlit as st

from ui.charts import current_mode, detail_chart, show_detail, show_spark, sparkline
from ui.fmt import MINUS, fmt_number, fmt_pct
from ui.live_search import live_search
from ui.theme import TOKENS


@dataclass(frozen=True)
class Kpi:
    label: str  # sentence case, no trailing colon
    value: str  # already formatted, e.g. fmt_money_compact(...)
    delta: str | None = None  # signed, e.g. "+3,4%"; say vs what in `help`
    delta_color: Literal["normal", "inverse", "off"] = "normal"
    help: str | None = None
    trend: Sequence[float] | None = None  # sparkline, e.g. last 12 months
    trend_kind: Literal["money", "pct"] = "money"  # hover format: "12 345,67 zł" or "+3,4%"
    trend_water: bool = False  # fill from zero: red below (under water), green above
    # Daily history for the enlarged chart ("Pełny wykres"); the tile gets a button when set.
    series: pd.Series | None = None
    series_start: pd.Timestamp | None = None  # where the enlarged chart opens (the page's period)
    series_note: str | None = None  # a line above the enlarged chart, e.g. what the curve means
    # Several small signed badges instead of the one delta, e.g. [("USD +25k", 25000), ("EUR −1,2k", -1200)]:
    # green when the number is positive, red when negative (D-061).
    badges: Sequence[tuple[str, float]] = ()


_CSS = """
<style>
/* KPI tiles: values like "205,4 tys. zł" must fit four tiles in a row. */
[data-testid="stMetricValue"] { font-size: 1.7rem; font-weight: 600; }
[data-testid="stMetricLabel"] p { font-size: 0.85rem; }
/* Each tile is a size container, so a narrow tile (six in a row, a smaller window) shrinks its value
   instead of cutting digits off ("+78 1…"): full size from about 150 px of tile width, never below 1 rem. */
[class*="st-key-kpi_tile"] { container-type: inline-size; }
[class*="st-key-kpi_tile"] [data-testid="stMetricValue"] { font-size: clamp(1rem, 18cqi, 1.7rem); }

/* While the page recalculates (D-060): a small floating pill with a spinner at the top, over the
   content, so nothing moves. It appears only after 0.4 s, so quick reruns (typing in a search
   field, the 30-second background check) do not flash it. */
@keyframes fa-spin { to { transform: rotate(360deg); } }
@keyframes fa-show { to { opacity: 1; } }
.stApp[data-test-script-state="running"]::before,
.stApp[data-test-script-state="running"]::after {
  position: fixed; top: 0.9rem; z-index: 1000000; opacity: 0; pointer-events: none;
  animation: fa-show 0.2s ease-out 0.4s forwards;
}
.stApp[data-test-script-state="running"]::before {
  content: "Przeliczam…"; left: 50%; transform: translateX(-50%);
  padding: 0.35rem 0.9rem 0.35rem 2.1rem; border-radius: 999px;
  background: rgba(32, 32, 30, 0.88); color: #f6f5f2;  /* one neutral pill, readable on light and dark */
  font-size: 0.85rem; box-shadow: 0 2px 10px rgba(0, 0, 0, 0.18); border: 1px solid rgba(255, 255, 255, 0.14);
}
.stApp[data-test-script-state="running"]::after {
  content: ""; left: calc(50% - 3.1rem); top: calc(0.9rem + 0.42rem);
  width: 0.85rem; height: 0.85rem; border-radius: 50%;
  border: 2px solid rgba(255, 255, 255, 0.25); border-top-color: #f6f5f2;
  animation: fa-show 0.2s ease-out 0.4s forwards, fa-spin 0.8s linear infinite;
}
</style>
"""


def apply_global_styles() -> None:
    """Small CSS refinements on top of the Streamlit theme. Call once per run (main.py)."""
    st.html(_CSS)


def page_header(title: str, caption: str | None = None) -> None:
    st.title(title)
    if caption:
        st.caption(caption)


def section(title: str, caption: str | None = None, *, help: str | None = None) -> None:
    """Section heading; `help` adds a "?" tooltip (use texts from ui/glossary.py)."""
    st.subheader(title, help=help)
    if caption:
        st.caption(caption)


def _trend_color(kpi: Kpi, delta: str | None) -> str:
    """The sparkline takes the delta's colour; a neutral tile takes the accent (first series colour), not grey."""
    tokens = TOKENS[current_mode()]
    if kpi.delta_color == "off" or not delta:
        return tokens.series[0]
    down = delta.lstrip().startswith("-")
    if kpi.delta_color == "inverse":
        down = not down
    return tokens.bad if down else tokens.good


def _badges_html(badges: Sequence[tuple[str, float]]) -> str:
    """Pill badges in the style of Streamlit's metric delta; the colour follows each number's sign."""
    tokens = TOKENS[current_mode()]
    pills = []
    for text, number in badges:
        color = tokens.good if number > 0 else tokens.bad if number < 0 else tokens.ink_muted
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        pills.append(
            f'<span style="display:inline-block;margin:0 0.2rem 0.2rem 0;padding:0.05rem 0.4rem;'
            f'border-radius:999px;font-size:0.75rem;line-height:1.5;white-space:nowrap;color:{color};'
            f'background:rgba({r},{g},{b},0.15)">{html.escape(text)}</span>'
        )
    return f'<div style="margin-top:-0.6rem">{"".join(pills)}</div>'


def kpi_row(kpis: Sequence[Kpi]) -> None:
    """A row of bordered KPI tiles of equal height. Sparklines are our own Plotly charts, because
    Streamlit's built-in metric sparkline shows raw numbers ("-26118") in its hover."""
    for column, kpi in zip(st.columns(len(kpis)), kpis, strict=True):
        # Streamlit reads the delta's direction from a leading ASCII "-".
        delta = kpi.delta.replace(MINUS, "-") if kpi.delta else None
        with column.container(border=True, height="stretch", gap="small", key=f"kpi_tile_{kpi.label}"):
            st.metric(
                kpi.label,
                kpi.value,
                delta,
                delta_color=kpi.delta_color,
                # A neutral (grey) delta is information, not a direction: no arrow.
                delta_arrow="off" if kpi.delta_color == "off" else "auto",
                help=kpi.help,
            )
            if kpi.badges:
                st.html(_badges_html(kpi.badges))
            if kpi.trend and len(kpi.trend) > 1:
                show_spark(sparkline(kpi.trend, color=_trend_color(kpi, delta), kind=kpi.trend_kind,
                                     mode=current_mode(), water=kpi.trend_water), key=f"kpi_spark_{kpi.label}")
            if kpi.series is not None and len(kpi.series) > 1 and st.button(
                "Pełny wykres", icon=":material/open_in_full:", type="tertiary", key=f"kpi_open_{kpi.label}",
                help="Otwiera wykres w dużym oknie: przybliżanie kółkiem myszy lub zaznaczeniem, suwak zakresu.",
            ):
                _open_detail(kpi)


DIALOG_OPEN = "dialog_open"  # main.py does not rerun the whole app while a dialog is open (it would close it)


def _close_detail() -> None:
    st.session_state[DIALOG_OPEN] = False


def _open_detail(kpi: Kpi) -> None:
    st.session_state[DIALOG_OPEN] = True

    @st.dialog(kpi.label, width="large", on_dismiss=_close_detail)
    def detail() -> None:
        if kpi.series_note:
            st.caption(kpi.series_note)
        st.caption("Przybliżaj kółkiem myszy albo zaznaczając obszar; dwuklik przywraca cały widok.")
        show_detail(detail_chart(kpi.series, name=kpi.label, mode=current_mode(), kind=kpi.trend_kind,
                                 start=kpi.series_start), key=f"kpi_detail_{kpi.label}")

    detail()


def filter_rows(df: pd.DataFrame, query: str) -> pd.DataFrame:
    """Rows whose text cells contain `query`, ignoring case; numbers and lists are not searched."""
    text = df.select_dtypes(include=["object", "string"])
    text = text.loc[:, [c for c in text.columns if not text[c].map(lambda v: isinstance(v, list)).any()]]
    if text.empty:
        return df
    hits = text.apply(lambda col: col.astype(str).str.contains(query, case=False, regex=False, na=False))
    return df[hits.any(axis=1)]


def table(
    df: pd.DataFrame,
    *,
    numbers: dict[str, int] | None = None,
    signed: Sequence[str] = (),
    datetimes: Sequence[str] = (),
    percents: Sequence[str] = (),
    trends: Sequence[str] = (),
    labels: dict[str, str] | None = None,
    helps: dict[str, str] | None = None,
    missing_labels: dict[str, str] | None = None,
    search: str | None = None,
) -> None:
    """A dataframe with Polish number formatting that still sorts numerically.

    search: a unique key; adds a "Szukaj" field above the table that keeps only the rows
    whose text columns contain the typed text (case-insensitive), e.g. "am" -> AMD.

    numbers: column -> decimals; signed: columns coloured green/red by sign;
    datetimes: columns shown as YYYY-MM-DD HH:MM; percents: fractions shown as +3,4%;
    trends: columns holding lists of numbers, drawn as sparklines;
    labels: column -> header text; helps: column -> tooltip on the header (texts from
    ui/glossary.py). Empty cells show as "–" instead of None/NaN, unless a column has
    an explicit label in missing_labels.
    """
    tokens = TOKENS[current_mode()]
    labels = labels or {}
    if search:
        query = live_search(search, "Szukaj: ticker, nazwa, rachunek…")  # filters while typing (D-057)
        if query:
            total = len(df)
            df = filter_rows(df, query)
            st.caption(f"Pasuje {len(df)} z {total}." if len(df) else f"Nic nie pasuje do „{query}”.")
    # Rename instead of column_config labels: Streamlit drops Styler display values
    # for columns that have a column_config entry.
    df = df.rename(columns=labels)
    numbers = {labels.get(col, col): d for col, d in (numbers or {}).items()}
    signed = [labels.get(col, col) for col in signed]
    datetimes = [labels.get(col, col) for col in datetimes]
    percents = [labels.get(col, col) for col in percents]
    trends = [labels.get(col, col) for col in trends]
    missing_labels = {labels.get(col, col): text for col, text in (missing_labels or {}).items()}
    for column, text in missing_labels.items():
        if column in df:
            df[column] = df[column].astype(object).where(df[column].notna(), text)
    # Streamlit paints empty text cells as a grey "None"; show a dash instead. Numeric columns
    # keep their gaps (na_rep below): a column of only None is object-typed but is not text.
    formatted = {*numbers, *datetimes, *percents, *trends}
    text_columns = [col for col in df.select_dtypes(include=["object", "string"]).columns if col not in formatted]
    df[text_columns] = df[text_columns].astype(object).where(df[text_columns].notna(), "–")
    # One format() call: each call with a dict resets every column it does not name.
    formatters: dict[str, object] = {
        col: (lambda v, d=d: v if isinstance(v, str) else fmt_number(v, d)) for col, d in numbers.items()
    }
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
    # Header tooltips: a help-only Column keeps the Styler's formatted values.
    tooltip = {labels.get(col, col): text for col, text in (helps or {}).items()}
    config: dict[str, object] = {col: st.column_config.Column(help=text) for col, text in tooltip.items()}
    for col in trends:  # sparkline columns are the one place column_config shapes the display
        config[col] = st.column_config.LineChartColumn(col, width="small", help=tooltip.get(col))
    st.dataframe(styler, hide_index=True, width="stretch", column_config=config)


def empty_state(title: str, body: str, *, icon: str = ":material/inbox:", steps: Sequence[str] = ()) -> None:
    with st.container(border=True):
        st.markdown(f"#### {icon} {title}")
        st.markdown(body)
        if steps:
            st.markdown("\n".join(f"{i}. {step}" for i, step in enumerate(steps, start=1)))
