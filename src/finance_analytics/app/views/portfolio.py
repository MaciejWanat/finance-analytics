"""Portfolio: value of everything in PLN, day by day.

In online mode the headline (KPI tiles and the value chart) and the positions table are live fragments: they
redraw with the newest quotes (`Preferences.redraw_seconds`), without rerunning the rest of the page (D-069).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import streamlit as st
from ui.charts import area_total, current_mode, intraday_chart, segmented_bar, show, stacked_bars
from ui.components import DIALOG_OPEN, Kpi, kpi_row, page_header, section, table
from ui.data import (
    DAILY_POINTS_DAYS,
    FULL_RUN,
    ONE_DAY,
    RANGES,
    live_every,
    load_benchmark,
    load_intraday,
    load_valuation,
    one_day,
    period_start,
    require_valued_data,
)
from ui.fmt import fmt_date, fmt_money, fmt_money_compact, fmt_pct
from ui.glossary import G
from ui.theme import OTHER_LABEL, color_map

from finance_analytics import reports
from finance_analytics.config import get_settings
from finance_analytics.market.intraday import coverage, update_intraday
from finance_analytics.market.live import live_symbols
from finance_analytics.portfolio import inflation
from finance_analytics.portfolio.attribution import fx_pnl
from finance_analytics.portfolio.benchmark import compare
from finance_analytics.portfolio.returns import period_return, position_result_trends, twr_index, underwater
from finance_analytics.portfolio.today import today_result
from finance_analytics.portfolio.valuation import market_days
from finance_analytics.preferences import Preferences, PreferencesError, load_preferences

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
try:
    preferences = load_preferences(settings)
except PreferencesError:  # the sidebar reports a broken settings file
    preferences = Preferences()
# Fast while an exchange is in session, slow while markets are quiet (D-071).
LIVE_EVERY = live_every(preferences)
STREAMING = preferences.streaming  # the stream says "na żywo" without the time of the last price (D-069)
v, live_at = load_valuation(settings)
total = v.total

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
        real_view, factor = False, None
UNIT = "w dzisiejszych złotych" if real_view else "w PLN"
# "1D" (D-070): the day of the "Dzisiaj" tile, every 5 minutes; daily figures are measured from its base close.
DAY = one_day(settings, v) if period == ONE_DAY else None
start = period_start(period, total.index[0], end, day_base=DAY.base if DAY else None)
INTRADAY_TREND = "15min"  # sparkline points within one day
# What the value chart shows: a new period or unit resets its zoom; live redraws keep it (D-072).
CHART_VIEW = f"{period}|{real_view}"


def day_values(v, window):
    """The 1D rows of a valuation, in today's złoty with "Po inflacji" (the factor of that day)."""
    intra = load_intraday(settings, v, window)
    if factor is not None and len(intra.rows):
        scale = float(factor.get(window.day, 1.0))
        intra.rows[["value_pln", "fx_pln"]] *= scale
    return intra


def fetch_today_button() -> None:
    """Offline the 1D quotes come only on request (D-031): a two-run button with a spinner (ui-guidelines §6)."""
    busy = st.session_state.get("intraday_fetching", False)
    if st.button("Pobierz notowania z dziś", icon="spinner" if busy else ":material/download:", disabled=busy,
                 help=G["intraday_fetch"], key="intraday_fetch"):
        st.session_state["intraday_fetching"] = True
        st.rerun(scope="fragment")
    if busy:
        try:
            update_intraday(settings, live_symbols(settings), manual=True)
        except Exception as exc:  # the network or Yahoo refused: say so, keep the page
            st.session_state["intraday_error"] = str(exc)
        finally:
            st.session_state["intraday_fetching"] = False
        st.rerun(scope="fragment")
    if error := st.session_state.pop("intraday_error", None):
        st.warning(f"Nie udało się pobrać notowań: {error}", icon=":material/sync_problem:")


def scaled(v):
    """(daily, total, flows, lots) of a valuation, in today's złoty with "Po inflacji" (D-058)."""
    daily, total, lots = v.daily, v.total, v.lots
    flows = v.flows.set_index("date")["amount_pln"].sort_index()
    if factor is not None:
        total = total * factor.reindex(total.index).fillna(1.0)
        flows = flows * factor.reindex(flows.index).fillna(1.0).to_numpy()
        daily = daily.assign(value_pln=daily["value_pln"] * daily["date"].map(factor).fillna(1.0))
        lots = lots.assign(cost_pln=lots["cost_pln"] * lots["open_date"].map(lambda d: factor.asof(d)).fillna(1.0))
    return daily, total, flows, lots


