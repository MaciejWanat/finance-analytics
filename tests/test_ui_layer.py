from datetime import date

import pandas as pd
from ui.fmt import MINUS, NBSP, fmt_date, fmt_money, fmt_money_compact, fmt_number, fmt_pct
from ui.theme import OTHER_LABEL, TOKENS, color_map, template


def test_polish_number_formatting():
    assert fmt_number(12345.678, 2) == f"12{NBSP}345,68"
    assert fmt_number(-1234.5, 1) == f"{MINUS}1{NBSP}234,5"
    assert fmt_number(-0.001, 2) == "0,00"
    assert fmt_number(None) == "–"
    assert fmt_number(float("nan")) == "–"


def test_money_percent_and_date():
    assert fmt_money(12345.6) == f"12{NBSP}345,60{NBSP}zł"
    assert fmt_money(99, "USD") == f"99,00{NBSP}USD"
    assert fmt_money(250, signed=True, decimals=0) == f"+250{NBSP}zł"
    assert fmt_pct(0.034) == "+3,4%"
    assert fmt_pct(-0.0123, 2) == f"{MINUS}1,23%"
    assert fmt_money_compact(1284) == f"1{NBSP}284{NBSP}zł"
    assert fmt_money_compact(129_400) == f"129,4{NBSP}tys.{NBSP}zł"
    assert fmt_money_compact(4_210_000) == f"4,21{NBSP}mln{NBSP}zł"
    assert fmt_date(date(2026, 11, 16)) == "16.11.2026"


def test_color_follows_entity_not_rank():
    full = color_map(["a", "b", "c"], "light")
    filtered = color_map(["a", "c"], "light")
    assert full["a"] == filtered["a"] == TOKENS["light"].series[0]
    # Callers keep keys in a stable order; the slot is the position in that order.
    assert full["c"] == TOKENS["light"].series[2]
    assert filtered["c"] == TOKENS["light"].series[1]


def test_palette_never_cycles():
    keys = [f"s{i}" for i in range(10)]
    colors = color_map(keys, "dark")
    assert len({colors[k] for k in keys[:8]}) == 8
    assert colors["s8"] == colors["s9"] == colors[OTHER_LABEL] == TOKENS["dark"].other


def test_template_uses_polish_separators_and_transparent_background():
    for mode in ("light", "dark"):
        layout = template(mode).layout
        assert layout.separators == ", "
        assert layout.paper_bgcolor == "rgba(0,0,0,0)"
        assert list(layout.colorway) == list(TOKENS[mode].series)


def test_chart_builders_produce_figures():
    from ui.charts import area_total, line_chart, stacked_bars

    idx = pd.date_range("2026-01-01", periods=5, freq="D")
    df = pd.DataFrame({"A": range(5), "B": range(5, 10)}, index=idx)
    assert len(area_total(df["A"], name="A", mode="light").data) == 1
    assert len(line_chart(df, mode="dark").data) == 2
    bars = stacked_bars(df, mode="light")
    assert bars.layout.barmode == "stack"


def test_category_bars_one_column_per_part_with_shares():
    from ui.charts import category_bars

    fig = category_bars(pd.Series({"B": 300.0, "A": 100.0, "Z": 0.0}), mode="light")
    (trace,) = fig.data
    assert list(trace.x) == ["B", "A"]  # zero-value parts are dropped
    assert list(trace.text) == ["75%", "25%"]
    assert not fig.layout.showlegend


def test_every_glossary_key_used_by_pages_exists():
    import re

    from conftest import APP
    from ui.glossary import G

    used = set()
    for path in APP.rglob("*.py"):
        used |= set(re.findall(r'G\["([a-z0-9_]+)"\]', path.read_text(encoding="utf-8")))
    assert used, "pages should use the glossary"
    assert used <= set(G), sorted(used - set(G))


def test_duration_and_relative_moment():
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from ui.fmt import fmt_duration, fmt_when

    assert fmt_duration(timedelta(hours=2, minutes=14)) == f"2{NBSP}h 14{NBSP}min"
    assert fmt_duration(timedelta(hours=3, minutes=5)) == f"3{NBSP}h 05{NBSP}min"  # aligned in a column
    assert fmt_duration(timedelta(hours=3)) == f"3{NBSP}h 00{NBSP}min"
    assert fmt_duration(timedelta(days=2, hours=9, minutes=30)) == f"2{NBSP}d 09{NBSP}h"  # a weekend
    assert fmt_duration(timedelta(minutes=44, seconds=1)) == f"45{NBSP}min"  # rounded up
    assert fmt_duration(timedelta(seconds=5)) == f"1{NBSP}min"

    warsaw = ZoneInfo("Europe/Warsaw")
    now = datetime(2026, 11, 20, 23, 0, tzinfo=warsaw)  # Friday
    assert fmt_when(datetime(2026, 11, 20, 23, 30, tzinfo=warsaw), now, warsaw) == "dziś 23:30"
    assert fmt_when(datetime(2026, 11, 21, 15, 30, tzinfo=warsaw), now, warsaw) == "jutro 15:30"
    assert fmt_when(datetime(2026, 11, 23, 15, 30, tzinfo=warsaw), now, warsaw) == "pon. 15:30"
    assert fmt_when(datetime(2026, 12, 1, 15, 30, tzinfo=warsaw), now, warsaw) == "01.12 15:30"


