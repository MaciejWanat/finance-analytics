"""GUS CPI: parser, page scraper, update through the network gate, and the real-return maths (D-025)."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date

import pandas as pd
import pytest
from conftest import go_online

from finance_analytics import reports
from finance_analytics.config import Settings
from finance_analytics.db import connect, migrate
from finance_analytics.market import gus
from finance_analytics.market.network import OfflineError
from finance_analytics.market.update import update_market
from finance_analytics.portfolio import inflation

HEADER = "Nazwa zmiennej;Jednostka terytorialna;Sposób prezentacji;Rok;Miesiąc;Wartość;Flaga;;"
NAME = "Wskaźnik cen towarów i usług konsumpcyjnych"


def _line(kind: str, year: int, month: int, value: str, *, name: str = NAME, territory: str = "Polska") -> str:
    return f"{name};{territory};{kind};{year};{month};{value};;;"


def synthetic_csv() -> bytes:
    """The real layout: cp1250, `;`, decimal comma, trailing `;;`, newest year first, empty future months."""
    lines = [HEADER]
    for month, mom, yoy in [(3, "100,5", "103,0"), (2, "100,0", ""), (1, "101,0", "104,2")]:
        lines += [_line(gus.MOM, 2026, month, mom), _line(gus.YOY, 2026, month, yoy)]
    lines += [_line(gus.MOM, 2026, 4, ""), _line(gus.YOY, 2026, 4, "")]  # not published yet
    lines += [
        _line("Grudzień poprzedniego roku = 100", 2026, 3, "101,5"),  # another presentation: ignored
        _line(gus.MOM, 2026, 3, "999,9", territory="Mazowieckie"),  # another territory: ignored
        _line(gus.MOM, 2026, 3, "888,8", name="Wskaźnik cen produkcji sprzedanej przemysłu"),  # other variable
    ]
    return ("\r\n".join(lines) + "\r\n").encode("cp1250")


def test_parse_real_layout():
    text = gus.decode(synthetic_csv())
    assert "Sposób prezentacji" in text  # cp1250 decoded after UTF-8 failed
    assert gus.parse_csv(text) == [
        (2026, 1, 101.0, 104.2),
        (2026, 2, 100.0, None),  # y/y missing: kept, the chain only needs m/m
        (2026, 3, 100.5, 103.0),
    ]


def test_decode_prefers_utf8_when_valid():
    assert gus.decode("Miesiąc".encode("utf-8-sig")) == "Miesiąc"


def test_parse_rejects_unexpected_layout():
    with pytest.raises(gus.GusError):
        gus.parse_csv("a;b;c\n1;2;3\n")
    with pytest.raises(gus.GusError):
        gus.parse_csv(HEADER + "\r\n")


def test_find_csv_link_in_page():
    html = """
    <a href="/download/gfx/x/1/1/other_report__2026.csv">other</a>
    <a href="/download/gfx/x/1/1/miesieczne_wskazniki_od_1982_roku__102026_2.xlsx">xlsx</a>
    <a class="file" href='/download/gfx/x/1/1/miesieczne_wskazniki_od_1982_roku__102026_2.csv'>csv</a>
    """
    assert gus.find_csv_link(html) == (
        "https://stat.gov.pl/download/gfx/x/1/1/miesieczne_wskazniki_od_1982_roku__102026_2.csv"
    )
    with pytest.raises(gus.GusError):
        gus.find_csv_link("<a href='/a.xlsx'>x</a>")


def test_fetch_cpi_goes_page_then_csv():
    class Response:
        def __init__(self, status, text="", content=b""):
            self.status_code, self.text, self.content = status, text, content

    urls = []

    def get(url, **kwargs):
        urls.append(url)
        if url.endswith(".csv"):
            return Response(200, content=synthetic_csv())
        return Response(200, text='<a href="/d/od_1982__1.csv">csv</a>')

    rows = gus.fetch_cpi(get=get)
    assert urls == [gus.PAGE_URL, "https://stat.gov.pl/d/od_1982__1.csv"]
    assert rows[-1] == (2026, 3, 100.5, 103.0)


# ------------------------------------------------------------------------------- update + gate


def _settings(tmp_path) -> Settings:
    settings = Settings(data_dir=tmp_path / "data")
    settings.data_dir.mkdir(parents=True)
    with closing(connect(settings.db_path)) as conn:
        migrate(conn)
    return settings


ROWS = [(2026, 1, 101.0, 104.2), (2026, 2, 100.0, None), (2026, 3, 100.5, 103.0)]


def test_update_market_fetches_cpi_once_a_day(tmp_path):
    settings = _settings(tmp_path)
    go_online(settings)
    calls = []

    def fetch():
        calls.append(1)
        return ROWS

    kwargs = {"today": date.today(), "cpi_fetch": fetch, "fx_fetch": lambda c, s, e: []}
    first = update_market(settings, **kwargs)
    assert first.cpi.fetched == 3 and not first.errors
    second = update_market(settings, **kwargs)
    assert second.cpi.skipped and len(calls) == 1
    with closing(sqlite3.connect(settings.db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM cpi_monthly").fetchone()[0] == 3
        logged = conn.execute("SELECT date_from, date_to FROM fetch_log WHERE source = 'gus' AND key = 'CPI'")
        assert logged.fetchone() == ("2026-01-01", "2026-03-01")
    cpi = reports.cpi_monthly(settings.db_path)
    assert list(cpi["mom"]) == [101.0, 100.0, 100.5]
    assert cpi["month"].iloc[0] == pd.Timestamp("2026-01-01")


def test_cpi_failure_is_reported_and_retried(tmp_path):
    settings = _settings(tmp_path)
    go_online(settings)

    def broken():
        raise gus.GusError("GUS page: HTTP 503")

    kwargs = {"today": date.today(), "fx_fetch": lambda c, s, e: []}
    report = update_market(settings, cpi_fetch=broken, **kwargs)
    assert report.errors == {"GUS CPI": "GUS page: HTTP 503"}
    retry = update_market(settings, cpi_fetch=lambda: ROWS, **kwargs)  # an error does not block the next try
    assert retry.cpi.fetched == 3 and not retry.errors


def test_offline_never_fetches_cpi(tmp_path):
    settings = _settings(tmp_path)

    def must_not_run():
        raise AssertionError("network call in offline mode")

    with pytest.raises(OfflineError):
        update_market(settings, today=date.today(), cpi_fetch=must_not_run)
    assert reports.cpi_monthly(settings.db_path).empty


def test_cpi_monthly_on_unmigrated_database(tmp_path):
    path = tmp_path / "old.db"
    sqlite3.connect(path).close()
    assert reports.cpi_monthly(path).empty


# ----------------------------------------------------------------------------------- maths


def mom_series(values: list[float], start: str = "2026-01-01") -> pd.Series:
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="MS"))


def test_price_level_chaining():
    levels = inflation.price_level_index(mom_series([150.0, 101.0, 102.0]))
    # The first month is the base (its own m/m is ignored): 100, 100 * 1.01, 101 * 1.02.
    assert levels.tolist() == pytest.approx([100.0, 101.0, 103.02])


def test_price_level_uses_latest_unbroken_run():
    mom = mom_series([101.0, 101.0, 101.0, 100.0, 102.0]).drop(pd.Timestamp("2026-03-01"))
    levels = inflation.price_level_index(mom)
    assert list(levels.index) == [pd.Timestamp("2026-04-01"), pd.Timestamp("2026-05-01")]
    assert levels.tolist() == pytest.approx([100.0, 102.0])


def test_daily_levels_step_and_estimated_flag():
    levels = inflation.price_level_index(mom_series([100.0, 101.0, 102.0]))  # Jan, Feb, Mar 2026
    days = pd.DatetimeIndex(
        ["2025-12-31", "2026-01-31", "2026-02-01", "2026-03-31", "2026-04-02", "2026-04-03", "2026-05-20"]
    )
    daily = inflation.daily_levels(levels, days)
    assert pd.isna(daily["level"].iloc[0])  # before the series starts
    assert daily["level"].iloc[1:].tolist() == pytest.approx([100.0, 101.0, 103.02, 103.02, 103.02, 103.02])
    assert daily["estimated"].tolist() == [False, False, False, False, True, True, True]


def test_window_inflation_and_real_return():
    levels = inflation.price_level_index(mom_series([100.0, 101.0, 102.0]))
    days = pd.date_range("2026-01-01", "2026-03-31", freq="D")
    daily = inflation.daily_levels(levels, days)
    pi = inflation.window_inflation(daily, pd.Timestamp("2026-01-15"), pd.Timestamp("2026-03-15"))
    assert pi == pytest.approx(0.0302)
    assert inflation.window_inflation(daily, pd.Timestamp("2025-06-01"), pd.Timestamp("2026-03-15")) is None
    assert inflation.real_return(0.113, 0.05) == pytest.approx(0.06)
    assert inflation.real_return(0.0, 0.05) == pytest.approx(-0.047619, abs=1e-6)


def test_real_annual_only_from_a_year():
    assert inflation.real_annual(0.1, 200) is None
    assert inflation.real_annual(0.21, 730.5) == pytest.approx(0.1, abs=1e-9)  # (1.21)^(1/2) - 1


def test_cumulative_inflation_and_todays_zloty():
    levels = inflation.price_level_index(mom_series([100.0, 110.0, 100.0]))  # 100, 110, 110
    days = pd.DatetimeIndex(["2026-01-10", "2026-02-10", "2026-03-10"])
    daily = inflation.daily_levels(levels, days)
    assert inflation.cumulative_inflation(daily, days[0]).tolist() == pytest.approx([0.0, 0.10, 0.10])
    values = pd.Series([1000.0, 1100.0, 1210.0], index=days)
    # January money is worth 10% more in March złoty; the last value is unchanged.
    assert inflation.todays_zloty(values, daily).tolist() == pytest.approx([1100.0, 1100.0, 1210.0])


def test_estimated_months():
    levels = inflation.price_level_index(mom_series([100.0, 101.0]))  # Jan, Feb
    assert inflation.estimated_months(levels, pd.Timestamp("2026-02-20")) == 0
    assert inflation.estimated_months(levels, pd.Timestamp("2026-04-02")) == 2
