"""Streamlit entry point. Start with `fa ui` (or `streamlit run app/main.py`)."""

from __future__ import annotations

import os
from datetime import timedelta

import streamlit as st
from ui.components import apply_global_styles

from finance_analytics.config import get_settings
from finance_analytics.market.auto import maybe_update_market
from finance_analytics.market.live import read_live, update_live
from finance_analytics.preferences import PreferencesError, load_preferences

st.set_page_config(
    page_title="Finanse",
    page_icon=":material/savings:",
    layout="wide",
    initial_sidebar_state="expanded",
)

pages = {
    "Analiza": [
        st.Page("views/portfolio.py", title="Portfel", icon=":material/monitoring:", default=True),
        st.Page("views/returns.py", title="Zwroty", icon=":material/trending_up:"),
        st.Page("views/dividends.py", title="Dywidendy", icon=":material/payments:"),
        st.Page("views/bonds.py", title="Obligacje", icon=":material/account_balance:"),
    ],
    "Dane": [
        st.Page("views/imports.py", title="Importy", icon=":material/upload_file:"),
        st.Page("views/market.py", title="Dane rynkowe", icon=":material/candlestick_chart:"),
    ],
    "Aplikacja": [
        st.Page("views/settings.py", title="Ustawienia", icon=":material/settings:"),
    ],
}
if os.environ.get("FA_DEV") == "1":
    pages["Deweloper"] = [
        st.Page("views/style_preview.py", title="Podgląd stylu", icon=":material/palette:"),
    ]

navigation = st.navigation(pages, position="sidebar")
apply_global_styles()
settings = get_settings()


@st.fragment(run_every=timedelta(seconds=30))
def network_status() -> None:
    """Sidebar badge; in online mode also the live refresh loop (D-021).

    Runs every 30 s. The first run of a page only draws the badge, so network work
    never delays a page; later runs poll. The update functions throttle themselves
    (refresh interval, daily schedule), so most runs only read the database. When new
    data arrives the whole app reruns, so every page shows it.
    """
    try:
        preferences = load_preferences(settings)
    except PreferencesError as exc:
        st.caption(f":material/error: Błędny plik ustawień: {exc}")
        return
    if not preferences.online:
        st.caption(":material/cloud_off: **Offline**: bez połączeń z internetem.")
        return
    changed = False
    first_run = not st.session_state.get("network_started")
    st.session_state["network_started"] = True
    if settings.db_path.exists() and not first_run:
        try:
            changed = maybe_update_market(settings) is not None
            changed |= update_live(settings).updated
        except Exception as exc:  # network trouble must never break the page
            st.caption(f":material/sync_problem: Nie udało się odświeżyć: {exc}")
    _, _, fetched = read_live(settings.db_path, timedelta(hours=12)) if settings.db_path.exists() else (0, 0, None)
    when = f" · ceny z {fetched.astimezone():%H:%M}" if fetched else ""
    st.caption(f":material/cloud_done: **Online**{when}")
    if changed:
        st.rerun()


with st.sidebar:
    network_status()
    st.caption(":material/lock: Dane zostają na tym komputerze.")

navigation.run()
