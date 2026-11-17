"""Streamlit entry point. Start with `fa ui` (or `streamlit run app/main.py`)."""

from __future__ import annotations

import os
import time
from datetime import timedelta

import streamlit as st
from ui.components import DIALOG_OPEN, apply_global_styles
from ui.fmt import plural

from finance_analytics.config import get_settings
from finance_analytics.market.auto import maybe_update_market
from finance_analytics.market.live import read_live, update_live
from finance_analytics.preferences import PreferencesError, load_preferences
from finance_analytics.sources.inbox import check_inbox

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
        st.Page("views/cash.py", title="Gotówka", icon=":material/account_balance_wallet:"),
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
if message := st.session_state.pop("inbox_toast", None):
    st.toast(message, icon=":material/inbox:")
INBOX_INTERVAL_SECONDS = 60  # how often the inbox folder is checked (D-028)


def _inbox_tick() -> int:
    """Import new exports from the inbox folder, at most once a minute; works offline too (D-028).

    The first run of a session only starts the clock, so page load is never delayed.
    Returns how many files were newly copied.
    """
    now = time.monotonic()
    last = st.session_state.get("inbox_checked_at")
    if last is None:
        st.session_state["inbox_checked_at"] = now
        return 0
    if now - last < INBOX_INTERVAL_SECONDS or not settings.db_path.exists():
        return 0
    st.session_state["inbox_checked_at"] = now
    try:
        result = check_inbox(settings)
    except Exception as exc:  # the inbox must never break the page
        st.caption(f":material/sync_problem: Folder skrzynki: {exc}")
        return 0
    if result is None:
        return 0
    if result.error:
        st.caption(f":material/sync_problem: {result.error}")
        return 0
    return len(result.copied)


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
    imported = _inbox_tick()
    if imported:
        st.session_state["inbox_toast"] = (
            f"Zaimportowano {plural(imported, 'nowy plik', 'nowe pliki', 'nowych plików')} z folderu skrzynki"
        )
        st.rerun()
    if not preferences.online:
        st.caption(":material/cloud_off: **Offline**: nic nie pobiera się samo.")
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
    # Rerun the whole app only when this was the fragment's own timer run: in a full run (a click, a page
    # change) the page renders after this fragment and already reads the new data, so a second rerun would
    # only cost time and could swallow the click. A full rerun would also close an open dialog (KPI chart).
    if changed and not st.session_state.get(FULL_RUN) and not st.session_state.get(DIALOG_OPEN):
        st.rerun()


FULL_RUN = "full_app_run"  # True while the whole script runs; a fragment's timer rerun sees False
st.session_state[FULL_RUN] = True
try:
    with st.sidebar:
        network_status()
        st.caption(":material/lock: Dane zostają na tym komputerze.")
    navigation.run()
finally:  # also after st.stop() in a page
    st.session_state[FULL_RUN] = False
