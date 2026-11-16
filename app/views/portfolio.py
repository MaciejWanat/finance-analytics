"""Portfolio: value of everything in PLN, day by day."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date

import pandas as pd
import streamlit as st
from ui.charts import area_total, current_mode, segmented_bar, show, stacked_bars
from ui.components import Kpi, empty_state, kpi_row, page_header, section, table
from ui.fmt import fmt_money, fmt_money_compact, fmt_pct
from ui.theme import OTHER_LABEL, color_map

from finance_analytics import reports
from finance_analytics.config import get_settings
from finance_analytics.portfolio.valuation import Valuation, data_version, load_inputs, value_portfolio

RANGES = ["1M", "3M", "YTD", "1R", "3L", "Maks."]
BREAKDOWNS = {"Rachunek": "account", "Klasa aktywów": "asset_class", "Instrument": "symbol", "Waluta": "currency"}
ASSET_CLASS_LABELS = {"stock": "Akcje", "etf": "ETF", "bond": "Obligacje", "cash": "Gotówka", "other": "Inne"}
MAX_PARTS = 8

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

if reports.accounts_overview(settings.db_path).empty:
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

with closing(sqlite3.connect(settings.db_path)) as conn:
    has_prices = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0] > 0
if not has_prices:
    empty_state(
        "Brakuje cen i kursów walut",
        "Do wyceny w PLN potrzebne są notowania instrumentów i kursy NBP. Pobierz je jednym kliknięciem.",
        icon=":material/candlestick_chart:",
    )
    st.page_link("views/market.py", label="Przejdź do danych rynkowych", icon=":material/arrow_forward:")
    st.stop()


@st.cache_data(show_spinner="Liczę wycenę portfela…")
def valuation(db_path: str, version: tuple, today: date) -> Valuation:
    from pathlib import Path

    return value_portfolio(load_inputs(Path(db_path)), today)


v = valuation(str(settings.db_path), data_version(settings.db_path), date.today())
daily, total = v.daily, v.total
if total.empty:
    st.info("Brak pozycji i operacji do wyceny.")
    st.stop()

# ------------------------------------------------------------------- period filter (scopes the whole page)
period = st.segmented_control("Okres", RANGES, default="Maks.", key="period", required=True)

end = total.index[-1]
start = {
    "1M": end - pd.DateOffset(months=1), "3M": end - pd.DateOffset(months=3),
    "YTD": pd.Timestamp(end.year, 1, 1) - pd.Timedelta(days=1), "1R": end - pd.DateOffset(years=1),
    "3L": end - pd.DateOffset(years=3), "Maks.": total.index[0],
}[period]
start = max(start, total.index[0])
window = total[total.index >= start]
flows = v.flows.set_index("date")["amount_pln"].sort_index()

# ------------------------------------------------------------------------------------------- KPIs
value_now = total.iloc[-1]
in_window = flows[(flows.index > start) & (flows.index <= end)].sum()
result = value_now - window.iloc[0] - in_window
base = window.iloc[0] + max(in_window, 0)
contributed = flows.sum()

# Every tile gets a sparkline over the selected period, so the tiles line up and read alike.
cumulative_flows = flows.groupby(level=0).sum().reindex(total.index, fill_value=0.0).cumsum()
step = "W-FRI" if (end - start).days <= 180 else "ME"


def trend(series: pd.Series) -> list[float]:
    return series[series.index >= start].resample(step).last().dropna().round(0).tolist()


period_result = total - window.iloc[0] - (cumulative_flows - cumulative_flows.asof(start))
kpi_row(
    [
        Kpi("Wartość portfela", fmt_money_compact(value_now),
            delta=fmt_money_compact(value_now - window.iloc[0]).replace("−", "-") + " w okresie",
            help="Przyrost wartości w wybranym okresie, razem z wpłatami (procent byłby mylący przy "
                 "małej wartości startowej).", trend=trend(total)),
        Kpi("Wynik w okresie", fmt_money(result, decimals=0, signed=True),
            delta=fmt_pct(result / base) if base > 0 else None,
            help="Zmiana wartości w wybranym okresie minus wpłaty i wypłaty. Uproszczona stopa zwrotu; "
                 "TWR i XIRR dojdą w kolejnym kroku.", trend=trend(period_result)),
        Kpi("Wpłacony kapitał", fmt_money_compact(contributed), delta_color="off",
            delta=fmt_money_compact(in_window) + " w okresie" if in_window else None,
            help="Suma wpłat minus wypłaty, w PLN po kursie NBP z dnia operacji.", trend=trend(cumulative_flows)),
        Kpi("Zysk całkowity", fmt_money_compact(value_now - contributed),
            delta=fmt_pct((value_now - contributed) / contributed) if contributed > 0 else None,
            help="Wartość portfela minus wpłacony kapitał.", trend=trend(total - cumulative_flows)),
    ]
)

mode = current_mode()

# -------------------------------------------------------------------------------- value over time
section("Wartość portfela", f"W PLN, od {window.index[0]:%d.%m.%Y} do {end:%d.%m.%Y}.")
show(area_total(window, name="Portfel", mode=mode, height=340), key="total")

# ---------------------------------------------------------------------------- composition and parts
# The breakdown filter sits right above the charts it changes.
breakdown = st.segmented_control("Podział", list(BREAKDOWNS), default="Rachunek", key="breakdown", required=True)
column = BREAKDOWNS[breakdown]
labelled = daily.assign(part=daily[column])
if column == "asset_class":
    labelled["part"] = labelled["part"].map(ASSET_CLASS_LABELS).fillna(labelled["part"])
wide = labelled.pivot_table(index="date", columns="part", values="value_pln", aggfunc="sum").fillna(0.0)
latest = wide.iloc[-1].sort_values(ascending=False)
parts = sorted(latest.index)  # colour follows the entity, assigned in a stable (alphabetical) order
if len(parts) > MAX_PARTS:
    kept = sorted(latest.index[: MAX_PARTS - 1])
    wide[OTHER_LABEL] = wide.drop(columns=kept).sum(axis=1)
    wide, parts = wide[kept + [OTHER_LABEL]], kept + [OTHER_LABEL]
colors = color_map([p for p in parts if p != OTHER_LABEL], mode)

window_days = (end - start).days
frequency, frequency_label = ("W-FRI", "tygodnia") if window_days <= 100 else ("ME", "miesiąca")
bars = wide[wide.index >= start][parts].resample(frequency).last()

left, right = st.columns([3, 2], gap="large")
with left:
    section(f"Skład portfela: {breakdown.lower()}", f"Wartość na koniec każdego {frequency_label}, w PLN.")
    show(stacked_bars(bars, mode=mode, colors=colors, height=340), key="composition")
with right:
    section("Alokacja dziś", f"{breakdown}: udział w wartości portfela.")
    today_parts = wide.iloc[-1][parts]
    show(segmented_bar(today_parts.sort_values(ascending=False), mode=mode, colors=colors), key="allocation")
    shares = today_parts.sort_values(ascending=False)
    table(
        pd.DataFrame({"part": shares.index, "value": shares.to_numpy(), "share": (shares / shares.sum()).to_numpy()}),
        numbers={"value": 0},
        percents=["share"],
        labels={"part": breakdown, "value": "Wartość (zł)", "share": "Udział"},
    )

# ------------------------------------------------------------------------------- current holdings
section("Bieżące pozycje", "Wartość po ostatnim kursie zamknięcia i kursie NBP; koszt po kursie z dnia zakupu.")
last_day = daily[(daily["date"] == end) & (daily["kind"] == "position")]
holdings = last_day.groupby(["account", "symbol", "name", "currency"], as_index=False).agg(
    qty=("qty", "sum"), price=("price", "last"), value=("value_pln", "sum")
)
open_lots = v.lots[v.lots["close_date"].isna()].assign(account=lambda d: d["account_id"].map(
    daily.drop_duplicates("account_id").set_index("account_id")["account"]))
cost = open_lots.groupby(["account", "symbol"])["cost_pln"].sum()
holdings["cost"] = [cost.get((a, s)) for a, s in zip(holdings["account"], holdings["symbol"], strict=True)]
holdings["pnl"] = holdings["value"] - holdings["cost"]
holdings["pnl_pct"] = holdings["pnl"] / holdings["cost"]
holdings["share"] = holdings["value"] / value_now
recent = daily[(daily["kind"] == "position") & (daily["date"] > end - pd.Timedelta(days=90))]
trend = recent.groupby(["account", "symbol", "date"])["value_pln"].sum()
holdings["trend"] = [trend.loc[(a, s)].round(0).tolist() for a, s in zip(holdings["account"], holdings["symbol"],
                                                                          strict=True)]
holdings = holdings.sort_values("value", ascending=False)
table(
    holdings[["symbol", "account", "name", "qty", "price", "currency", "value", "share", "cost", "pnl", "pnl_pct",
              "trend"]],
    numbers={"qty": 4, "price": 2, "value": 2, "cost": 2, "pnl": 2},
    percents=["share", "pnl_pct"],
    signed=["pnl", "pnl_pct"],
    trends=["trend"],
    labels={
        "account": "Rachunek", "symbol": "Ticker", "name": "Instrument", "qty": "Ilość", "price": "Kurs",
        "currency": "Waluta", "value": "Wartość (zł)", "share": "Udział", "cost": "Koszt (zł)",
        "pnl": "Wynik (zł)", "pnl_pct": "Wynik %", "trend": "90 dni",
    },
)

if v.warnings:
    with st.expander(f":material/warning: Uwagi do wyceny ({len(v.warnings)})"):
        for warning in v.warnings:
            st.markdown(f"- {warning}")
