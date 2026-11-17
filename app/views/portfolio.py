"""Portfolio: value of everything in PLN, day by day."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from ui.charts import area_total, current_mode, segmented_bar, show, stacked_bars
from ui.components import Kpi, kpi_row, page_header, section, table
from ui.data import RANGES, load_valuation, period_start, require_valued_data
from ui.fmt import fmt_money, fmt_money_compact, fmt_pct
from ui.glossary import G
from ui.theme import OTHER_LABEL, color_map

from finance_analytics import reports
from finance_analytics.config import get_settings
from finance_analytics.portfolio import inflation
from finance_analytics.portfolio.returns import period_return, twr_index

BREAKDOWNS = {"Rachunek": "account", "Klasa aktywów": "asset_class", "Instrument": "symbol", "Waluta": "currency"}
# Fixed order = fixed palette slot per class, so a class keeps its colour whatever else the portfolio holds.
# "other" is shown as OTHER_LABEL and gets the neutral colour.
ASSET_CLASS_LABELS = {
    "stock": "Akcje", "etf": "ETF", "bond": "Obligacje", "precious_metals": "Metale szlachetne", "cash": "Gotówka",
    "other": OTHER_LABEL,
}
MAX_PARTS = 8

page_header("Portfel", "Wartość wszystkich rachunków w PLN, dzień po dniu.")
settings = get_settings()
require_valued_data(settings, "wartość portfela w czasie, podział na rachunki i klasy aktywów oraz bieżące pozycje")
v, live_at = load_valuation(settings)
daily, total = v.daily, v.total

# ------------------------------------------------------------------- period filter (scopes the whole page)
period = st.segmented_control("Okres", RANGES, default="Maks.", key="period", required=True, help=G["periods"])

end = total.index[-1]
start = period_start(period, total.index[0], end)
window = total[total.index >= start]
flows = v.flows.set_index("date")["amount_pln"].sort_index()

# ------------------------------------------------------------------------------------------- KPIs
value_now = total.iloc[-1]
in_window = flows[(flows.index > start) & (flows.index <= end)].sum()
result = value_now - window.iloc[0] - in_window
twr_period = period_return(twr_index(total, flows), start, end)
contributed = flows.sum()

# Inflation (D-025, D-041): the price level per day, from the saved GUS CPI; nothing without it.
cpi = reports.cpi_monthly(settings.db_path)
levels, daily_cpi = inflation.daily_from_cpi(cpi, total.index) if not cpi.empty else (None, None)
real = inflation.real_profit(total, flows, daily_cpi, None, end) if daily_cpi is not None else None
if real is None:
    real_delta = "realnie: brak CPI" if cpi.empty else "realnie: –"
else:
    real_delta = f"realnie {'+' if real.profit >= 0 else ''}{fmt_money_compact(real.profit)}"
real_help = G["total_gain"] + " Pod spodem zysk realny: " + G["real_profit"]
if real is not None:
    real_help += (f" Teraz: {fmt_money(real.profit, decimals=0, signed=True)}"
                  + (f", {fmt_pct(real.pct)} wpłat w dzisiejszych złotych." if real.pct is not None else "."))

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
            delta=f"{fmt_pct(twr_period)} TWR",
            help=G["result_period"],
            trend=trend(period_result)),
        Kpi("Wpłacony kapitał", fmt_money_compact(contributed), delta_color="off",
            delta=fmt_money_compact(in_window) + " w okresie" if in_window else None,
            help=G["contributed"], trend=trend(cumulative_flows)),
        # Nominal profit as the value, profit after inflation ("na czysto") as the delta (D-041).
        Kpi("Zysk całkowity", fmt_money_compact(value_now - contributed),
            delta=real_delta, delta_color="normal" if real is not None else "off",
            help=real_help,
            trend=trend(total - cumulative_flows)),
    ]
)

mode = current_mode()

# -------------------------------------------------------------------------------- value over time
live_note = f" Dzisiejsza wartość na żywo: ceny z {live_at.astimezone():%H:%M}." if live_at else ""
section("Wartość portfela", f"W PLN, od {window.index[0]:%d.%m.%Y} do {end:%d.%m.%Y}.{live_note}",
        help=G["portfolio_value"])
CHART_HEIGHT = 340
NOTE_HEIGHT = 48


@st.fragment
def value_over_time() -> None:
    """Toggle + chart in a fragment: flipping the toggle reruns only this block, so the rest of the page stays
    put. The chart slot has a fixed height and the note line is always present, so the layout never shifts."""
    real_view = st.toggle(
        "W dzisiejszych złotych", value=False, key="todays_pln", help=G["todays_pln"], disabled=cpi.empty,
    )
    note, note_help = "Wartości nominalne, w złotych z danego dnia.", None
    shown = window
    note_slot = st.container(height=NOTE_HEIGHT, border=False)  # reserves two lines whatever the note says
    slot = st.container(height=CHART_HEIGHT + 16, border=False)
    if cpi.empty:
        note = "Brak danych o inflacji (CPI z GUS): pobierz je w trybie online na stronie Dane rynkowe."
    elif real_view:
        with slot, st.spinner("Przeliczam na dzisiejsze złote…"):
            shown = inflation.todays_zloty(window, daily_cpi)
        note = f"Wartości w złotych z {end:%m.%Y}, czyli po uwzględnieniu wzrostu cen od danego dnia."
        if daily_cpi["estimated"].iloc[-1]:
            note += " (miesiąc bez opublikowanego CPI: ostatnia inflacja r/r)"
            note_help = G["cpi_estimated"]
    with note_slot:
        st.caption(note, help=note_help)
    with slot:
        show(area_total(shown, name="Portfel", mode=mode, height=CHART_HEIGHT), key="total")


value_over_time()

# ---------------------------------------------------------------------------- composition and parts
# The breakdown filter sits right above the charts it changes.
breakdown = st.segmented_control(
    "Podział", list(BREAKDOWNS), default="Klasa aktywów", key="breakdown", required=True, help=G["breakdown"]
)
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
if column == "asset_class":
    colors = color_map([label for label in ASSET_CLASS_LABELS.values() if label != OTHER_LABEL], mode)
else:
    colors = color_map([p for p in parts if p != OTHER_LABEL], mode)

window_days = (end - start).days
frequency, frequency_label = ("W-FRI", "tygodnia") if window_days <= 100 else ("ME", "miesiąca")
bars = wide[wide.index >= start][parts].resample(frequency).last()

left, right = st.columns([3, 2], gap="large")
with left:
    section(f"Skład portfela: {breakdown.lower()}", f"Wartość na koniec każdego {frequency_label}, w PLN.",
            help=G["composition"])
    show(stacked_bars(bars, mode=mode, colors=colors, height=340), key="composition")
with right:
    section("Alokacja dziś", f"{breakdown}: udział w wartości portfela.",
            help=G["asset_class"] if column == "asset_class" else G["allocation"])
    today_parts = wide.iloc[-1][parts]
    show(segmented_bar(today_parts.sort_values(ascending=False), mode=mode, colors=colors), key="allocation")
    shares = today_parts.sort_values(ascending=False)
    table(
        pd.DataFrame({"part": shares.index, "value": shares.to_numpy(), "share": (shares / shares.sum()).to_numpy()}),
        numbers={"value": 0},
        percents=["share"],
        labels={"part": breakdown, "value": "Wartość (zł)", "share": "Udział"},
        helps={"share": G["share"]},
    )

# ------------------------------------------------------------------------------- current holdings
section("Bieżące pozycje", "Wartość po ostatnim kursie zamknięcia i kursie NBP; koszt po kursie z dnia zakupu.",
        help=G["position"])
last_day = daily[(daily["date"] == end) & (daily["kind"] == "position")]
holdings = last_day.groupby(["account", "symbol", "name", "asset_class", "currency"], as_index=False).agg(
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
holdings["asset_class"] = holdings["asset_class"].map(ASSET_CLASS_LABELS).fillna(holdings["asset_class"])
holdings = holdings.sort_values("value", ascending=False)
table(
    holdings[["symbol", "account", "name", "asset_class", "qty", "price", "currency", "value", "share", "cost", "pnl",
              "pnl_pct", "trend"]],
    numbers={"qty": 4, "price": 2, "value": 2, "cost": 2, "pnl": 2},
    percents=["share", "pnl_pct"],
    signed=["pnl", "pnl_pct"],
    trends=["trend"],
    missing_labels={"cost": "unknown"},
    labels={
        "account": "Rachunek", "symbol": "Ticker", "name": "Instrument", "asset_class": "Klasa", "qty": "Ilość",
        "price": "Kurs",
        "currency": "Waluta", "value": "Wartość (zł)", "share": "Udział", "cost": "Koszt (zł)",
        "pnl": "Wynik (zł)", "pnl_pct": "Wynik %", "trend": "90 dni",
    },
    helps={"symbol": G["ticker"], "asset_class": G["asset_class"], "price": G["last_price"], "cost": G["cost"],
           "pnl": G["pnl"], "pnl_pct": G["pnl"], "share": G["share"], "trend": G["trend_90"]},
)

if v.warnings:
    with st.expander(f":material/warning: Uwagi do wyceny ({len(v.warnings)})"):
        for warning in v.warnings:
            st.markdown(f"- {warning}")
