"""Returns: TWR, XIRR, drawdowns and monthly returns (D-022)."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from ui.charts import current_mode, drawdown_chart, line_chart, returns_heatmap, show
from ui.components import Kpi, empty_state, kpi_row, page_header, section, table
from ui.data import RANGES, load_valuation, period_start, require_valued_data
from ui.fmt import fmt_date, fmt_money, fmt_pct
from ui.glossary import G
from ui.theme import color_map

from finance_analytics import reports
from finance_analytics.config import get_settings
from finance_analytics.market.network import is_online
from finance_analytics.portfolio import inflation
from finance_analytics.portfolio.attribution import attribute
from finance_analytics.portfolio.returns import monthly_returns, returns_for

PORTFOLIO = "Cały portfel"

page_header("Zwroty", "Ile zarabiają Twoje inwestycje, niezależnie od tego, kiedy i ile wpłacałeś.")
settings = get_settings()
require_valued_data(settings, "stopy zwrotu (TWR, XIRR), spadki od szczytu i zwroty miesięczne")
v, _ = load_valuation(settings)
total = v.total

period = st.segmented_control(
    "Okres", RANGES, default="Maks.", key="returns_period", required=True, help=G["periods"]
)
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

# Inflation (D-025, D-041): the price level per day, from the saved GUS CPI; nothing without it.
cpi = reports.cpi_monthly(settings.db_path)
levels, daily_cpi = inflation.daily_from_cpi(cpi, total.index) if not cpi.empty else (None, None)
period_inflation = inflation.window_inflation(daily_cpi, start, end) if daily_cpi is not None else None

# ------------------------------------------------------------------------------------------- KPIs
dd = portfolio.drawdown
kpi_row(
    [
        Kpi("TWR w okresie", fmt_pct(portfolio.twr),
            delta=f"{fmt_pct(portfolio.twr_annual)} rocznie" if portfolio.twr_annual is not None else None,
            help=G["twr"],
            trend=(portfolio.index - 1).resample("W-FRI").last().round(4).tolist(), trend_kind="pct"),
        Kpi("XIRR (rocznie)", fmt_pct(portfolio.xirr) if portfolio.xirr is not None else "–",
            delta_color="off",
            delta=None if portfolio.xirr is not None else "dla okresów od roku",
            help=G["xirr"],
            trend=total[total.index >= start].resample("W-FRI").last().round(0).tolist()),
        Kpi("Największy spadek", fmt_pct(dd.max_drawdown),
            delta=f"{fmt_date(dd.peak)} → {fmt_date(dd.trough)}" if dd.trough is not None else None,
            delta_color="off",
            help=G["drawdown"] + " "
                 + (f"Odrobiony {fmt_date(dd.recovered)}." if dd.recovered is not None else "Jeszcze nieodrobiony."),
            trend=dd.series.resample("W-FRI").min().round(4).tolist(), trend_kind="pct"),
        Kpi("Obecnie od szczytu", fmt_pct(dd.current), delta_color="off",
            help=G["drawdown_current"],
            trend=dd.series.resample("W-FRI").last().round(4).tolist(), trend_kind="pct"),
    ]
)

mode = current_mode()

# --------------------------------------------------------------------------------- TWR over time
section(
    "Stopa zwrotu w czasie (TWR)",
    f"Skumulowana, od {fmt_date(start)} do {fmt_date(end)}. 0% oznacza wynik zerowy.",
    help=G["twr"],
)
lines = pd.DataFrame({PORTFOLIO: portfolio.index - 1})
for account, result in per_account.items():
    lines[account] = result.index - 1
colors = color_map([PORTFOLIO, *per_account], mode)
show(line_chart(lines, mode=mode, colors=colors, height=360, hover="%{y:.1%}", y_tickformat=".0%"), key="twr")

# ------------------------------------------------------------------------------ after inflation
section("Po inflacji", "Zwrot nominalny (TWR) i realny, czyli po odjęciu wzrostu cen według CPI z GUS.",
        help=G["real_return"])
if cpi.empty:
    online = is_online(settings)
    empty_state(
        "Brak danych o inflacji",
        "Do zwrotu realnego potrzebny jest indeks CPI z GUS. "
        + ("Pobierz go razem z cenami na stronie Dane rynkowe." if online else
           "Aplikacja jest w trybie offline, więc go nie pobiera. Włącz tryb online w Ustawieniach."),
        icon=":material/trending_up:",
    )
    if online:
        st.page_link("views/market.py", label="Przejdź do danych rynkowych", icon=":material/arrow_forward:")
    else:
        st.page_link("views/settings.py", label="Przejdź do ustawień", icon=":material/arrow_forward:")
else:
    if period_inflation is None:
        st.caption(f"CPI zaczyna się od {fmt_date(levels.index[0])}, więc dla tego okresu nie ma inflacji.")
    else:
        real = inflation.real_return(portfolio.twr, period_inflation)
        real_annual = inflation.real_annual(real, days)
        annual_note = f" ({fmt_pct(real_annual)} rocznie)" if real_annual is not None else ""
        st.markdown(
            f"Inflacja w okresie **{fmt_pct(period_inflation)}**, zwrot nominalny (TWR) "
            f"**{fmt_pct(portfolio.twr)}**, zwrot realny **{fmt_pct(real)}**{annual_note}.",
            help=G["real_return"],
        )
        # Profit "na czysto" in złoty and the real XIRR: the money-weighted view (D-041).
        # "Maks." counts every deposit, like "Zysk całkowity" on Portfel, so the two amounts agree.
        profit = inflation.real_profit(total, flows, daily_cpi, None if start <= total.index[0] else start, end)
        real_irr = inflation.real_xirr(total, flows, daily_cpi, start, end) if portfolio.xirr is not None else None
        if profit is not None:
            irr_note = (f", XIRR realny **{fmt_pct(real_irr)}** rocznie (nominalnie {fmt_pct(portfolio.xirr)})"
                        if real_irr is not None else "")
            st.markdown(
                f"Zysk realny w okresie **{fmt_money(profit.profit, decimals=0, signed=True)}** "
                f"(w złotych z {end:%m.%Y}){irr_note}.",
                help=G["real_profit"] + " " + G["real_xirr"],
            )
        cumulative_cpi = inflation.cumulative_inflation(daily_cpi, start)
        nominal = (portfolio.index - 1).reindex(cumulative_cpi.index).dropna()
        cumulative_cpi = cumulative_cpi.reindex(nominal.index)
        real_line = (1 + nominal) / (1 + cumulative_cpi) - 1
        compare = pd.DataFrame({"Nominalnie (TWR)": nominal, "Realnie (po inflacji)": real_line,
                                "Inflacja (CPI)": cumulative_cpi})
        show(line_chart(compare, mode=mode, height=320, hover="%{y:.1%}", y_tickformat=".0%"), key="real")
        if daily_cpi["estimated"].iloc[-1]:
            st.caption(f"Ostatni opublikowany miesiąc CPI: {levels.index[-1]:%m.%Y}. Dla nowszych miesięcy "
                       "przyjmujemy ostatnią inflację rok do roku, więc wynik realny jest przybliżony.",
                       help=G["cpi_estimated"])

# ---------------------------------------------------------------------------- stocks vs currency
attribution = attribute(v, start, end)
final = attribution.cumulative.iloc[-1] if not attribution.cumulative.empty else None
section("Akcje czy waluty?", "Skąd wziął się wynik w PLN: ze zmian cen instrumentów, z kursów walut czy z reszty.",
        help=G["attribution"])
if final is None:
    st.caption("Za krótki okres, żeby rozbić wynik.")
else:
    st.markdown(
        f"**{fmt_pct(final['total'])}** w PLN (TWR) = ceny instrumentów **{fmt_pct(final['price'])}** "
        f"× kursy walut **{fmt_pct(final['fx'])}** × pozostałe **{fmt_pct(final['other'])}**",
        help="(1 + wynik w PLN) = (1 + ceny) × (1 + waluty) × (1 + pozostałe). Ceny: zmiana kursów akcji i ETF "
             "w ich walucie. Waluty: zmiana kursu NBP waluty notowania oraz gotówki w walutach. Pozostałe: "
             "dywidendy, odsetki, podatki, opłaty i różnica między ceną zakupu a ceną zamknięcia w dniu zakupu.",
    )
    parts = attribution.cumulative.rename(columns={
        "total": "Razem (TWR)", "price": "Ceny instrumentów", "fx": "Kursy walut", "other": "Pozostałe",
    })[["Razem (TWR)", "Ceny instrumentów", "Kursy walut", "Pozostałe"]]
    show(line_chart(parts, mode=mode, height=320, hover="%{y:.1%}", y_tickformat=".0%"), key="attribution")

    st.markdown(
        "**Waluty**: wynik z kursu na pozycjach i gotówce w danej walucie.",
        help="Wynik z kursu zależy od tego, ile w danej walucie miałeś w chwili, gdy kurs się zmieniał. "
             "Może więc mieć inny znak niż zmiana kursu w całym okresie, np. gdy dokupowałeś przy niskim kursie, "
             "a potem kurs wzrósł.",
    )
    table(
        attribution.by_currency,
        numbers={"pnl_fx": 2},
        percents=["fx_change"],
        signed=["pnl_fx", "fx_change"],
        labels={"currency": "Waluta", "pnl_fx": "Wynik z kursu (zł)", "fx_change": "Zmiana kursu NBP"},
        helps={"pnl_fx": G["fx_sign"], "fx_change": G["nbp_rate"]},
    )
    st.markdown("**Instrumenty**: zmiany liczone za część okresu, w której instrument był w portfelu.")
    table(
        attribution.by_instrument,
        numbers={"pnl_price": 2, "pnl_fx": 2, "pnl_total": 2},
        percents=["price_change", "fx_change"],
        signed=["pnl_price", "pnl_fx", "pnl_total", "price_change", "fx_change"],
        labels={"symbol": "Ticker", "name": "Instrument", "currency": "Waluta",
                "pnl_price": "Z ceny (zł)", "pnl_fx": "Z waluty (zł)", "pnl_total": "Razem (zł)",
                "price_change": "Zmiana ceny", "fx_change": "Zmiana kursu"},
        helps={"symbol": G["ticker"], "pnl_price": G["part_price"], "pnl_fx": G["part_fx"],
               "price_change": G["price_change"], "fx_change": G["fx_change"]},
    )

section("Spadki od szczytu", "Jak daleko cały portfel był pod swoim poprzednim maksimum (indeks TWR).",
        help=G["drawdown"])
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
accounts_table = pd.DataFrame(rows)
columns = ["account", "value", "twr", "twr_annual", "xirr", "max_dd"]
if period_inflation is not None:  # real TWR next to the nominal one (D-041)
    def account_inflation(name: str) -> float | None:
        """Inflation from the later of the window start and the account's first day with money."""
        held = account_values[name][account_values[name] != 0] if name != PORTFOLIO else total[total != 0]
        first = max(start, held.index[0]) if not held.empty else start
        return inflation.window_inflation(daily_cpi, first, end)

    real_twr = []
    for name, twr in zip(accounts_table["account"], accounts_table["twr"], strict=True):
        pi = account_inflation(name)
        real_twr.append(None if pi is None else inflation.real_return(twr, pi))
    accounts_table["twr_real"] = real_twr
    columns.insert(3, "twr_real")
