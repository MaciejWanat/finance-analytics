"""Plotly charts that update in place on a live redraw (D-072).

`st.plotly_chart` gives a chart a new element ID whenever its figure changes, and its frontend reads the figure only
when the chart mounts. So every live redraw removed the chart and drew a new one, which left the area empty for a
frame or two: the chart blinked every few seconds. This component (Streamlit components v2, in the page, no iframe)
keeps one chart per key and hands it the new figure with `Plotly.react`, which changes only what changed.

plotly.js comes from the installed `plotly` package, copied once into the app's `static/` folder and served by
Streamlit from this machine (`server.enableStaticServing`); nothing is fetched from the internet (D-011). If the copy
is not possible, `available()` is False and charts fall back to `st.plotly_chart`.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import plotly
import plotly.graph_objects as go
import plotly.io
import streamlit as st
from plotly.offline import get_plotlyjs_version

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"  # served at /app/static/ (Streamlit static serving)
PLOTLY_JS = f"plotly-{get_plotlyjs_version()}.min.js"  # the version in the name: a new one is never a stale cache

_JS = """
const SRC = "/app/static/%(file)s";

// Always our own copy, kept apart: Streamlit's charts also set the global `Plotly` (another version, loaded when
// they first appear), and a chart must not be drawn by one version and updated by another.
function loadPlotly() {
  if (!window.__faPlotly) {
    window.__faPlotly = new Promise((resolve, reject) => {
      const previous = window.Plotly;
      const script = document.createElement("script");
      script.src = SRC;
      script.onload = () => {
        const own = window.Plotly;
        if (previous) window.Plotly = previous;  // leave the global as it was
        resolve(own);
      };
      script.onerror = () => { window.__faPlotly = null; reject(new Error("plotly.js not available")); };
      document.head.appendChild(script);
    });
  }
  return window.__faPlotly;
}

export default function ({ parentElement, data }) {
  let chart = parentElement.querySelector(":scope > .fa-live-chart");
  if (!chart) {
    chart = document.createElement("div");
    chart.className = "fa-live-chart";
    chart.style.width = "100%%";
    parentElement.appendChild(chart);
  }
  const figure = JSON.parse(data.figure);
  chart.style.height = (figure.layout && figure.layout.height ? figure.layout.height : 340) + "px";
  chart.__faNext = figure;  // the newest figure wins if redraws arrive while plotly.js loads
  loadPlotly().then((Plotly) => {
    const next = chart.__faNext;
    if (!next) return;
    chart.__faNext = null;
    Plotly.react(chart, next.data, next.layout, data.config);
  });
}
"""

_CSS = ".fa-live-chart { width: 100%; }"


def _ensure_plotly_js() -> bool:
    """Copy plotly.js from the plotly package next to the app, once per version. False if that is not possible."""
    target = STATIC_DIR / PLOTLY_JS
    if target.exists():
        return True
    source = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
    try:
        STATIC_DIR.mkdir(exist_ok=True)
        partial = target.with_suffix(".tmp")
        shutil.copyfile(source, partial)
        os.replace(partial, target)
        for old in STATIC_DIR.glob("plotly-*.min.js"):  # earlier versions of the package
            if old.name != PLOTLY_JS:
                old.unlink(missing_ok=True)
    except OSError:
        return False
    return True


_READY = _ensure_plotly_js()
_component = st.components.v2.component("fa_live_plotly", js=_JS % {"file": PLOTLY_JS}, css=_CSS,
                                        isolate_styles=False)


def available() -> bool:
    """plotly.js is next to the app and Streamlit serves the app's static folder."""
    return _READY and bool(st.get_option("server.enableStaticServing"))


def live_plotly(fig: go.Figure, *, key: str, config: dict) -> None:
    """Draw `fig` under `key`; on the next run with the same key the same chart takes the new figure in place."""
    _component(data={"figure": plotly.io.to_json(fig, validate=False), "config": config}, key=key)