def live_valuation():
    """The valuation for a live fragment: the full run's one, or a fresh one with the newest quotes on the
    fragment's own timer runs. A new day (midnight) reruns the whole page, so every block moves to it; so does a
    change of pace (an exchange opens or the last one closes, D-071), unless a chart dialog is open."""
    if st.session_state.get(FULL_RUN, True):
        return v, live_at
    fresh, fresh_at = load_valuation(settings, live_run=True)
    if fresh.total.index[-1] != end:
        st.rerun(scope="app")
    if live_every(preferences) != LIVE_EVERY and not st.session_state.get(DIALOG_OPEN):
        st.rerun(scope="app")
    return fresh, fresh_at


# Today (D-063, D-067): the result of the last day, counted from midnight (the default) or by US sessions (with US
# instruments held).
by_us_session = preferences.today_tile == "us_session" and reports.holds_us_listed(settings.db_path)


def _short(amount: float) -> str:
    """'+26k' / '+1,2k' / '−523': short enough for two currencies in one tile delta."""
    if abs(amount) >= 10_000:
        text = f"{amount / 1000:+.0f}k"
    elif abs(amount) >= 1000:
        text = f"{amount / 1000:+.1f}k".replace(".", ",")
    else:
        text = f"{amount:+.0f}"
    return text.replace("-", "−")