table(
    accounts_table[columns],
    numbers={"value": 2},
    percents=["twr", "twr_real", "twr_annual", "xirr", "max_dd"],
    signed=["twr", "twr_real", "twr_annual", "xirr", "max_dd"],
    labels={"account": "Rachunek", "value": "Wartość (zł)", "twr": "TWR", "twr_real": "TWR realnie",
            "twr_annual": "TWR rocznie", "xirr": "XIRR", "max_dd": "Maks. spadek"},
    helps={"twr": G["twr"], "twr_real": G["twr_real"], "twr_annual": G["twr_annual"], "xirr": G["xirr"],
           "max_dd": G["drawdown"]},
)

# ---------------------------------------------------------------------------------- monthly grid
section("Zwroty miesięczne", "TWR całego portfela w każdym miesiącu i roku, od początku historii.",
        help=G["monthly_returns"])
grid = monthly_returns(returns_for(total, flows, total.index[0], end).index)
left, right = st.columns([5, 1], gap="medium")
with left:
    show(returns_heatmap(grid, mode=mode), key="monthly")
with right:
    table(
        pd.DataFrame({"year": [str(y) for y in grid.index], "r": grid["year"].to_numpy()}),
        percents=["r"], signed=["r"], labels={"year": "Rok", "r": "Zwrot"},
    )
