"""Dividends: gross, withholding tax, net, in PLN; over time, per company and per tax year (D-024)."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from ui.charts import current_mode, show, stacked_bars
from ui.components import Kpi, empty_state, kpi_row, page_header, section, table
from ui.data import RANGES, load_valuation, period_start, require_valued_data
from ui.fmt import fmt_date, fmt_money, fmt_money_compact, fmt_pct, plural
from ui.glossary import G
from ui.theme import OTHER_LABEL, color_map

from finance_analytics.config import get_settings
from finance_analytics.portfolio.dividends import load_events, payments, per_company, per_year
from finance_analytics.portfolio.valuation import data_version

MAX_COMPANIES = 8

page_header("Dywidendy", "Ile wypłaciły Ci spółki: brutto, podatek u źródła i na rękę, w złotych.")
settings = get_settings()
require_valued_data(settings, "wypłacone dywidendy, podatek i ich historię")


@st.cache_data(show_spinner=False)
def dividend_payments(db_path: str, version: tuple) -> pd.DataFrame:
    from pathlib import Path

    events, fx = load_events(Path(db_path))
    return payments(events, fx)


v, _ = load_valuation(settings)
paid = dividend_payments(str(settings.db_path), data_version(settings.db_path))
if paid.empty:
    empty_state(
        "Nie ma jeszcze dywidend",
        "W zaimportowanych operacjach nie ma wypłat dywidend. Pojawią się tu po imporcie eksportu, "
        "który je obejmuje.",
        icon=":material/payments:",
    )
    st.stop()

period = st.segmented_control("Okres", RANGES, default="Maks.", key="dividends_period", required=True,
                              help=G["periods"])
end = v.total.index[-1]
start = period_start(period, min(paid["date"].min(), v.total.index[0]), end)
window = paid[(paid["date"] > start) & (paid["date"] <= end)] if period != "Maks." else paid

if paid["rate"].isna().any():
    st.warning("Brakuje kursów NBP dla części wypłat; przelicz je po pobraniu danych rynkowych.",
               icon=":material/warning:")

# ------------------------------------------------------------------------------------------- KPIs
last_year = paid[paid["date"] > end - pd.DateOffset(years=1)]
monthly = paid.set_index("date")[["net_pln", "wht_pln", "tax_due_pln"]].resample("ME").sum()
in_window = monthly[monthly.index > start] if period != "Maks." else monthly


def running(column: str) -> list[float]:
    """Cumulative monthly sum within the period, for the tile sparkline."""
    return in_window[column].cumsum().round(0).tolist()


kpi_row(
    [
        Kpi("Dywidendy netto", fmt_money(window["net_pln"].sum(), decimals=0), delta_color="off",
            delta=plural(len(window), "wypłata", "wypłaty", "wypłat"), help=G["dividend_net"],
            trend=running("net_pln")),
        Kpi("Podatek u źródła", fmt_money(window["wht_pln"].sum(), decimals=0), delta_color="off",
            delta=f"{fmt_pct(window['wht_pln'].sum() / window['gross_pln'].sum(), 1, signed=False)} brutto"
            if window["gross_pln"].sum() else None,
            help=G["wht"], trend=running("wht_pln")),
        Kpi("Do dopłaty w PIT-38 (szac.)", fmt_money(window["tax_due_pln"].sum(), decimals=0), delta_color="off",
            help=G["tax_due"], trend=running("tax_due_pln")),
        Kpi("Ostatnie 12 mies. netto", fmt_money_compact(last_year["net_pln"].sum()), delta_color="off",
            delta=f"{fmt_pct(last_year['net_pln'].sum() / v.total.iloc[-1], 2, signed=False)} wartości portfela",
            help=G["dividend_yield"], trend=monthly["net_pln"].tail(12).round(0).tolist()),
    ]
)

mode = current_mode()

# --------------------------------------------------------------------------------- over time
section("Dywidendy w czasie", "Netto w PLN, suma w każdym miesiącu, według spółki.", help=G["dividend_net"])
by_month = window.pivot_table(index="date", columns="symbol", values="net_pln", aggfunc="sum").resample("ME").sum()
by_month = by_month.reindex(pd.date_range(by_month.index.min(), by_month.index.max(), freq="ME"), fill_value=0.0)
totals = by_month.sum().sort_values(ascending=False)
companies = sorted(totals.index)
if len(companies) > MAX_COMPANIES:
    kept = sorted(totals.index[: MAX_COMPANIES - 1])
    by_month[OTHER_LABEL] = by_month.drop(columns=kept).sum(axis=1)
    by_month, companies = by_month[kept + [OTHER_LABEL]], kept + [OTHER_LABEL]
colors = color_map([c for c in companies if c != OTHER_LABEL], mode)
show(stacked_bars(by_month[companies], mode=mode, colors=colors, height=320), key="dividends_by_month")

# ------------------------------------------------------------------------------- per company
section("Spółki", "Suma wypłat w wybranym okresie.", help=G["dividend_payments"])
companies_table = per_company(window)
table(
    companies_table[["symbol", "name", "payments", "gross_pln", "wht_pln", "wht_rate", "net_pln", "tax_due_pln",
                     "last"]].assign(last=companies_table["last"].map(fmt_date)),
    numbers={"payments": 0, "gross_pln": 2, "wht_pln": 2, "net_pln": 2, "tax_due_pln": 2},
    percents=["wht_rate"],
    labels={"symbol": "Ticker", "name": "Spółka", "payments": "Wypłaty", "gross_pln": "Brutto (zł)",
            "wht_pln": "Podatek u źródła (zł)", "wht_rate": "Stawka", "net_pln": "Netto (zł)",
            "tax_due_pln": "Do dopłaty (zł)", "last": "Ostatnia"},
    helps={"symbol": G["ticker"], "payments": G["dividend_payments"], "gross_pln": G["dividend_gross"],
           "wht_pln": G["wht"], "wht_rate": G["wht_rate"], "net_pln": G["dividend_net"], "tax_due_pln": G["tax_due"]},
)

# ------------------------------------------------------------------------------------ tax years
section("Lata podatkowe", "Podsumowanie do zeznania: rok wypłaty, kwoty w PLN po kursie NBP z dnia D-1.",
        help=G["tax_due"])
table(
    per_year(paid).assign(year=lambda d: d["year"].astype(str)),
    numbers={"gross_pln": 2, "wht_pln": 2, "net_pln": 2, "tax_due_pln": 2},
    labels={"year": "Rok", "gross_pln": "Brutto (zł)", "wht_pln": "Podatek u źródła (zł)", "net_pln": "Netto (zł)",
            "tax_due_pln": "Do dopłaty w PIT-38 (zł)"},
    helps={"gross_pln": G["dividend_gross"], "wht_pln": G["wht"], "tax_due_pln": G["tax_due"]},
)
st.caption(
    ":material/info: Szacunek pomocniczy, nie porada podatkowa. Przed złożeniem zeznania porównaj kwoty "
    "z rocznym zestawieniem od brokera."
)

with st.expander(":material/list: Wszystkie wypłaty w okresie"):
    table(
        window.sort_values("date", ascending=False)[["date", "account", "symbol", "gross", "wht", "net", "currency",
                                                     "rate", "net_pln", "tax_due_pln"]]
        .assign(date=lambda d: d["date"].map(fmt_date)),
        numbers={"gross": 2, "wht": 2, "net": 2, "rate": 4, "net_pln": 2, "tax_due_pln": 2},
        labels={"date": "Data", "account": "Rachunek", "symbol": "Ticker", "gross": "Brutto", "wht": "Podatek",
                "net": "Netto", "currency": "Waluta", "rate": "Kurs D-1", "net_pln": "Netto (zł)",
                "tax_due_pln": "Do dopłaty (zł)"},
        helps={"rate": G["dividend_rate"], "tax_due_pln": G["tax_due"]},
    )
