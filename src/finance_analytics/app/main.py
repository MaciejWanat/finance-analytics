"""Streamlit entry point. Start with `fa ui`, which runs it from this folder so .streamlit/config.toml applies."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta

import streamlit as st
from ui.components import DIALOG_OPEN, StatusRow, apply_global_styles, live_status, run_end_marker, status_list
from ui.data import FULL_RUN
from ui.fmt import market_text, plural
from ui.glossary import G

from finance_analytics.config import get_settings
from finance_analytics.diagnostics import get_monitor
from finance_analytics.market.auto import maybe_update_market
from finance_analytics.market.feed import get_feed
from finance_analytics.market.hours import EXCHANGES
from finance_analytics.market.live import read_live
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


LIVE_PAGES = {"Zwroty", "Dywidendy"}  # read live quotes but redraw only on a full run (Portfel has live fragments)
LIVE_RERUN_SECONDS = 60  # at most this often a page in LIVE_PAGES is redrawn for new live quotes
STREAM_TEXT = {"streaming": "na żywo", "connecting": "łączę ze strumieniem…", "error": "ponawiam połączenie…",
               "paused": "rynki zamknięte"}


def _live_line(preferences, fetched: datetime | None) -> None:
    """The lamp and text of the live prices line (D-069). With the stream no time of the last price: it would
    change every second; the pulsing lamp says the prices are live. Polling shows when the last prices came."""
    status = get_feed(settings).status()
    hover = G["live_status"] + (f" {status.message}" if status.message else "")
    if preferences.live_source == "stream":
        state = {"live": "streaming", "off": "connecting"}.get(status.state, status.state)
        live_status(state, STREAM_TEXT[state], hover=hover)
        return
    prices = f"ceny z {fetched.astimezone():%H:%M}" if fetched else "ceny z ostatnich notowań"
    if status.state == "paused":
        live_status("paused", f"rynki zamknięte · {prices}", hover=hover)
    else:  # after a failed poll the last prices stay; the red lamp and the hover say why
        live_status("error" if status.state == "error" else "polling", prices, hover=hover)


@st.fragment(run_every=timedelta(seconds=5))
def network_status() -> None:
    """Sidebar badge; in online mode it also keeps the live price feed running (D-021, D-069).

    Runs every 5 s and only reads: the feed (`market.feed`) fetches prices in its own thread. The first run of a
    page only draws the badge, so the daily update never delays a page. The whole app reruns when the daily
    update brings new data; for live quotes Portfel has its own live fragments, Zwroty and Dywidendy rerun at
    most once a minute.
    """
    try:
        preferences = load_preferences(settings)
    except PreferencesError as exc:
        st.caption(f":material/error: Błędny plik ustawień: {exc}")
        return
    # Resource use (D-073): the monitor samples in its own thread; a warning only when it is high.
    if get_monitor().snapshot().level == "high":
        st.page_link("views/settings.py", label=":red[Wysokie zużycie zasobów]", icon=":material/warning:",
                     help="Aplikacja zużywa dużo procesora lub pamięci. Szczegóły i co zrobić: Ustawienia.")
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
    if settings.db_path.exists():
        get_feed(settings).touch()
        if not first_run:
            try:
                changed = maybe_update_market(settings) is not None
            except Exception as exc:  # network trouble must never break the page
                st.caption(f":material/sync_problem: Nie udało się odświeżyć: {exc}")
    fetched = read_live(settings.db_path)[2] if settings.db_path.exists() else None
    _live_line(preferences, fetched)
    if fetched is not None and fetched != st.session_state.get("live_seen") and navigation.title in LIVE_PAGES:
        last = st.session_state.get("live_rerun_at", 0.0)
        if time.monotonic() - last >= LIVE_RERUN_SECONDS:
            st.session_state["live_seen"], st.session_state["live_rerun_at"] = fetched, time.monotonic()
            changed = True
    # Rerun the whole app only when this was the fragment's own timer run: in a full run (a click, a page
    # change) the page renders after this fragment and already reads the new data, so a second rerun would
    # only cost time and could swallow the click. A full rerun would also close an open dialog (KPI chart).
    if changed and not st.session_state.get(FULL_RUN) and not st.session_state.get(DIALOG_OPEN):
        st.rerun()


@st.fragment(run_every=timedelta(seconds=30))
def market_clock() -> None:
    """Open and closed exchanges with the time to the next change (D-066, D-068); works offline too."""
    now = datetime.now(UTC)
    rows = []
    for exchange in EXCHANGES:
        status = exchange.status(now)
        rows.append(StatusRow(exchange.name, status.phase, *market_text(status, now)))
    status_list("Giełdy", rows, help=G["markets"])


st.session_state[FULL_RUN] = True  # a fragment's timer rerun sees False
# A full run means any open dialog is gone (a click outside it, a page change); only a live fragment's own run may
# keep one open (components.kpi_row), so a stale flag never reopens it.
st.session_state[DIALOG_OPEN] = False
try:
    with st.sidebar:
        network_status()
        market_clock()
        st.caption(":material/lock: Dane zostają na tym komputerze.")
    navigation.run()
    run_end_marker()
finally:  # also after st.stop() in a page
    st.session_state[FULL_RUN] = False