@st.fragment(run_every=LIVE_EVERY)
def headline() -> None:
    """KPI tiles and the value chart; live in online mode (D-069)."""
    v, live_at = live_valuation()
    _, total, flows, _ = scaled(v)
    window = total[total.index >= start]
    mode = current_mode()
    day = one_day(settings, v) if DAY is not None else None  # its end moves with the clock
    intra = day_values(v, day) if day is not None else None
    curve = intra.total if intra is not None else None
    # ------------------------------------------------------------------------------------------- KPIs
    value_now = total.iloc[-1]
    in_window = flows[(flows.index > start) & (flows.index <= end)].sum()
    result = value_now - window.iloc[0] - in_window
    index = twr_index(total, flows)
    twr_period = period_return(index, start, end)
    contributed = flows.sum()

    # Every tile gets a sparkline over the selected period, so the tiles line up and read alike.
    cumulative_flows = flows.groupby(level=0).sum().reindex(total.index, fill_value=0.0).cumsum()
    span = (end - start).days
    step = "D" if span <= DAILY_POINTS_DAYS else "W-FRI" if span <= 180 else "ME"

    def trend(series: pd.Series, decimals: int = 0) -> list[float]:
        if series.index.tz is not None:  # within one day (1D)
            return series.resample(INTRADAY_TREND).last().dropna().round(decimals).tolist()
        return series[series.index >= start].resample(step).last().dropna().round(decimals).tolist()

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
    contributed_ratio = None
    if curve is not None:
        # Within one day the curves come from the 5-minute values; the tile numbers stay the daily ones, measured
        # from the same close (D-070).
        period_result = curve - window.iloc[0] - in_window
        fx_cumulative = intra.fx_part
        deposits = cumulative_flows.iloc[-1]
        contributed_ratio = (curve - deposits) / deposits if deposits > 0 else None
        in_window_ratio = contributed_ratio if contributed_ratio is not None else in_window_ratio

    # The tile shows the two currencies that mattered most as coloured badges; the help lists all of them.
    fx_badges = [(f"{currency} {_short(amount)}", float(amount)) for currency, amount in fx_by_currency.head(2).items()]
    fx_help = G["fx_result"] + "".join(
        f" {currency}: {fmt_money(amount, decimals=0, signed=True)}." for currency, amount in fx_by_currency.items())
    # Today (D-063, D-067): the result of the last day, counted from midnight (the default) or by US sessions (with US
    # instruments held). When that day is not today the tooltip names it (no badge: the user found it noisy, D-067).
    tile = today_result(total, flows, market_days(v), by_us_session=by_us_session, now=datetime.now(UTC))
    session, today, session_returns = tile.day, tile.change, tile.per_day
    today_badges = [(fmt_money(today[0], decimals=0, signed=True), today[0])] if today else []
    today_help = (G["today"] + (G["today_us_session"] if by_us_session else G["today_calendar_day"])
                  + (f" Teraz widać sesję z {fmt_date(session)}." if session < end else "")
                  + (" Ceny na żywo ze strumienia." if live_at and STREAMING
                     else f" Ceny na żywo z {live_at.astimezone():%H:%M}." if live_at
                     else " Ceny z ostatnich pobranych notowań.")
                  + (" Kwota w dzisiejszych złotych." if real_view else ""))
    today_note = ("Wynik każdej sesji giełdy w USA w procentach (TWR), razem z ruchami walut i innych giełd od "
                  "poprzedniej sesji, bez wpłat i wypłat. Na kafelku: ostatni miesiąc." if by_us_session else
                  "Wynik każdej sesji w procentach (TWR dnia), bez wpłat i wypłat. Dni bez notowań (weekendy, święta) "
                  "są pominięte. Na kafelku: ostatni miesiąc.")
    # The enlarged charts' "1D" (D-076): today every 5 minutes after the daily history, the same curves as the 1D
    # period. Computed only while a chart is open (`Kpi.series_today`), so live redraws do not pay for it.
    today_parts: dict = {}

    def today_curves():
        if "intra" not in today_parts:
            d = one_day(settings, v)
            today_parts["intra"] = day_values(v, d) if coverage(settings.db_path, d.start, d.end) is not None else None
        intra_today = today_parts["intra"]
        return intra_today if intra_today is not None and len(intra_today.rows) else None

    def from_today(make):
        if curve is not None:  # the 1D period: the series are within the day already
            return None

        def build():
            curves = today_curves()
            return make(curves) if curves is not None else None
        return build

    # "Czy pobiłeś giełdę?" (D-080): the portfolio against the same money put into the S&P 500 on the same days.
    # Computed in nominal złoty (the index is nominal); with "Po inflacji" the gap is then put in today's złoty.
    nominal_flows = v.flows.set_index("date")["amount_pln"].sort_index()
    index_pln = load_benchmark(settings, v.total.index)
    vs = compare(v.total, nominal_flows, index_pln, start)
    if vs is not None and len(vs.gap) > 1:
        gap = vs.gap * factor.reindex(vs.gap.index).fillna(1.0) if factor is not None else vs.gap
        gap_now = float(gap.iloc[-1])
        # The index return is nominal, so the portfolio's TWR next to it is the nominal one too.
        twr_nominal = period_return(twr_index(v.total, nominal_flows), start, end) if real_view else twr_period
        market_tile = Kpi(
            "Czy pobiłeś giełdę?", "Tak" if gap_now > 0 else "Nie",
            delta=("+" if gap_now > 0 else "") + fmt_money_compact(gap_now),
            help=G["beat_market"]
            + f" Różnica: {fmt_money(gap_now, decimals=0, signed=True)}"
            + (" w dzisiejszych złotych" if real_view else "")
            + f". W tym okresie Twój portfel zarobił {fmt_pct(twr_nominal)} (TWR), a S&P 500 "
              f"{fmt_pct(vs.index_return)} w PLN."
            + (f" Stan na zamknięcie indeksu z {fmt_date(gap.index[-1])}." if gap.index[-1] < end else ""),
            trend=gap.resample(step).last().dropna().round(0).tolist(), trend_water=True,
            series=gap, series_start=start,
            series_note="Twój portfel minus portfel-cień, który za te same wpłaty, w te same dni, kupował indeks "
                        "S&P 500 (z dywidendami, w PLN). Powyżej zera wygrywasz z indeksem, poniżej przegrywasz.")
    else:
        # Quotes up to the period start but no close after it (1D before the US close): wait, do not ask to download.
        waiting = index_pln[index_pln.index <= start].notna().any()
        market_tile = Kpi("Czy pobiłeś giełdę?", "–",
                          delta="czeka na zamknięcie" if waiting else "brak notowań S&P 500", delta_color="off",
                          help=G["beat_market_waiting" if waiting else "beat_market_missing"])
    deposits_now = float(cumulative_flows.iloc[-1])
    fx_before_today = float(fx_cumulative.iloc[-2]) if curve is None and len(fx_cumulative) > 1 else 0.0
    # Value, today, period result, currencies; deposits, profit vs deposits, vs the S&P 500 (D-055, D-059, D-063,
    # D-080).
    tiles = [
        Kpi("Wartość portfela", fmt_money_compact(value_now),
            delta=fmt_money_compact(value_now - window.iloc[0]).replace("−", "-"),
            help="Przyrost wartości w wybranym okresie, razem z wpłatami (procent byłby mylący przy "
                 "małej wartości startowej).", trend=trend(curve if curve is not None else total),
            series=curve if curve is not None else total, series_start=start,
            series_today=from_today(lambda c: c.total),
            series_note=f"Wartość wszystkich rachunków {UNIT}, "
                        + ("co 5 minut." if curve is not None else "dzień po dniu.")),
        Kpi("Dzisiaj", fmt_pct(today[1], 2) if today else "–",
            delta=None if today else "brak poprzedniej sesji", delta_color="off", badges=today_badges,
            help=today_help,
            trend=session_returns[session_returns.index > end - pd.Timedelta(days=30)].round(5).tolist(),
            trend_kind="pct", trend_water=True, series=session_returns, series_start=start, series_note=today_note),
        Kpi("Wynik w okresie", fmt_money(result, decimals=0, signed=True),
            delta=f"{fmt_pct(twr_period)} TWR" + (" realnie" if real_view else ""),
            help=G["result_period"],
            trend=trend(period_result), trend_water=True,
            series=period_result if curve is not None else period_result[period_result.index >= start],
            series_today=from_today(lambda c: c.total - window.iloc[0] - in_window),
            series_note="Zysk lub strata od początku wybranego okresu, bez wpłat i wypłat. Inny okres wybierzesz "
                        "nad kafelkami."),
        Kpi("Wynik na walutach", fmt_money(fx_total, decimals=0, signed=True) if len(fx_by_currency) else "–",
            delta=None if fx_badges else "brak walut obcych", delta_color="off", badges=fx_badges, help=fx_help,
            trend=trend(fx_cumulative) if curve is not None
            else fx_cumulative.resample(step).last().dropna().round(0).tolist(), trend_water=True,
            series=fx_cumulative, series_today=from_today(lambda c: fx_before_today + c.fx_part),
            series_note="Zysk (+) lub strata (−) na samych kursach walut, narastająco od początku okresu: wartość "
                        + ("w walucie razy zmiana kursu rynkowego, co 5 minut." if curve is not None
                           else "w walucie razy zmiana kursu NBP, dzień po dniu.")),
        Kpi("Wpłacony kapitał", fmt_money_compact(contributed), delta_color="off",
            delta=fmt_money_compact(in_window) + " w okresie" if in_window else None,
            help=G["contributed"] + (" Każda wpłata przeliczona na dzisiejsze złote." if real_view else ""),
            trend=trend(pd.Series(contributed, index=curve.index) if curve is not None else cumulative_flows),
            series=cumulative_flows, series_start=start, series_note="Suma wpłat minus wypłaty, narastająco.",
            series_today=from_today(lambda c: pd.Series(deposits_now, index=c.total.index))),
        Kpi("Zysk do wpłat", fmt_pct(uw.current) if uw.current is not None else "–",
            delta=lowest, delta_color="off", help=ratio_help,
            trend=trend(in_window_ratio, 4) if curve is not None
            else in_window_ratio.resample(step).last().dropna().round(4).tolist(),
            trend_kind="pct", trend_water=True, series=in_window_ratio,
            series_today=(from_today(lambda c: (c.total - deposits_now) / deposits_now)
                          if deposits_now > 0 else None),
            series_note="(Wartość portfela − wpłaty) / wpłaty, dzień po dniu. Poniżej zera portfel był wart mniej "
                        "niż wpłacone pieniądze."),
        market_tile,
    ]
    # Two rows, 4 + 3 with an empty place, so seven tiles keep their labels readable (D-081).
    kpi_row(tiles[:4])
    kpi_row(tiles[4:], columns=4)

    # -------------------------------------------------------------------------------- value over time
    live_note = (" Dzisiejsza wartość na żywo." if live_at and STREAMING
                 else f" Dzisiejsza wartość na żywo: ceny z {live_at.astimezone():%H:%M}." if live_at else "")
    if day is None:
        section("Wartość portfela", f"{UNIT[0].upper() + UNIT[1:]}, od {window.index[0]:%d.%m.%Y} do {end:%d.%m.%Y}."
                f"{live_note}", help=G["portfolio_value"])
        show(area_total(window, name="Portfel", mode=mode, height=340), key="total", live=True, view=CHART_VIEW)
        return
    flat = f" Bez notowań w ciągu dnia (linia płaska): {', '.join(intra.missing)}." if intra.missing else ""
    section("Wartość portfela", f"{UNIT[0].upper() + UNIT[1:]}, {fmt_date(day.day)} co 5 minut, względem "
            f"zamknięcia {fmt_date(day.base)}.{live_note}{flat}", help=G["intraday"])
    if coverage(settings.db_path, day.start, day.end) is None:
        if preferences.online:
            st.info("Notowania z dziś pobierają się w tle; wykres pojawi się za chwilę.", icon=":material/schedule:")
        else:
            st.info("Brak notowań z tego dnia. W trybie offline aplikacja sama ich nie pobiera; możesz pobrać je "
                    "jednorazowo przyciskiem.", icon=":material/cloud_off:")
            fetch_today_button()
        return
    baseline = float(window.iloc[0])
    show(intraday_chart(curve, baseline=baseline, until=day.until, mode=mode, height=340,
                        baseline_label=f"Zamknięcie {day.base:%d.%m}: {fmt_money(baseline, decimals=0)}"),
         key="total", live=True, view=CHART_VIEW)


