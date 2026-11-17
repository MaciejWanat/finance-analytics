"""Portfolio: value of everything in PLN, day by day."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from ui.charts import area_total, current_mode, segmented_bar, show, stacked_bars
from ui.components import Kpi, kpi_row, page_header, section, table
from ui.data import RANGES, load_valuation, period_start, require_valued_data
from ui.fmt import fmt_date, fmt_money, fmt_money_compact, fmt_pct
from ui.glossary import G
from ui.theme import OTHER_LABEL, color_map

from finance_analytics import reports
from finance_analytics.config import get_settings
from finance_analytics.portfolio import inflation
from finance_analytics.portfolio.attribution import fx_pnl
from finance_analytics.portfolio.returns import period_return, twr_index, underwater

BREAKDOWNS = {"Klasa aktywów": "asset_class", "Rachunek": "account", "Instrument": "symbol", "Waluta": "currency"}
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

# Inflation (D-025, D-058): the price level per day, from the saved GUS CPI; nothing without it.
cpi = reports.cpi_monthly(settings.db_path)
daily_cpi = inflation.daily_from_cpi(cpi, total.index)[1] if not cpi.empty else None

# ------------------------------------------------- period filter and inflation switch (scope the whole page)
period_col, real_col = st.columns([4, 1], vertical_alignment="bottom")
with period_col:
    period = st.segmented_control("Okres", RANGES, default="Maks.", key="period", required=True,
                                  help=G["periods"])
with real_col:
    # The note on estimated months lives in the help, not on the page: a line that comes and goes with
    # the switch would move everything below it (D-060).
    real_help = G["real_view_no_cpi"] if daily_cpi is None else G["real_view"] + (
        " Ostatnie miesiące bez opublikowanego CPI liczone z ostatniej inflacji r/r."
        if daily_cpi["estimated"].iloc[-1] else "")
    real_view = st.toggle("Po inflacji", key="real_view", disabled=daily_cpi is None, help=real_help)
real_view = bool(real_view and daily_cpi is not None)

flows = v.flows.set_index("date")["amount_pln"].sort_index()
lots = v.lots
end = total.index[-1]
factor = None
if real_view:
    # Every amount in the złoty of the last day: value, flows and costs times level(end) / level(day).
    # The formulas below stay the same; only their inputs change (D-058).
    level = daily_cpi["level"].reindex(total.index)
    level = level.where(level > 0).ffill().bfill()
    factor = level.iloc[-1] / level
    # Polish prices did not rise more than five-fold, nor fall by four fifths, within one portfolio's life: a
    # factor outside that range means broken CPI data, and using it would turn every figure into nonsense.
    if factor.isna().any() or not factor.between(0.2, 5).all():
        st.warning("Dane o inflacji (CPI z GUS) w bazie wyglądają na uszkodzone, więc pokazuję wartości "
                   "nominalne. Pobierz je ponownie na stronie Dane rynkowe.", icon=":material/warning:")
        real_view = False
if real_view:
    total = total * factor
    flows = flows * factor.reindex(flows.index).fillna(1.0).to_numpy()
    daily = daily.assign(value_pln=daily["value_pln"] * daily["date"].map(factor).fillna(1.0))
    lots = lots.assign(cost_pln=lots["cost_pln"] * lots["open_date"].map(lambda d: factor.asof(d)).fillna(1.0))
UNIT = "w dzisiejszych złotych" if real_view else "w PLN"

start = period_start(period, total.index[0], end)
window = total[total.index >= start]

# ------------------------------------------------------------------------------------------- KPIs
value_now = total.iloc[-1]
in_window = flows[(flows.index > start) & (flows.index <= end)].sum()
result = value_now - window.iloc[0] - in_window
index = twr_index(total, flows)
twr_period = period_return(index, start, end)
contributed = flows.sum()


# Every tile gets a sparkline over the selected period, so the tiles line up and read alike.
cumulative_flows = flows.groupby(level=0).sum().reindex(total.index, fill_value=0.0).cumsum()
step = "W-FRI" if (end - start).days <= 180 else "ME"


def trend(series: pd.Series) -> list[float]:
    return series[series.index >= start].resample(step).last().dropna().round(0).tolist()


period_result = total - window.iloc[0] - (cumulative_flows - cumulative_flows.asof(start))
# How far below the money put in the portfolio has been (D-049): (value - deposits) / deposits.
uw = underwater(total, cumulative_flows, start)
in_window_ratio = uw.series[uw.series.index >= start].dropna()
lowest = (f"min. {fmt_pct(uw.worst)} ({uw.day:%m.%Y})" if uw.worst is not None and uw.worst < 0
          else "nigdy poniżej wpłat" if uw.worst is not None else None)
ratio_help = (G["profit_ratio"]
              + (f" Najniżej {fmt_date(uw.day)}: {fmt_pct(uw.worst)}, czyli "
                 f"{fmt_money(uw.profit, decimals=0, signed=True)} względem wpłat." if uw.day is not None else "")
              + (" Wpłaty i wartości w dzisiejszych złotych." if real_view else ""))
# Currency gain or loss (D-059): what foreign holdings earned or lost on the NBP rate alone, day by day.
fx_daily = fx_pnl(v)
if factor is not None:
    fx_daily = fx_daily.mul(factor.reindex(fx_daily.index).fillna(1.0), axis=0)
fx_window = fx_daily[(fx_daily.index > start) & (fx_daily.index <= end)]
fx_by_currency = fx_window.sum().sort_values(key=abs, ascending=False)
fx_total = float(fx_by_currency.sum())
fx_cumulative = fx_window.sum(axis=1).cumsum()


def _short(amount: float) -> str:
    """'+26k' / '+1,2k' / '−523': short enough for two currencies in one tile delta."""
    if abs(amount) >= 10_000:
        text = f"{amount / 1000:+.0f}k"
    elif abs(amount) >= 1000:
        text = f"{amount / 1000:+.1f}k".replace(".", ",")
    else:
        text = f"{amount:+.0f}"
    return text.replace("-", "−")


# The tile shows the two currencies that mattered most as coloured badges; the help lists all of them.
fx_badges = [(f"{currency} {_short(amount)}", float(amount)) for currency, amount in fx_by_currency.head(2).items()]
fx_help = G["fx_result"] + "".join(
    f" {currency}: {fmt_money(amount, decimals=0, signed=True)}." for currency, amount in fx_by_currency.items())
# One row: value, period result, currencies, deposits, profit vs deposits with its lowest point (D-055, D-059).
kpi_row(
    [
        Kpi("Wartość portfela", fmt_money_compact(value_now),
            delta=fmt_money_compact(value_now - window.iloc[0]).replace("−", "-"),
            help="Przyrost wartości w wybranym okresie, razem z wpłatami (procent byłby mylący przy "
                 "małej wartości startowej).", trend=trend(total),
            series=total, series_start=start, series_note=f"Wartość wszystkich rachunków {UNIT}, dzień po dniu."),
        Kpi("Wynik w okresie", fmt_money(result, decimals=0, signed=True),
            delta=f"{fmt_pct(twr_period)} TWR" + (" realnie" if real_view else ""),
            help=G["result_period"],
            trend=trend(period_result),
            series=period_result[period_result.index >= start],
            series_note="Zysk lub strata od początku wybranego okresu, bez wpłat i wypłat. Inny okres wybierzesz "
                        "nad kafelkami."),
        Kpi("Wynik na walutach", fmt_money(fx_total, decimals=0, signed=True) if len(fx_by_currency) else "–",
            delta=None if fx_badges else "brak walut obcych", delta_color="off", badges=fx_badges, help=fx_help,
            trend=fx_cumulative.resample(step).last().dropna().round(0).tolist(), trend_water=True,
            series=fx_cumulative,
            series_note="Zysk (+) lub strata (−) na samych kursach walut, narastająco od początku okresu: wartość "
                        "w walucie razy zmiana kursu NBP, dzień po dniu."),
        Kpi("Wpłacony kapitał", fmt_money_compact(contributed), delta_color="off",
            delta=fmt_money_compact(in_window) + " w okresie" if in_window else None,
            help=G["contributed"] + (" Każda wpłata przeliczona na dzisiejsze złote." if real_view else ""),
            trend=trend(cumulative_flows),
            series=cumulative_flows, series_start=start, series_note="Suma wpłat minus wypłaty, narastająco."),
        Kpi("Zysk do wpłat", fmt_pct(uw.current) if uw.current is not None else "–",
            delta=lowest, delta_color="off", help=ratio_help,
            trend=in_window_ratio.resample(step).last().dropna().round(4).tolist(),
            trend_kind="pct", trend_water=True, series=in_window_ratio,
            series_note="(Wartość portfela − wpłaty) / wpłaty, dzień po dniu. Poniżej zera portfel był wart mniej "
                        "niż wpłacone pieniądze."),
    ]
)

mode = current_mode()

# -------------------------------------------------------------------------------- value over time
live_note = f" Dzisiejsza wartość na żywo: ceny z {live_at.astimezone():%H:%M}." if live_at else ""
section("Wartość portfela", f"{UNIT[0].upper() + UNIT[1:]}, od {window.index[0]:%d.%m.%Y} do {end:%d.%m.%Y}."
        f"{live_note}", help=G["portfolio_value"])
show(area_total(window, name="Portfel", mode=mode, height=340), key="total")

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
    section(f"Skład portfela: {breakdown.lower()}", f"Wartość na koniec każdego {frequency_label}, {UNIT}.",
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
section("Bieżące pozycje", "Wartość po ostatnim kursie zamknięcia i kursie NBP; koszt po kursie z dnia zakupu"
        + (", przeliczony na dzisiejsze złote." if real_view else "."), help=G["position"])
last_day = daily[(daily["date"] == end) & (daily["kind"] == "position")]
holdings = last_day.groupby(["account", "symbol", "name", "asset_class", "currency"], as_index=False).agg(
    qty=("qty", "sum"), price=("price", "last"), value=("value_pln", "sum")
)
open_lots = lots[lots["close_date"].isna()].assign(account=lambda d: d["account_id"].map(
    daily.drop_duplicates("account_id").set_index("account_id")["account"]))
cost = open_lots.groupby(["account", "symbol"])["cost_pln"].sum(min_count=1)  # all unknown -> unknown, not 0
holdings["cost"] = [cost.get((a, s)) for a, s in zip(holdings["account"], holdings["symbol"], strict=True)]
holdings["pnl"] = holdings["value"] - holdings["cost"]
# A cost of zero (or below) is not a real cost: show the result % as unknown rather than +∞.
holdings["pnl_pct"] = holdings["pnl"] / holdings["cost"].where(holdings["cost"] > 0)
holdings["share"] = holdings["value"] / value_now
# The 90-day trend is the result (value minus the cost of the lots held that day), so a purchase
# does not bend the line (D-054).
recent = daily[(daily["kind"] == "position") & (daily["date"] > end - pd.Timedelta(days=90))]
recent_value = recent.groupby(["account", "symbol", "date"])["value_pln"].sum()
all_lots = lots.assign(account=lambda d: d["account_id"].map(
    daily.drop_duplicates("account_id").set_index("account_id")["account"]), cost=lambda d: d["cost_pln"].fillna(0.0))
cost_steps = pd.concat([
    all_lots[["account", "symbol", "open_date", "cost"]].rename(columns={"open_date": "date"}),
    all_lots.dropna(subset=["close_date"])[["account", "symbol", "close_date", "cost"]]
    .rename(columns={"close_date": "date"}).assign(cost=lambda d: -d["cost"]),
]).groupby(["account", "symbol", "date"])["cost"].sum()


def result_trend(account: str, symbol: str) -> list[float]:
    values = recent_value.loc[(account, symbol)]
    steps = cost_steps.loc[(account, symbol)].sort_index().cumsum()
    held_cost = steps.reindex(steps.index.union(values.index)).ffill().reindex(values.index).fillna(0.0)
    return (values - held_cost).round(0).tolist()


holdings["trend"] = [result_trend(a, s) for a, s in zip(holdings["account"], holdings["symbol"], strict=True)]
holdings["asset_class"] = holdings["asset_class"].map(ASSET_CLASS_LABELS).fillna(holdings["asset_class"])
holdings = holdings.sort_values("value", ascending=False)
table(
    holdings[["symbol", "account", "name", "asset_class", "qty", "price", "currency", "value", "share", "cost", "pnl",
              "pnl_pct", "trend"]],
    numbers={"qty": 4, "price": 2, "value": 2, "cost": 2, "pnl": 2},
    percents=["share", "pnl_pct"],
    signed=["pnl", "pnl_pct"],
    trends=["trend"],
    search="positions",
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