def test_polish_plural():
    from ui.fmt import plural

    words = ("wypłata", "wypłaty", "wypłat")
    assert [plural(n, *words).split(NBSP)[1] for n in (1, 2, 4, 5, 12, 13, 22, 33, 100)] == [
        "wypłata", "wypłaty", "wypłaty", "wypłat", "wypłat", "wypłat", "wypłaty", "wypłaty", "wypłat",
    ]


def test_table_renders_numeric_columns_that_are_all_empty():
    # Regression (D-029): a percent column of only None (e.g. XIRR for windows under a year) is
    # object-typed; it used to be turned into "–" text and then crash the percent formatter.
    from streamlit.testing.v1 import AppTest

    def page():
        import pandas as pd
        from ui.components import table

        table(pd.DataFrame({"account": ["A"], "twr": [0.1], "xirr": [None], "when": [None]}),
              percents=["twr", "xirr"], datetimes=["when"])

    at = AppTest.from_function(page, default_timeout=30).run()
    assert not at.exception


def test_table_can_label_an_unknown_numeric_value():
    from streamlit.testing.v1 import AppTest

    def page():
        import pandas as pd
        from ui.components import table

        table(pd.DataFrame({"cost": [None, 123.0]}), numbers={"cost": 2}, missing_labels={"cost": "unknown"})

    at = AppTest.from_function(page, default_timeout=30).run()
    assert not at.exception


def test_detail_chart_opens_on_the_period_and_formats_the_hover():
    import pandas as pd
    from ui.charts import detail_chart

    days = pd.date_range("2024-01-01", "2026-11-13", freq="D")
    series = pd.Series(range(len(days)), index=days, dtype=float)
    start = pd.Timestamp("2026-01-01")
    fig = detail_chart(series, name="Wynik", mode="dark", start=start)
    assert fig.layout.xaxis.rangeslider.visible
    assert [b.label for b in fig.layout.xaxis.rangeselector.buttons] == ["1D", "1T", "1M", "6M", "YTD", "1R", "3L",
                                                                        "Maks."]
    assert fig.layout.meta["fa_fit_y"]  # the y-axis follows the visible range (D-076)
    assert pd.Timestamp(fig.layout.xaxis.range[0]) == start
    assert fig.data[0].hovertemplate.startswith("%{y:,.2f} zł")
    pct = detail_chart(series / 100, name="TWR", mode="light", kind="pct")
    assert pct.data[0].hovertemplate.startswith("%{y:+.2%}") and pct.layout.xaxis.range is None


def test_table_search_keeps_matching_rows_only():
    from ui.components import filter_rows

    df = pd.DataFrame({"symbol": ["XYZ.US", "AMD.US", "VUAA.UK"], "name": ["Xyz Corp", "Advanced Micro", "S&P 500"],
                       "value": [1.0, 2.0, 3.0], "trend": [[1, 2], [3, 4], [5, 6]]})
    assert filter_rows(df, "xy")["symbol"].tolist() == ["XYZ.US"]
    assert filter_rows(df, ".us")["symbol"].tolist() == ["XYZ.US", "AMD.US"]
    assert filter_rows(df, "micro")["symbol"].tolist() == ["AMD.US"]
    assert filter_rows(df, "zzz").empty


def test_live_fragments_slow_down_while_markets_are_quiet():
    """D-071: the user's pace while an exchange is in session, 60 s while only currencies trade, 5 min when
    nothing trades, nothing offline."""
    from datetime import UTC, datetime, timedelta

    from ui.data import live_every

    from finance_analytics.preferences import Preferences

    online = Preferences(network="online", live_source="stream", stream_seconds=5)
    wednesday_noon = datetime(2026, 11, 18, 11, 0, tzinfo=UTC)  # Xetra, London and the GPW in session
    wednesday_night = datetime(2026, 11, 19, 3, 0, tzinfo=UTC)  # US post-market over (01:00 UTC): currencies only
    saturday = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)
    assert live_every(online, wednesday_noon) == timedelta(seconds=5)
    assert live_every(online, wednesday_night) == timedelta(seconds=60)
    assert live_every(online, saturday) == timedelta(minutes=5)
    assert live_every(Preferences(), wednesday_noon) is None


