"""Settings: network mode (offline / online) and live refresh interval (D-021)."""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from ui.components import page_header, section
from ui.glossary import G

from finance_analytics.config import get_settings
from finance_analytics.preferences import load_preferences, save_preferences

page_header(
    "Ustawienia",
    "Twoje dane zawsze zostają na tym komputerze. Tu decydujesz, czy aplikacja może korzystać z sieci.",
)
settings = get_settings()
preferences = load_preferences(settings)

section("Tryb pracy")
mode = st.radio(
    "Tryb pracy",
    ["offline", "online"],
    index=1 if preferences.online else 0,
    format_func={"offline": "Offline: bez połączeń z internetem", "online": "Online: dane rynkowe na żywo"}.get,
    label_visibility="collapsed",
    horizontal=True,
    help=f'Offline: {G["offline"]} Online: {G["online"]}',
)

left, right = st.columns(2, gap="large")
with left, st.container(border=True, height="stretch"):
    st.markdown("#### :material/cloud_off: Offline")
    st.markdown(
        "- Aplikacja **nie wykonuje żadnych połączeń** sieciowych.\n"
        "- Wyceny liczone są na już pobranych cenach i kursach.\n"
        "- Wszystko działa lokalnie: import, wykresy, raporty."
    )
with right, st.container(border=True, height="stretch"):
    st.markdown("#### :material/cloud_sync: Online")
    st.markdown(
        "- Ceny posiadanych instrumentów odświeżane co kilka minut w dni robocze (Yahoo Finance).\n"
        "- Kursy NBP dociągane codziennie po publikacji tabeli (ok. 12:15), inflacja z GUS raz dziennie.\n"
        "- Wysyłane są **wyłącznie** tickery (np. `NVDA`), kody walut i daty. "
        "Nigdy salda, ilości, kwoty ani numery rachunków."
    )

refresh = st.slider(
    "Odświeżanie cen w trybie online (minuty)", min_value=1, max_value=60, value=preferences.refresh_minutes,
    disabled=mode == "offline",
    help="Co ile minut aplikacja pobiera bieżące ceny i kursy, gdy jest otwarta. Tylko w dni robocze.",
)

section(
    "Folder skrzynki XTB",
    "Aplikacja tylko czyta ten folder i kopiuje nowe eksporty do własnego katalogu danych. "
    "Niczego w nim nie zmienia ani nie usuwa.",
    help=G["inbox"],
)
inbox_text = st.text_input(
    "Ścieżka do folderu", value=preferences.inbox_dir or "", placeholder="np. D:/Pobrane/XTB",
    help=G["inbox"], label_visibility="collapsed",
).strip().strip('"')
inbox_dir = str(Path(inbox_text).expanduser().resolve()) if inbox_text else None
inbox_ok = inbox_dir is None or Path(inbox_dir).is_dir()
if not inbox_ok:
    st.error("Nie znaleziono takiego folderu. Wskaż istniejący folder albo wyczyść pole.", icon=":material/error:")

changed = (
    mode != preferences.network or refresh != preferences.refresh_minutes or inbox_dir != preferences.inbox_dir
)
if st.button("Zapisz", type="primary", icon=":material/save:", disabled=not changed or not inbox_ok):
    save_preferences(settings, preferences.model_copy(update={
        "network": mode, "refresh_minutes": refresh, "inbox_dir": inbox_dir,
    }))
    st.toast("Zapisano ustawienia.", icon=":material/check_circle:")
    st.rerun()

st.caption(f"Plik ustawień: `{settings.preferences_file}`")