headline()
mode = current_mode()
daily = scaled(v)[0]

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
frequency, frequency_label = (("D", "dnia") if window_days <= DAILY_POINTS_DAYS
                              else ("W-FRI", "tygodnia") if window_days <= 100 else ("ME", "miesiąca"))
bars = wide[wide.index >= start][parts].resample(frequency).last()
if DAY is not None:  # 1D (D-070): the value at the end of each hour of the day
    hourly = day_values(v, DAY).rows
    if len(hourly):
        hourly = hourly.assign(part=hourly[column])
        if column == "asset_class":
            hourly["part"] = hourly["part"].map(ASSET_CLASS_LABELS).fillna(hourly["part"])
        by_hour = hourly.pivot_table(index="ts", columns="part", values="value_pln", aggfunc="sum").fillna(0.0)
        if OTHER_LABEL in parts:
            by_hour[OTHER_LABEL] = by_hour.drop(columns=[p for p in parts if p != OTHER_LABEL], errors="ignore").sum(
                axis=1)
        bars = by_hour.reindex(columns=parts, fill_value=0.0).resample("h").last()
        frequency_label = "godziny"

left, right = st.columns([3, 2], gap="large")
with left:
    section(f"Skład portfela: {breakdown.lower()}",
            f"Wartość na koniec każdej {frequency_label}, {UNIT}." if frequency_label == "godziny"
            else f"Wartość na koniec każdego {frequency_label}, {UNIT}.", help=G["composition"])
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
section("Bieżące pozycje", "Wartość po ostatniej cenie i kursie waluty (w trybie online na żywo); koszt po kursie NBP "
        "z dnia zakupu" + (", przeliczony na dzisiejsze złote." if real_view else "."), help=G["position"])