def test_health_tiles_formatting_and_colours():
    from ui.health import HealthTile, fmt_bytes, fmt_cpu, health_html

    assert fmt_cpu(3.14) == "3,1%"
    assert fmt_cpu(None) == "–"
    assert fmt_bytes(412 * 2**20) == f"412{NBSP}MB"
    assert fmt_bytes(int(1.4 * 2**30)) == f"1,4{NBSP}GB"
    assert fmt_bytes(None) == "–"
    tokens = TOKENS["light"]
    page = health_html([HealthTile("Procesor", "30,0%", "średnio 1 min", "high"),
                        HealthTile("Wątki", "12", "<b>", "info")], tokens)
    assert tokens.bad in page and "wysokie" in page  # colour and the word
    assert "&lt;b&gt;" in page  # texts are escaped


def test_global_styles_install_the_rolling_digits_once_per_run():
    """D-074: the invisible script that rolls changed KPI digits is mounted by apply_global_styles (main.py)."""
    from streamlit.testing.v1 import AppTest

    def page():
        from ui.components import Kpi, apply_global_styles, kpi_row

        apply_global_styles()
        kpi_row([Kpi("Wartość portfela", "12,3 tys. zł", trend=[1.0, 2.0])])

    at = AppTest.from_function(page).run()
    assert not at.exception, at.exception
    assert len(at.get("bidi_component")) == 1


def test_kpi_row_can_leave_empty_places_after_the_last_tile():
    """D-081: a shorter second row (4 + 3) keeps the tile width of the first."""
    from streamlit.testing.v1 import AppTest

    def page():
        from ui.components import Kpi, kpi_row

        kpi_row([Kpi(f"Kafelek {n}", "1 zł") for n in range(3)], columns=4)

    at = AppTest.from_function(page).run()
    assert not at.exception, at.exception
    assert len(at.columns) == 4 and len(at.metric) == 3


def test_table_can_show_every_row():
    """D-082: "Bieżące pozycje" shows all rows instead of ten and a scrollbar."""
    from streamlit.testing.v1 import AppTest

    def page():
        import pandas as pd
        from ui.components import table

        table(pd.DataFrame({"symbol": [f"S{n}" for n in range(30)]}), height="content")

    at = AppTest.from_function(page).run()
    assert not at.exception, at.exception
    assert len(at.dataframe) == 1 and len(at.dataframe[0].value) == 30


def test_detail_chart_puts_today_every_5_minutes_after_the_daily_history():
    """D-076: "1D" in the enlarged chart shows today's 5-minute curve, joined to the daily history."""
    from datetime import datetime

    import pandas as pd
    from ui.charts import detail_chart

    days = pd.date_range("2026-11-01", "2026-11-18", freq="D")
    daily = pd.Series(range(len(days)), index=days, dtype=float)
    local = datetime.now().astimezone().tzinfo
    moments = pd.date_range("2026-11-18 00:00", "2026-11-18 12:00", freq="5min").tz_localize(local)
    today = pd.Series(100.0, index=moments)
    fig = detail_chart(daily, name="Wartość", mode="light", today=today)
    history, day = fig.data
    assert pd.Timestamp(history.x[-1]) == pd.Timestamp("2026-11-17")  # today's daily point gives way to the curve
    assert pd.Timestamp(day.x[0]) == pd.Timestamp("2026-11-17") and len(day.x) == len(moments) + 1  # joined
    assert "%H:%M" in day.hovertemplate and fig.layout.hovermode == "closest"
    only_daily = detail_chart(daily, name="Wartość", mode="light", today=None)
    assert len(only_daily.data) == 1


def test_one_week_period_starts_seven_days_back():
    """D-078: "1T" is measured from the close seven days before the last day, never before the data starts."""
    import pandas as pd
    from ui.data import RANGES, period_start

    end = pd.Timestamp("2026-11-18")
    assert RANGES[:3] == ["1D", "1T", "1M"]
    assert period_start("1T", pd.Timestamp("2020-01-01"), end) == pd.Timestamp("2026-11-11")
    assert period_start("1T", pd.Timestamp("2026-11-15"), end) == pd.Timestamp("2026-11-15")


def test_table_marks_put_a_coloured_dot_before_each_row():
    from streamlit.testing.v1 import AppTest

    def page():
        import pandas as pd
        from ui.components import table

        table(pd.DataFrame({"name": ["A", "B"], "twr": [0.1, -0.2]}), percents=["twr"], signed=["twr"],
              marks=["#2a78d6", "#eb6834"])

    at = AppTest.from_function(page, default_timeout=30).run()
    assert not at.exception
    frame = at.dataframe[0].value
    assert list(frame.columns)[:2] == [" ", "name"] and frame.iloc[:, 0].tolist() == ["●", "●"]
