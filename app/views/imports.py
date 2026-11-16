"""Imports: add XTB exports, see accounts, operations, positions and import issues."""

from __future__ import annotations

from datetime import date

import streamlit as st
from ui.components import empty_state, page_header, section, table
from ui.fmt import fmt_date, fmt_money
from ui.glossary import G
from ui.manual_data import manual_data_section

from finance_analytics import reports
from finance_analytics.config import get_settings
from finance_analytics.preferences import PreferencesError, load_preferences
from finance_analytics.sources.inbox import InboxResult, check_inbox
from finance_analytics.sources.sync import store_xtb_file, sync
from finance_analytics.sources.xtb.parser import XtbFormatError

LEDGER_LABELS = {
    "DEPOSIT": "Wpłata", "WITHDRAWAL": "Wypłata", "BUY": "Kupno", "SELL": "Sprzedaż",
    "DIVIDEND": "Dywidenda", "WHT": "Podatek u źródła", "INTEREST": "Odsetki",
    "INTEREST_TAX": "Podatek od odsetek", "FEE": "Opłata", "OTHER": "Inne",
}
ACCOUNT_KIND = {"IKE": "IKE", "IKZE": "IKZE", None: "zwykły"}

page_header("Importy", "Eksporty z XTB, pliki CSV z ręcznymi danymi i to, co z nich trafiło do lokalnej bazy.")
settings = get_settings()

if not settings.db_path.exists():
    empty_state(
        "Brak lokalnej bazy danych",
        f"Nie znaleziono bazy w `{settings.data_dir}`.",
        icon=":material/database:",
        steps=["W terminalu, w katalogu projektu, uruchom `fa init`.", "Odśwież tę stronę."],
    )
    st.stop()


def _report_inbox(result: InboxResult | None) -> None:
    if result is None:
        return
    if result.error:
        st.warning(result.error, icon=":material/warning:")
        return
    if result.sync is not None and result.sync.errors:
        st.warning(f"Skopiowano {len(result.copied)} plik(ów), ale z błędami: {len(result.sync.errors)}.")
    elif result.copied:
        st.success(f"Zaimportowano nowych plików: {len(result.copied)}.", icon=":material/check_circle:")
    else:
        st.success("Brak nowych plików w folderze skrzynki.", icon=":material/check_circle:")
    for path, reason in result.skipped:
        st.warning(f"{path.name}: {reason}")


def _report_sync(result) -> None:
    if result.errors:
        st.error(f"Zaimportowano z błędami: {len(result.errors)}. Szczegóły niżej.", icon=":material/error:")
    elif result.rebuilt:
        st.toast("Baza przebudowana z plików.", icon=":material/check_circle:")
    else:
        st.toast("Bez zmian: pliki są już zaimportowane.", icon=":material/info:")


with st.container(border=True):
    st.markdown("#### :material/upload_file: Dodaj eksport XTB")
    st.caption(
        "Wskaż pliki .xlsx z folderu eksportu xStation (np. `USD_…xlsx`, `IKE_…xlsx`). "
        "Pliki zostają na tym komputerze: trafiają do `data/raw/xtb/` i do lokalnej bazy."
    )
    uploads = st.file_uploader(
        "Pliki eksportu", type="xlsx", accept_multiple_files=True, label_visibility="collapsed"
    )
    left, right = st.columns([1, 4])
    if left.button("Importuj", type="primary", disabled=not uploads, icon=":material/download:"):
        stored = 0
        for upload in uploads:
            try:
                _, written = store_xtb_file(upload.name, upload.getvalue(), settings)
                stored += written
            except XtbFormatError as exc:
                st.error(f"{upload.name}: {exc}")
        st.session_state["last_sync"] = sync(settings)
        st.session_state["last_stored"] = stored
    if right.button("Przebuduj bazę z plików", icon=":material/sync:", help="fa rebuild"):
        st.session_state["last_sync"] = sync(settings, force=True)
    try:
        inbox_dir = load_preferences(settings).inbox_dir
    except PreferencesError:
        inbox_dir = None
    if inbox_dir:
        st.caption(f"Skrzynka: `{inbox_dir}`. Nowe eksporty z tego folderu importują się same.")
        if st.button("Sprawdź folder teraz", icon=":material/refresh:"):
            _report_inbox(check_inbox(settings))

manual_data_section(settings)

if "last_sync" in st.session_state:
    _report_sync(st.session_state.pop("last_sync"))

issues = reports.issues(settings.db_path)
errors = issues[issues["severity"] == "error"]
for message in errors["message"]:
    st.error(message, icon=":material/error:")
warnings = issues[issues["severity"] == "warning"]
if not warnings.empty:
    with st.expander(f":material/warning: Ostrzeżenia z importu ({len(warnings)})"):
        for message in warnings["message"]:
            st.markdown(f"- {message}")

