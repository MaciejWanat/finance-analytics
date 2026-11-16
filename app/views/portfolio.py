"""Portfolio overview. Krok 0: only the empty states; the valuation arrives in Krok 4."""

from __future__ import annotations

import sqlite3
from contextlib import closing

from ui.components import empty_state, page_header

from finance_analytics.config import get_settings

page_header("Portfel", "Wartość wszystkich rachunków w PLN, dzień po dniu.")

settings = get_settings()

if not settings.db_path.exists():
    empty_state(
        "Brak lokalnej bazy danych",
        "Aplikacja nie znalazła bazy w katalogu danych "
        f"`{settings.data_dir}`. Utwórz ją jednym poleceniem:",
        icon=":material/database:",
        steps=["W terminalu, w katalogu projektu, uruchom `fa init`.", "Odśwież tę stronę."],
    )
else:
    with closing(sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)) as conn:
        account_count = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]

    if account_count == 0:
        empty_state(
            "Nie ma jeszcze danych do pokazania",
            "Po zaimportowaniu historii konta z XTB zobaczysz tu wartość portfela w czasie, "
            "podział na rachunki i klasy aktywów oraz bieżące pozycje.",
            icon=":material/upload_file:",
            steps=[
                "W xStation wyeksportuj historię konta: powstanie folder z podfolderami kont.",
                "Zaimportuj ten folder poleceniem `fa import xtb <folder>` (w przygotowaniu).",
            ],
        )
