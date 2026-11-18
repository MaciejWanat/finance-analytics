"""Settings: network mode (D-021), live prices (D-069), resource use (D-073), inbox folder (D-028) and data reset
(D-038)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import streamlit as st
from ui.components import page_header, section
from ui.fmt import fmt_number, interval_text, plural
from ui.glossary import G
from ui.health import HealthTile, fmt_bytes, fmt_cpu, health_tiles

from finance_analytics.config import get_settings
from finance_analytics.diagnostics import advice, cpu_level, get_monitor
from finance_analytics.preferences import load_preferences, save_preferences
from finance_analytics.sources.reset import ResetChoice, backup_zip, files_for, reset_data

page_header(
    "Ustawienia",
    "Twoje dane zawsze zostają na tym komputerze. Tu decydujesz, czy aplikacja może korzystać z sieci.",
)
settings = get_settings()
preferences = load_preferences(settings)
POLL_STEPS = (120, 300, 600, 900, 1800, 3600)  # seconds; not more often than every 2 minutes (D-069)
STREAM_STEPS = (1, 2, 5, 10, 15, 30, 60)

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
        "- Ceny posiadanych instrumentów na bieżąco (Yahoo Finance), także z pre-market i post-market w USA.\n"
        "- Kursy NBP dociągane codziennie po publikacji tabeli (ok. 12:15), inflacja z GUS raz dziennie.\n"
        "- Wysyłane są **wyłącznie** tickery (np. `NVDA`), kody walut i daty. "
        "Nigdy salda, ilości, kwoty ani numery rachunków."
    )

section("Ceny na żywo", "Tylko w trybie online: skąd i jak często przychodzą bieżące ceny.", help=G["live_source"])
source_col, refresh_col = st.columns([2, 3], gap="large", vertical_alignment="bottom")
with source_col:
    live_source = st.radio(
        "Źródło cen", ["poll", "stream"], index=0 if preferences.live_source == "poll" else 1,
        format_func={"poll": "Odpytywanie", "stream": "Strumień"}.get, horizontal=True,
        disabled=mode == "offline", help=G["live_source"],
    )
# Each source has its own range and keeps its own value: polling every 2 minutes to an hour, the stream's redraw
# every 5 to 60 seconds.
poll_seconds, stream_seconds = preferences.poll_seconds, preferences.stream_seconds
with refresh_col:
    if live_source == "stream":
        stream_seconds = st.select_slider(
            "Co ile odświeżać stronę", sorted({*STREAM_STEPS, stream_seconds}), value=stream_seconds,
            format_func=interval_text, key="stream_seconds", disabled=mode == "offline", help=G["live_refresh"],
        )
    else:
        poll_seconds = st.select_slider(
            "Co ile pobierać ceny", sorted({*POLL_STEPS, poll_seconds}), value=poll_seconds,
            format_func=interval_text, key="poll_seconds", disabled=mode == "offline", help=G["live_refresh"],
        )
# One line of about the same length under the controls, whatever the choice, so the page does not jump (D-060).
st.caption(
    "Ceny przychodzą same, gdy giełda działa; tu ustawiasz, co ile odświeża się strona Portfel."
    if live_source == "stream" else
    "Najczęściej co 2 minuty, żeby Yahoo nie odrzucało zapytań; przy zamkniętych giełdach najwyżej co 5 minut."
)

section(
    "Zużycie zasobów",
    "Ile procesora i pamięci zużywa aplikacja na tym komputerze. Odświeża się co 5 sekund.",
    help=G["resources"],
)


@st.fragment(run_every=timedelta(seconds=5))
def resource_usage() -> None:
    """Reads the background monitor (D-073); the sampling itself runs in its own thread."""
    snapshot = get_monitor().snapshot()
    current, cores = snapshot.current, get_monitor().cpu_count
    machine = fmt_cpu(snapshot.cpu_1min / cores) if current else "–"
    health_tiles([
        HealthTile(
            "Procesor (1 rdzeń)", fmt_cpu(snapshot.cpu_1min),
            f"średnio 1 min · 5 min: {fmt_cpu(snapshot.cpu_5min)} · całość: {machine}",
            snapshot.cpu_level if current else "info", hover=G["resources_cpu"],
        ),
        HealthTile(
            "Pamięć", fmt_bytes(current.rss_bytes if current else None),
            f"{fmt_cpu(current.mem_pct)} pamięci komputera" if current else "–",
            snapshot.memory_level if current else "info", hover=G["resources_memory"],
        ),
        HealthTile(
            "Wątek cen na żywo", fmt_cpu(snapshot.feed_cpu_1min),
            "średnio 1 min" if preferences.online else "wyłączony (offline)",
            cpu_level(snapshot.feed_cpu_1min) if current else "info", hover=G["resources_feed"],
        ),
        HealthTile("Wątki", fmt_number(current.threads) if current else "–", "wszystkie wątki aplikacji"),
    ])
    hint = advice(snapshot.level, preferences.live_source, preferences.stream_seconds, preferences.online)
    # Always one line under the tiles, so the page does not jump when the level changes.
    if current is None and snapshot.warmup_left > 0:  # start-up is always heavy and is not measured (D-073)
        st.info(f"Aplikacja się uruchamia. Pomiar zacznie się za {snapshot.warmup_left:.0f} s, start go nie zawyża.",
                icon=":material/hourglass_top:")
    elif current is None:
        st.info("Zbieram pierwsze pomiary…", icon=":material/hourglass_top:")
    elif snapshot.level == "high":
        st.error(f"Wysokie zużycie. {hint}", icon=":material/warning:")
    elif snapshot.level == "warn":
        st.warning(f"Podwyższone zużycie. {hint}", icon=":material/info:")
    else:
        st.success("Zużycie w normie.", icon=":material/check_circle:")


resource_usage()

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
    mode != preferences.network or live_source != preferences.live_source or poll_seconds != preferences.poll_seconds
    or stream_seconds != preferences.stream_seconds or inbox_dir != preferences.inbox_dir
    or today_tile != preferences.today_tile
)
if st.button("Zapisz", type="primary", icon=":material/save:", disabled=not changed or not inbox_ok):
    save_preferences(settings, preferences.model_copy(update={
        "network": mode, "live_source": live_source, "poll_seconds": poll_seconds, "stream_seconds": stream_seconds,
        "inbox_dir": inbox_dir, "today_tile": today_tile,
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
        st.cache_resource.clear()  # the valued history (ui.data._history, D-071)
        st.session_state["reset_round"] = st.session_state.get("reset_round", 0) + 1
        st.session_state["reset_done"] = (
            f"Usunięto {plural(len(result.removed), 'plik', 'pliki', 'plików')}"
            + (" i zapisane dane rynkowe." if result.market_cleared else ".")
        )
        st.rerun()
