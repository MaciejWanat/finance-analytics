"""Settings: network mode (D-021), inbox folder (D-028) and data reset (D-038)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import streamlit as st
from ui.components import page_header, section
from ui.fmt import plural
from ui.glossary import G

from finance_analytics.config import get_settings
from finance_analytics.preferences import load_preferences, save_preferences
from finance_analytics.sources.reset import ResetChoice, backup_zip, files_for, reset_data

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
    format_func={"offline": "Offline: pobieranie tylko na żądanie", "online": "Online: dane rynkowe na żywo"}.get,
    label_visibility="collapsed",
    horizontal=True,
    help=f'Offline: {G["offline"]} Online: {G["online"]}',
)

left, right = st.columns(2, gap="large")
with left, st.container(border=True, height="stretch"):
    st.markdown("#### :material/cloud_off: Offline")
    st.markdown(
        "- Aplikacja **sama nie łączy się** z internetem: nic nie odświeża się w tle.\n"
        "- Dane rynkowe pobierasz tylko wtedy, gdy sam klikniesz przycisk na stronie Dane rynkowe.\n"
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

section("Kafelek „Dzisiaj”", "Od kiedy liczy się dzisiejszy wynik na stronie Portfel.", help=G["today_tile"])
today_tile = st.radio(
    "Kafelek „Dzisiaj”",
    ["calendar_day", "us_session"],
    index=0 if preferences.today_tile == "calendar_day" else 1,
    format_func={"calendar_day": "Od północy", "us_session": "Sesjami giełdy w USA"}.get,
    label_visibility="collapsed",
    horizontal=True,
    help=G["today_tile"],
)

changed = (
    mode != preferences.network or refresh != preferences.refresh_minutes or inbox_dir != preferences.inbox_dir
    or today_tile != preferences.today_tile
)
if st.button("Zapisz", type="primary", icon=":material/save:", disabled=not changed or not inbox_ok):
    save_preferences(settings, preferences.model_copy(update={
        "network": mode, "refresh_minutes": refresh, "inbox_dir": inbox_dir, "today_tile": today_tile,
    }))
    st.toast("Zapisano ustawienia.", icon=":material/check_circle:")
    st.rerun()

st.caption(f"Plik ustawień: `{settings.preferences_file}`")

section(
    "Resetowanie danych",
    "Usuwa pliki źródłowe z katalogu danych aplikacji i opróżnia bazę. Tej operacji nie da się cofnąć.",
    help=G["reset"],
)
if message := st.session_state.pop("reset_done", None):
    st.success(message, icon=":material/check_circle:")
with st.container(border=True):
    st.markdown("##### Co usunąć")
    reset_choice = ResetChoice(
        exports=st.checkbox("Zaimportowane eksporty XTB", value=True, help="Pliki .xlsx w `raw/` katalogu danych."),
        manual=st.checkbox("Wpisy ręczne: obligacje i salda gotówki", value=True,
                           help="`manual/bonds.csv` i `manual/cash_balances.csv`."),
        accounts=st.checkbox("Rachunki (nazwy i ustawienia rachunków)", value=True,
                             help="`config/accounts.yaml` i `config/bond_series.yaml`."),
        market=st.checkbox("Dane rynkowe: ceny, kursy, inflacja", value=False, help=G["market_cache"]),
    )
    to_delete = files_for(settings, reset_choice)
    st.caption(
        f"Do usunięcia: {plural(len(to_delete), 'plik', 'pliki', 'plików')}"
        + (" oraz zapisane dane rynkowe." if reset_choice.market else ".")
        + f" Katalog danych: `{settings.data_dir}`"
    )
    st.download_button(
        "Pobierz kopię zapasową (.zip)", data=backup_zip(settings),
        file_name=f"finanse-kopia-{date.today():%Y-%m-%d}.zip", mime="application/zip",
        icon=":material/archive:", on_click="ignore",
        help="Eksporty, wpisy ręczne i konfiguracja w jednym pliku. Zostaje na tym komputerze.",
    )
    typed = st.text_input(
        "Aby potwierdzić, wpisz USUŃ", placeholder="USUŃ",
        key=f"reset_confirm_{st.session_state.get('reset_round', 0)}",
    )
    nothing = not to_delete and not reset_choice.market
    if st.button("Usuń dane", type="primary", icon=":material/delete_forever:",
                 disabled=nothing or typed.strip().upper() != "USUŃ"):
        result = reset_data(settings, reset_choice)
        st.cache_data.clear()
        st.session_state["reset_round"] = st.session_state.get("reset_round", 0) + 1
        st.session_state["reset_done"] = (
            f"Usunięto {plural(len(result.removed), 'plik', 'pliki', 'plików')}"
            + (" i zapisane dane rynkowe." if result.market_cleared else ".")
        )
        st.rerun()