@st.fragment(run_every=LIVE_EVERY)
def positions() -> None:
    """The holdings table; live in online mode (D-069)."""
    v, _ = live_valuation()
    daily, total, _, lots = scaled(v)
    value_now = total.iloc[-1]
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
    trends = position_result_trends(daily, lots, end)
    holdings["trend"] = [trends.get((a, s), []) for a, s in zip(holdings["account"], holdings["symbol"], strict=True)]
    holdings["asset_class"] = holdings["asset_class"].map(ASSET_CLASS_LABELS).fillna(holdings["asset_class"])
    holdings = holdings.sort_values("value", ascending=False)
    table(
        holdings[["symbol", "account", "name", "asset_class", "qty", "price", "currency", "value", "share", "cost",
                  "pnl", "pnl_pct", "trend"]],
        numbers={"qty": 4, "price": 2, "value": 2, "cost": 2, "pnl": 2},
        percents=["share", "pnl_pct"],
        signed=["pnl", "pnl_pct"],
        trends=["trend"],
        search="positions",
        height="content",  # every position at once, no scrolling inside the table (D-082)
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


positions()

if v.warnings:
    with st.expander(f":material/warning: Uwagi do wyceny ({len(v.warnings)})"):
        for warning in v.warnings:
            st.markdown(f"- {warning}")
