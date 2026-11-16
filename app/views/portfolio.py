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

from finance_analytics.config import get_settings
from finance_analytics.portfolio.returns import period_return, twr_index

BREAKDOWNS = {"Rachunek": "account", "Klasa aktywów": "asset_class", "Instrument": "symbol", "Waluta": "currency"}
ASSET_CLASS_LABELS = {"stock": "Akcje", "etf": "ETF", "bond": "Obligacje", "cash": "Gotówka", "other": "Inne"}
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
        Kpi("Zysk całkowity", fmt_money_compact(value_now - contributed),
            delta=fmt_pct((value_now - contributed) / contributed) if contributed > 0 else None,
            help=G["total_gain"], trend=trend(total - cumulative_flows)),
    ]
)

mode = current_mode()

# -------------------------------------------------------------------------------- value over time
live_note = f" Dzisiejsza wartość na żywo: ceny z {live_at.astimezone():%H:%M}." if live_at else ""
section("Wartość portfela", f"W PLN, od {window.index[0]:%d.%m.%Y} do {end:%d.%m.%Y}.{live_note}",
        help=G["portfolio_value"])
show(area_total(window, name="Portfel", mode=mode, height=340), key="total")

# ---------------------------------------------------------------------------- composition and parts
# The breakdown filter sits right above the charts it changes.
breakdown = st.segmented_control(
    "Podział", list(BREAKDOWNS), default="Rachunek", key="breakdown", required=True, help=G["breakdown"]
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
    section("Alokacja dziś", f"{breakdown}: udział w wartości portfela.", help=G["allocation"])
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
    helps={"symbol": G["ticker"], "price": G["last_price"], "cost": G["cost"], "pnl": G["pnl"],
           "pnl_pct": G["pnl"], "share": G["share"], "trend": G["trend_90"]},
)

if v.warnings:
    with st.expander(f":material/warning: Uwagi do wyceny ({len(v.warnings)})"):
        for warning in v.warnings:
            st.markdown(f"- {warning}")
