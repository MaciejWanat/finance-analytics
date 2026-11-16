"""Returns: TWR, XIRR, drawdowns and monthly returns (D-022)."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from ui.charts import current_mode, drawdown_chart, line_chart, returns_heatmap, show
from ui.components import Kpi, kpi_row, page_header, section, table
from ui.data import RANGES, load_valuation, period_start, require_valued_data
from ui.fmt import fmt_date, fmt_pct
from ui.theme import color_map

from finance_analytics.config import get_settings
from finance_analytics.portfolio.returns import monthly_returns, returns_for

PORTFOLIO = "Cały portfel"

page_header("Zwroty", "Ile zarabiają Twoje inwestycje, niezależnie od tego, kiedy i ile wpłacałeś.")
settings = get_settings()
require_valued_data(settings, "stopy zwrotu (TWR, XIRR), spadki od szczytu i zwroty miesięczne")
v, _ = load_valuation(settings)
total = v.total

period = st.segmented_control("Okres", RANGES, default="Maks.", key="returns_period", required=True)
end = total.index[-1]
start = period_start(period, total.index[0], end)
days = (end - start).days

flows = v.flows.set_index("date")["amount_pln"].sort_index()
portfolio = returns_for(total, flows, start, end)

# Same metrics per account: its own value and its own deposits/withdrawals.
account_values = v.daily.pivot_table(index="date", columns="account", values="value_pln", aggfunc="sum").fillna(0.0)
aliases = v.daily.drop_duplicates("account_id").set_index("account_id")["account"]
account_flows = v.flows.assign(account=v.flows["account_id"].map(aliases))
per_account = {
    account: returns_for(
        account_values[account],
        account_flows[account_flows["account"] == account].set_index("date")["amount_pln"].sort_index(),
        start, end,
    )
    for account in sorted(account_values.columns)
}

# ------------------------------------------------------------------------------------------- KPIs
dd = portfolio.drawdown
kpi_row(
    [
        Kpi("TWR w okresie", fmt_pct(portfolio.twr),
            delta=f"{fmt_pct(portfolio.twr_annual)} rocznie" if portfolio.twr_annual is not None else None,
            help="Stopa zwrotu ważona czasem: wynik samych inwestycji, bez wpływu momentów wpłat i wypłat. "
                 "Wersję roczną pokazujemy dla okresów od roku.",
            trend=(portfolio.index - 1).resample("W-FRI").last().round(4).tolist()),
        Kpi("XIRR (rocznie)", fmt_pct(portfolio.xirr) if portfolio.xirr is not None else "–",
            delta_color="off",
            delta=None if portfolio.xirr is not None else "dla okresów od roku",
            help="Stopa zwrotu ważona kapitałem: Twój roczny zysk z uwzględnieniem tego, kiedy i ile wpłacałeś. "
                 "Wyższa od TWR, gdy więcej pieniędzy pracowało w dobrych okresach.",
            trend=total[total.index >= start].resample("W-FRI").last().round(0).tolist()),
        Kpi("Największy spadek", fmt_pct(dd.max_drawdown),
            delta=f"{fmt_date(dd.peak)} → {fmt_date(dd.trough)}" if dd.trough is not None else None,
            delta_color="off",
            help="Najgłębszy spadek indeksu TWR od poprzedniego szczytu w wybranym okresie. "
                 + (f"Odrobiony {fmt_date(dd.recovered)}." if dd.recovered is not None else "Jeszcze nieodrobiony."),
            trend=dd.series.resample("W-FRI").min().round(4).tolist()),
        Kpi("Obecnie od szczytu", fmt_pct(dd.current), delta_color="off",
            help="O ile indeks TWR jest dziś poniżej swojego najwyższego poziomu w okresie.",
            trend=dd.series.resample("W-FRI").last().round(4).tolist()),
    ]
)

mode = current_mode()

# --------------------------------------------------------------------------------- TWR over time
section(
    "Stopa zwrotu w czasie (TWR)",
    f"Skumulowana, od {fmt_date(start)} do {fmt_date(end)}. 0% oznacza wynik zerowy.",
)
lines = pd.DataFrame({PORTFOLIO: portfolio.index - 1})
for account, result in per_account.items():
    lines[account] = result.index - 1
colors = color_map([PORTFOLIO, *per_account], mode)
show(line_chart(lines, mode=mode, colors=colors, height=360, hover="%{y:.1%}", y_tickformat=".0%"), key="twr")

section("Spadki od szczytu", "Jak daleko cały portfel był pod swoim poprzednim maksimum (indeks TWR).")
show(drawdown_chart(dd.series, mode=mode), key="drawdown")

# ------------------------------------------------------------------------------- per account
section("Rachunki", "Każdy rachunek liczony z własnymi wpłatami i wypłatami.")
rows = [
    {"account": name, "value": float(account_values[name].iloc[-1]), "twr": r.twr, "twr_annual": r.twr_annual,
     "xirr": r.xirr, "max_dd": r.drawdown.max_drawdown}
    for name, r in per_account.items()
]
rows.append({"account": PORTFOLIO, "value": float(total.iloc[-1]), "twr": portfolio.twr,
             "twr_annual": portfolio.twr_annual, "xirr": portfolio.xirr, "max_dd": dd.max_drawdown})
table(
    pd.DataFrame(rows),
    numbers={"value": 2},
    percents=["twr", "twr_annual", "xirr", "max_dd"],
    signed=["twr", "twr_annual", "xirr", "max_dd"],
    labels={"account": "Rachunek", "value": "Wartość (zł)", "twr": "TWR", "twr_annual": "TWR rocznie",
            "xirr": "XIRR", "max_dd": "Maks. spadek"},
)

# ---------------------------------------------------------------------------------- monthly grid
section("Zwroty miesięczne", "TWR całego portfela w każdym miesiącu i roku, od początku historii.")
grid = monthly_returns(returns_for(total, flows, total.index[0], end).index)
left, right = st.columns([5, 1], gap="medium")
with left:
    show(returns_heatmap(grid, mode=mode), key="monthly")
with right:
    table(
        pd.DataFrame({"year": [str(y) for y in grid.index], "r": grid["year"].to_numpy()}),
        percents=["r"], signed=["r"], labels={"year": "Rok", "r": "Zwrot"},
    )
