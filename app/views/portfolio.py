"""Portfolio overview. Until valuation exists (step 4) it shows what was imported."""

from __future__ import annotations

import streamlit as st
from ui.components import Kpi, empty_state, kpi_row, page_header, section, table
from ui.fmt import fmt_number

from finance_analytics import reports
from finance_analytics.config import get_settings

page_header("Portfel", "Wartość wszystkich rachunków w PLN, dzień po dniu.")

settings = get_settings()

if not settings.db_path.exists():
    empty_state(
        "Brak lokalnej bazy danych",
        f"Aplikacja nie znalazła bazy w katalogu danych `{settings.data_dir}`. Utwórz ją jednym poleceniem:",
        icon=":material/database:",
        steps=["W terminalu, w katalogu projektu, uruchom `fa init`.", "Odśwież tę stronę."],
    )
    st.stop()

overview = reports.accounts_overview(settings.db_path)
if overview.empty:
    empty_state(
        "Nie ma jeszcze danych do pokazania",
        "Po zaimportowaniu historii konta z XTB zobaczysz tu wartość portfela w czasie, "
        "podział na rachunki i klasy aktywów oraz bieżące pozycje.",
        icon=":material/upload_file:",
        steps=[
            "W xStation wyeksportuj historię konta: powstanie folder z podfolderami kont.",
            "Zaimportuj go na stronie **Importy** albo poleceniem `fa import xtb <folder>`.",
        ],
    )
    st.page_link("views/imports.py", label="Przejdź do importu", icon=":material/arrow_forward:")
    st.stop()

holdings = reports.holdings(settings.db_path)
kpi_row(
    [
        Kpi("Rachunki", fmt_number(len(overview))),
        Kpi("Instrumenty w portfelu", fmt_number(holdings["symbol"].nunique())),
        Kpi("Otwarte pozycje", fmt_number(int(overview["open_positions"].sum()))),
        Kpi("Operacje gotówkowe", fmt_number(int(overview["operations"].sum()))),
    ]
)

st.info(
    "Wycena w PLN pojawi się w kolejnym kroku: aplikacja pobierze ceny instrumentów (Yahoo) i kursy walut "
    "(NBP), a potem policzy wartość portfela na każdy dzień.",
    icon=":material/hourglass_top:",
)

section("Bieżące pozycje", "Łączna ilość per rachunek i instrument, koszt w walucie rachunku.")
table(
    holdings,
    numbers={"volume": 4, "lots": 0, "cost": 2},
    labels={
        "account": "Rachunek", "symbol": "Ticker", "name": "Instrument", "asset_class": "Klasa",
        "volume": "Ilość", "lots": "Pozycje", "cost": "Koszt", "currency": "Waluta",
    },
)
