"""Developer page (FA_DEV=1): every UI building block on synthetic data.

Used to tune the look in light and dark mode before real data exists. All numbers
here are generated; nothing is read from the data directory.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st
from ui.charts import area_total, current_mode, line_chart, show, stacked_bars
from ui.components import Kpi, kpi_row, page_header, section
from ui.fmt import fmt_money, fmt_money_compact, fmt_pct


@st.cache_data
def synthetic_accounts(seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    days = pd.date_range("2023-01-02", "2026-11-13", freq="B")
    start = {"XTB PLN": 40_000, "XTB USD": 25_000, "XTB EUR": 12_000, "IKE": 18_000}
    frame = {}
    for i, (name, value) in enumerate(start.items()):
        returns = rng.normal(0.0004 + 0.0001 * i, 0.009 + 0.002 * i, len(days))
        contributions = np.where(rng.random(len(days)) < 0.02, value * 0.05, 0.0)
        frame[name] = np.maximum(value * np.cumprod(1 + returns) + np.cumsum(contributions), 0)
    return pd.DataFrame(frame, index=days)


mode = current_mode()
accounts = synthetic_accounts()
total = accounts.sum(axis=1)
year_start = total[total.index >= f"{total.index[-1].year}-01-01"].iloc[0]

page_header("Podgląd stylu", "Dane syntetyczne. Strona widoczna tylko z FA_DEV=1.")

kpi_row(
    [
        Kpi("Wartość portfela", fmt_money_compact(total.iloc[-1]),
            delta=fmt_pct(total.iloc[-1] / total.iloc[-2] - 1, 2), help="Zmiana od poprzedniej sesji",
            trend=total.resample("ME").last().tail(12).round(0).tolist()),
        Kpi("Od początku roku", fmt_money(total.iloc[-1] - year_start, decimals=0, signed=True),
            delta=fmt_pct(total.iloc[-1] / year_start - 1), help="Zmiana wartości od 1 stycznia"),
        Kpi("Wpłacony kapitał", fmt_money_compact(95_000)),
        Kpi("Zysk", fmt_money_compact(total.iloc[-1] - 95_000), delta=fmt_pct(-0.0123), help="Przykład ujemnej zmiany"),
    ]
)

section("Wartość portfela", "Jedna seria: linia z delikatnym wypełnieniem.")
show(area_total(total, name="Portfel", mode=mode), key="area")

section("Wartość rachunków", "Kilka serii: kolor przypisany do rachunku, nie do pozycji w rankingu.")
show(line_chart(accounts, mode=mode), key="lines")

section("Skład portfela w czasie", "Wartość na koniec miesiąca, segmenty oddzielone odstępem.")
show(stacked_bars(accounts.resample("ME").last().tail(18), mode=mode), key="bars")
