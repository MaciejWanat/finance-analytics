"""A search field that filters while you type (D-057).

`st.text_input` sends its value only on Enter or blur. This is a tiny inline Streamlit v2
component instead: plain HTML, CSS and JavaScript shipped with the app (no package, no CDN,
no network, D-011). It sends the text to Python 250 ms after the last keystroke.
"""

from __future__ import annotations

import streamlit as st

_HTML = """
<label class="fa-search">
  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15.5 14h-.79l-.28-.27A6.47 6.47 0 0 0 16 9.5 6.5 6.5 0 1 0
  9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14
  7.01 14 9.5 11.99 14 9.5 14z"/></svg>
  <input type="search" autocomplete="off" spellcheck="false" aria-label="Szukaj">
</label>
"""

_CSS = """
.fa-search {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0 0.75rem; height: 2.5rem; box-sizing: border-box;
  border: 1px solid var(--st-border-color, rgba(128, 128, 128, 0.35));
  border-radius: var(--st-base-radius, 0.5rem);
  background: var(--st-secondary-background-color, transparent);
  color: var(--st-text-color, inherit);
  font-family: var(--st-font, inherit);
}
.fa-search:focus-within { border-color: var(--st-primary-color, #4a7bd0); }
.fa-search svg { width: 1.1rem; height: 1.1rem; flex: none; fill: currentColor; opacity: 0.6; }
.fa-search input {
  flex: 1; min-width: 0; border: 0; outline: 0; background: transparent;
  color: inherit; font: inherit; font-size: 0.95rem;
}
.fa-search input::placeholder { color: inherit; opacity: 0.55; }
"""

_JS = """
export default function(component) {
  const { parentElement, setStateValue, data } = component;
  const input = parentElement.querySelector('input');
  if (data && data.placeholder) input.placeholder = data.placeholder;
  if (input.dataset.ready) return;          // the element survives reruns; wire it once
  input.dataset.ready = '1';
  if (data && data.value) input.value = data.value;
  let timer;
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => setStateValue('value', input.value), 250);
  });
}
"""

_component = st.components.v2.component("fa_live_search", html=_HTML, css=_CSS, js=_JS)


def live_search(key: str, placeholder: str) -> str:
    """The current search text (stripped); the page reruns shortly after each change."""
    previous = st.session_state.get(f"_live_search_{key}", "")
    result = _component(key=f"live_search_{key}", data={"placeholder": placeholder, "value": previous},
                        default={"value": previous}, on_value_change=lambda: None)
    value = (getattr(result, "value", None) or "").strip()
    st.session_state[f"_live_search_{key}"] = value
    return value