overview = reports.accounts_overview(settings.db_path)
if overview.empty:
    empty_state(
        "Nie ma jeszcze zaimportowanych rachunków",
        "Dodaj pliki powyżej albo zaimportuj cały folder poleceniem `fa import xtb <folder>`.",
        icon=":material/account_balance:",
    )
    st.stop()

section("Rachunki", "Saldo gotówki to suma operacji w walucie rachunku.")
accounts_view = overview.assign(
    rodzaj=overview["tax_wrapper"].fillna("").map(lambda w: ACCOUNT_KIND.get(w or None, w)),
    numer=overview["external_no"].map(lambda n: f"…{n[-3:]}" if isinstance(n, str) and n else ""),
    zakres=[
        f"{fmt_date(date.fromisoformat(a))} – {fmt_date(date.fromisoformat(b))}" if isinstance(a, str) else "–"
        for a, b in zip(overview["date_from"], overview["date_to"], strict=True)
    ],
    gotowka=[fmt_money(v, c) for v, c in zip(overview["cash"], overview["currency"], strict=True)],
)
table(
    accounts_view[["alias", "rodzaj", "currency", "numer", "zakres", "files", "operations", "open_positions",
                   "closed_positions", "gotowka"]],
    labels={
        "alias": "Rachunek", "rodzaj": "Rodzaj", "currency": "Waluta", "numer": "Numer", "zakres": "Okres",
        "files": "Pliki", "operations": "Operacje", "open_positions": "Pozycje otwarte",
        "closed_positions": "Zamknięte", "gotowka": "Gotówka",
    },
    helps={"rodzaj": f'{G["account_kind"]} {G["ike"]} {G["ikze"]}', "gotowka": G["account_cash"],
           "open_positions": G["position"]},
)

section("Szczegóły rachunku")
labels = dict(zip(overview["id"], overview["alias"], strict=True))
account_id = st.selectbox("Rachunek", list(labels), format_func=labels.get, label_visibility="collapsed")
currency = overview.set_index("id").loc[account_id, "currency"]
ops_tab, open_tab, closed_tab = st.tabs(["Operacje gotówkowe", "Pozycje otwarte", "Pozycje zamknięte"])

with ops_tab:
    ledger = reports.cash_ledger(settings.db_path, account_id)
    kinds = st.multiselect(
        "Typ operacji",
        sorted(ledger["type"].unique(), key=list(LEDGER_LABELS).index),
        format_func=LEDGER_LABELS.get,
        placeholder="Wszystkie typy",
        help=f'Filtruj operacje po typie. {G["wht"]}',
    )
    shown = ledger[ledger["type"].isin(kinds)] if kinds else ledger
    table(
        shown.assign(typ=shown["type"].map(LEDGER_LABELS))[["ts", "typ", "symbol", "name", "amount", "comment"]],
        numbers={"amount": 2},
        signed=["amount"],
        datetimes=["ts"],
        labels={
            "ts": "Czas (UTC)", "typ": "Typ", "symbol": "Ticker", "name": "Instrument",
            "amount": f"Kwota ({currency})", "comment": "Komentarz",
        },
        helps={"symbol": G["ticker"], "amount": "Wpływ (+) lub wypływ (−) gotówki w walucie rachunku."},
    )

position_labels = {
    "symbol": "Ticker", "name": "Instrument", "volume": "Ilość", "open_time": "Otwarcie (UTC)",
    "open_price": "Cena otwarcia", "close_time": "Zamknięcie (UTC)", "close_price": "Cena zamknięcia",
    "purchase_value": f"Koszt ({currency})", "sale_value": f"Sprzedaż ({currency})", "result": f"Wynik ({currency})",
}
with open_tab:
    opened = reports.positions(settings.db_path, account_id, open_only=True)
    table(
        opened[["symbol", "name", "volume", "open_time", "open_price", "purchase_value"]],
        numbers={"volume": 4, "open_price": 2, "purchase_value": 2},
        datetimes=["open_time"],
        labels=position_labels,
        helps={"symbol": G["ticker"], "purchase_value": "Ile zapłaciłeś, w walucie rachunku (z przewalutowaniem)."},
    )
with closed_tab:
    closed = reports.positions(settings.db_path, account_id, open_only=False)
    if closed.empty:
        st.caption("Brak zamkniętych pozycji w zaimportowanych plikach.")
    else:
        closed = closed.assign(result=closed["sale_value"] - closed["purchase_value"])
        table(
            closed[["symbol", "name", "volume", "open_time", "open_price", "close_time", "close_price",
                    "purchase_value", "sale_value", "result"]],
            numbers={"volume": 4, "open_price": 2, "close_price": 2, "purchase_value": 2, "sale_value": 2,
                     "result": 2},
            signed=["result"],
            datetimes=["open_time", "close_time"],
            labels=position_labels,
        )
