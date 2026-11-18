"""Rolling digits for the KPI tiles (D-074).

When a tile's value changes on a live redraw, the digits that changed roll to the new ones (up when the number
grows, down when it falls) and flash green or red for a moment, instead of the text simply being swapped.

How, without fighting React: Streamlit keeps the tile's text node and changes its content. A small script (an
invisible Streamlit component, installed once per page) watches the tile values. Over each one it draws an overlay
in the same font; the original text stays in place, transparent, so the layout does not move. If anything fails,
the overlay is not drawn and the original text shows as before. With "reduce motion" set in the system, the digits
change without rolling.
"""

from __future__ import annotations

import streamlit as st

KEY = "fa_ticker"

_JS = r"""
const VALUE = '[data-testid="stMetricValue"]';
const ROLL_MS = 480;
const FLASH_MS = 1100;

function amount(text) {
  // "462,7 tys. zł" -> 462700, "−6,90%" -> -6.9; null when there is no number
  const t = text.replace(/[\s ]/g, "").replace("−", "-");
  const m = t.match(/[-+]?\d+(?:,\d+)?/);
  if (!m) return null;
  let n = parseFloat(m[0].replace(",", "."));
  if (/tys\./.test(t)) n *= 1e3;
  if (/mln/.test(t)) n *= 1e6;
  if (/mld/.test(t)) n *= 1e9;
  return n;
}

function plain(ch) {
  const s = document.createElement("span");
  s.textContent = ch;
  return s;
}

function rolling(from, to, up) {
  // A one-character window over a column of [from, to] (up) or [to, from] (down), slid to the new one.
  const box = document.createElement("span");
  box.className = "fa-roll " + (up ? "fa-up" : "fa-down");
  const col = document.createElement("span");
  col.className = "fa-col";
  const a = plain(up ? from : to), b = plain(up ? to : from);
  col.append(a, b);
  box.append(col);
  const frames = up ? ["translateY(0)", "translateY(-50%)"] : ["translateY(-50%)", "translateY(0)"];
  col.animate([{ transform: frames[0] }, { transform: frames[1] }],
              { duration: ROLL_MS, easing: "cubic-bezier(.2,.8,.2,1)", fill: "forwards" });
  box.animate([{ color: up ? "var(--fa-good)" : "var(--fa-bad)" }, { color: "inherit" }],
              { duration: FLASH_MS, easing: "ease-out" });
  return box;
}

function draw(overlay, before, after, animate) {
  if (!animate || before === undefined || before === after) {
    overlay.replaceChildren(plain(after));
    return;
  }
  const a = amount(before), b = amount(after);
  const up = a === null || b === null ? true : b >= a;
  // Align from the right, so units ("zł", "%") and the last digits line up.
  const n = Math.max(before.length, after.length);
  const old = before.padStart(n, "\u0000"), now = after.padStart(n, "\u0000");
  const parts = [];
  for (let i = 0; i < n; i++) {
    const o = old[i], c = now[i];
    if (c === "\u0000") continue;
    if (o === c) parts.push(plain(c));
    else if (/\d/.test(c) || /\d/.test(o)) parts.push(rolling(o === "\u0000" ? " " : o, c, up));
    else parts.push(plain(c));
  }
  overlay.replaceChildren(...parts);
}

function place(host, source, overlay) {
  // Measured on every pass, not only when the text changes: a full rerun (another theme, a filter) moves things.
  const hostBox = host.getBoundingClientRect(), box = source.getBoundingClientRect();
  const s = overlay.style;
  s.left = (box.left - hostBox.left) + "px";
  s.top = (box.top - hostBox.top) + "px";
  s.height = box.height + "px";
  s.lineHeight = box.height + "px";
  s.width = box.width + "px";
}

function sync(host, reduce, sizes) {
  const source = host.querySelector("p");
  if (!source) return;
  const text = source.textContent;
  let overlay = host.querySelector(":scope > .fa-ticker");
  const fresh = !overlay;
  if (fresh) {
    overlay = document.createElement("span");
    overlay.className = "fa-ticker";
    overlay.setAttribute("aria-hidden", "true");
    host.append(overlay);
    sizes.observe(host);
  }
  place(host, source, overlay);
  if (overlay.dataset.text !== text) {
    draw(overlay, fresh ? undefined : overlay.dataset.text, text, !reduce.matches);
    overlay.dataset.text = text;
  }
  // Only now hide the original text: the overlay is there. An attribute, not a class: React rewrites the class
  // list of this element (e.g. on a theme change), but leaves attributes it does not manage alone.
  host.dataset.faTicker = "on";
}

export default function () {
  if (window.__faTicker) return;
  window.__faTicker = true;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
  let queued = false;
  const run = () => {
    queued = false;
    for (const host of document.querySelectorAll(VALUE)) {
      try { sync(host, reduce, sizes); } catch (e) { delete host.dataset.faTicker; }
    }
  };
  const schedule = () => { if (!queued) { queued = true; setTimeout(run, 0); } };
  const sizes = new ResizeObserver(schedule);  // a narrower tile shrinks the font (container query)
  new MutationObserver((records) => {
    // Our own overlay changes do not count, or every roll would trigger the next one.
    if (records.every((r) => r.target.closest && r.target.closest(".fa-ticker"))) return;
    schedule();
  }).observe(document.body, { subtree: true, childList: true, characterData: true });
  schedule();
}
"""

_CSS = """
.st-key-fa_ticker { display: none; }
[data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; }
[data-fa-ticker] { position: relative; }
[data-fa-ticker] p { color: transparent !important; }
.fa-ticker {
  position: absolute; white-space: pre; overflow: hidden; pointer-events: none;
  font-variant-numeric: tabular-nums; color: inherit;
}
.fa-roll { display: inline-block; overflow: hidden; vertical-align: top; height: 1lh; }
.fa-col { display: flex; flex-direction: column; }
.fa-col > span { display: block; height: 1lh; }
"""

_component = st.components.v2.component(KEY, js=_JS, css=_CSS, isolate_styles=False)


def install_ticker() -> None:
    """Mount the (invisible) script once per full run; it keeps working through live redraws of the tiles."""
    _component(key=KEY)
