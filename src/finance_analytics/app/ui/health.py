"""Resource tiles for the Ustawienia page (D-073): CPU and memory of the app, colour-coded by level."""

from __future__ import annotations

import html
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import streamlit as st

from ui.charts import current_mode
from ui.fmt import fmt_number
from ui.theme import TOKENS, Tokens

Level = Literal["ok", "warn", "high", "info"]
LEVEL_WORD = {"ok": "w normie", "warn": "podwyższone", "high": "wysokie", "info": ""}


@dataclass(frozen=True)
class HealthTile:
    label: str
    value: str  # already formatted
    detail: str  # a muted line under the value
    level: Level = "info"  # "info": no judgement, neutral colour
    hover: str | None = None


def fmt_cpu(pct: float | None) -> str:
    """CPU in percent points of the whole machine: 3.14 -> '3,1%'."""
    return "–" if pct is None else f"{fmt_number(pct, 1)}%"


def fmt_bytes(count: int | None) -> str:
    """412_000_000 -> '393 MB'; from 1 GB with one decimal: '1,4 GB'."""
    if count is None:
        return "–"
    mb = count / 2**20
    return f"{fmt_number(mb / 1024, 1)} GB" if mb >= 1024 else f"{fmt_number(mb, 0)} MB"


def _color(level: Level, tokens: Tokens) -> str:
    return {"ok": tokens.good, "warn": tokens.caution, "high": tokens.bad, "info": tokens.ink_muted}[level]


def health_html(tiles: Sequence[HealthTile], tokens: Tokens) -> str:
    """Tiles of equal height in a grid that wraps on a narrow screen. Each has a coloured edge and a lamp, and
    the level in words, so colour is never the only signal."""
    cells = []
    for tile in tiles:
        color = _color(tile.level, tokens)
        title = f' title="{html.escape(tile.hover)}"' if tile.hover else ""
        word = LEVEL_WORD[tile.level]
        badge = (
            f'<span style="display:inline-flex;align-items:center;gap:0.35rem;font-size:0.8rem;color:{color};'
            f'font-weight:600"><span style="width:0.6rem;height:0.6rem;border-radius:50%;background:{color}">'
            f"</span>{word}</span>" if word else ""
        )
        cells.append(
            f'<div{title} style="border:1px solid {tokens.border};border-left:0.3rem solid {color};'
            f'border-radius:0.5rem;padding:0.6rem 0.8rem;display:flex;flex-direction:column;gap:0.15rem">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;gap:0.5rem">'
            f'<span style="font-size:0.85rem;color:{tokens.ink_secondary}">{html.escape(tile.label)}</span>{badge}'
            f"</div>"
            f'<div style="font-size:1.6rem;font-weight:600;color:{tokens.ink_primary}">{html.escape(tile.value)}</div>'
            f'<div style="font-size:0.8rem;color:{tokens.ink_muted}">{html.escape(tile.detail)}</div></div>'
        )
    return (
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(11rem,1fr));gap:0.75rem;'
        f'font-variant-numeric:tabular-nums">{"".join(cells)}</div>'
    )


def health_tiles(tiles: Sequence[HealthTile]) -> None:
    st.html(health_html(tiles, TOKENS[current_mode()]))
