"""Exchange hours (D-066, D-068) and the session-based "Dzisiaj" tile (D-067). No network."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from streamlit.testing.v1 import AppTest

from finance_analytics.config import APP_DIR, DATA_DIR_ENV, Settings
from finance_analytics.market.hours import (
    CLOSE,
    EARLY_CLOSE,
    EXCHANGES,
    closing_time,
    gpw_holidays,
    is_trading_day,
    london_holidays,
    us_holidays,
    xetra_holidays,
)

WARSAW = ZoneInfo("Europe/Warsaw")


def test_holidays_follow_the_nyse_calendar():
    assert us_holidays(2026) == {
        date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3), date(2026, 5, 25),
        date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25),
    }
    # 2027: Juneteenth and Christmas on a Saturday move to Friday, Independence Day on a Sunday to Monday.
    assert us_holidays(2027) == {
        date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26), date(2027, 5, 31),
        date(2027, 6, 18), date(2027, 7, 5), date(2027, 9, 6), date(2027, 11, 25), date(2027, 12, 24),
    }
    # New Year's Day 2028 is a Saturday: not observed on 31 December.
    assert is_trading_day(date(2027, 12, 31))
    assert not is_trading_day(date(2026, 11, 21))  # Saturday


@pytest.mark.parametrize(
    ("day", "close"),
    [
        (date(2025, 7, 3), EARLY_CLOSE),  # Thursday before Independence Day
        (date(2026, 7, 2), CLOSE),  # Independence Day observed on Friday 3 July: no early close
        (date(2026, 11, 27), EARLY_CLOSE),  # day after Thanksgiving
        (date(2026, 12, 24), EARLY_CLOSE),
        (date(2026, 11, 18), CLOSE),
    ],
)
def test_early_closes(day, close):
    assert closing_time(day) == close


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def phase(name: str, now: datetime):
    return next(e for e in EXCHANGES if e.name == name).status(now)


def local(moment: datetime) -> time:
    return moment.astimezone(WARSAW).time()


def state(name: str, now: datetime) -> tuple[str, str, time]:
    """(phase now, next phase, when it starts in Polish time)."""
    status = phase(name, now)
    return status.phase, status.next_phase, local(status.next_change)


def test_us_phases_through_the_day():
    # Wednesday 18.11.2026, Polish time = UTC + 1, New York = UTC - 5.
    assert state("USA", utc(2026, 11, 18, 8, 0)) == ("closed", "pre", time(10, 0))
    assert state("USA", utc(2026, 11, 18, 12, 0)) == ("pre", "open", time(15, 30))
    assert state("USA", utc(2026, 11, 18, 15, 0)) == ("open", "post", time(22, 0))
    assert state("USA", utc(2026, 11, 18, 23, 30)) == ("post", "closed", time(2, 0))
    assert phase("USA", utc(2026, 11, 18, 8, 0)).next_open == utc(2026, 11, 18, 14, 30)  # the real open
    assert phase("USA", utc(2026, 11, 18, 15, 0)).next_open == utc(2026, 11, 19, 14, 30)
    assert phase("USA", utc(2026, 11, 19, 1, 30)).next_change == utc(2026, 11, 19, 9, 0)  # the next pre-market
    friday_night = phase("USA", utc(2026, 11, 21, 2, 0))  # Saturday 3:00 in Poland
    assert (friday_night.phase, friday_night.next_change) == ("closed", utc(2026, 11, 23, 9, 0))


def test_us_holidays_and_early_close():
    assert phase("USA", utc(2026, 11, 26, 15, 0)).next_change == utc(2026, 11, 27, 9, 0)  # Thanksgiving
    assert state("USA", utc(2026, 11, 27, 17, 0)) == ("open", "post", time(19, 0))
    assert state("USA", utc(2026, 11, 27, 19, 0)) == ("post", "closed", time(23, 0))  # 17:00 in New York


def test_opening_hour_moves_while_daylight_saving_differs():
    # The US switches on 8 March 2026, Europe on 29 March: for three weeks the open is at 14:30 in Poland.
    assert state("USA", utc(2026, 3, 9, 8, 0)) == ("pre", "open", time(14, 30))
    assert state("USA", utc(2026, 3, 30, 8, 0)) == ("pre", "open", time(15, 30))
    # London and Frankfurt switch with Poland: 9:00 all year.
    assert state("Londyn", utc(2026, 3, 9, 6, 0)) == ("closed", "open", time(9, 0))
    assert state("Londyn", utc(2026, 7, 1, 5, 0)) == ("closed", "open", time(9, 0))


def test_european_sessions():
    noon = utc(2026, 11, 18, 11, 0)
    assert [(e.name, *state(e.name, noon)) for e in EXCHANGES[1:]] == [
        ("Londyn", "open", "closed", time(17, 30)), ("Niemcy", "open", "closed", time(17, 30)),
        ("Warszawa", "open", "closed", time(17, 0)),
    ]
    evening = utc(2026, 11, 18, 16, 45)  # 17:45 in Poland: after every European close, no extended sessions
    assert {state(e.name, evening) for e in EXCHANGES[1:]} == {("closed", "open", time(9, 0))}


def test_european_holidays():
    assert london_holidays(2026) == {
        date(2026, 1, 1), date(2026, 4, 3), date(2026, 4, 6), date(2026, 5, 4), date(2026, 5, 25),
        date(2026, 8, 31), date(2026, 12, 25), date(2026, 12, 28),  # Boxing Day on Saturday -> Monday
    }
    assert {date(2027, 12, 27), date(2027, 12, 28)} <= london_holidays(2027)  # Christmas on a Saturday
    assert phase("Londyn", utc(2026, 12, 24, 11, 0)).next_change == utc(2026, 12, 24, 12, 30)  # half day
    assert date(2026, 12, 31) in xetra_holidays(2026) and date(2026, 5, 25) not in xetra_holidays(2026)
    # GPW: Polish public holidays plus Good Friday, Christmas Eve and New Year's Eve.
    assert {date(2026, 1, 6), date(2026, 4, 3), date(2026, 6, 4), date(2026, 11, 11), date(2026, 12, 31)} <= (
        gpw_holidays(2026))
    assert phase("Warszawa", utc(2026, 11, 11, 10, 0)).next_change == datetime(2026, 11, 12, 9, 0, tzinfo=WARSAW)


def test_market_text_counts_to_the_regular_open_or_close():
    from ui.fmt import NBSP, market_text

    def text(name, now):
        return tuple(s.replace(NBSP, " ") for s in market_text(phase(name, now), now, WARSAW))

    # Before and during the pre-market the time runs to the real open; the hover says which it is.
    assert text("USA", utc(2026, 11, 18, 8, 0)) == (
        "do otwarcia", "6 h 30 min", "Zamknięta · pre-market dziś 10:00 · otwarcie dziś 15:30")
    assert text("USA", utc(2026, 11, 18, 12, 0)) == ("do otwarcia", "2 h 30 min", "Pre-market · otwarcie dziś 15:30")
    assert text("USA", utc(2026, 11, 18, 15, 0)) == ("do zamknięcia", "6 h 00 min", "Otwarta · zamknięcie dziś 22:00")
    # In the post-market too: the next real open, tomorrow.
    assert text("USA", utc(2026, 11, 18, 23, 30)) == (
        "do otwarcia", "15 h 00 min", "Post-market do 02:00 · otwarcie dziś 15:30")
    assert text("Warszawa", utc(2026, 11, 18, 7, 15)) == ("do otwarcia", "45 min", "Zamknięta · otwarcie dziś 09:00")
    # Over a weekend the countdown counts days.
    assert text("Warszawa", utc(2026, 11, 20, 17, 0)) == ("do otwarcia", "2 d 15 h", "Zamknięta · otwarcie pon. 09:00")


@pytest.fixture
def settings(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data")
    monkeypatch.setenv(DATA_DIR_ENV, str(settings.data_dir))
    return settings


def test_sidebar_lists_the_exchanges(settings):
    at = AppTest.from_file(str(APP_DIR / "main.py"), default_timeout=60).run()
    assert not at.exception
    assert any(c.value == "Giełdy" for c in at.sidebar.caption)  # the title alone, so its "?" stays beside it
    board = next(e.proto.body for e in at.sidebar.get("html") if "grid-template-columns" in e.proto.body)
    assert all(f">{name}<" in board for name in ("USA", "Londyn", "Niemcy", "Warszawa"))
    assert "tabular-nums" in board  # digits line up in the time column
    assert "border-radius:50%" in board  # the status lamps


# ------------------------------------------------------------------ session-based "Dzisiaj" tile (D-067)


def test_days_count_towards_the_next_session():
    from finance_analytics.market.hours import last_close, last_opened_session, previous_trading_day, session_of

    assert session_of(date(2026, 11, 21)) == date(2026, 11, 23)  # Saturday -> Monday
    assert session_of(date(2026, 11, 26)) == date(2026, 11, 27)  # Thanksgiving -> Friday
    assert session_of(date(2026, 11, 18)) == date(2026, 11, 18)
    assert previous_trading_day(date(2026, 11, 23)) == date(2026, 11, 20)
    assert previous_trading_day(date(2026, 11, 27)) == date(2026, 11, 25)
    # Monday before the open: still Friday's session; from the open on, Monday's.
    assert last_opened_session(utc(2026, 11, 23, 9, 0)) == date(2026, 11, 20)
    assert last_opened_session(utc(2026, 11, 23, 14, 30)) == date(2026, 11, 23)
    assert last_opened_session(utc(2026, 11, 23, 23, 30)) == date(2026, 11, 23)  # after the close, before midnight
    assert last_close(utc(2026, 11, 23, 20, 0)) == utc(2026, 11, 20, 21, 0)
    assert last_close(utc(2026, 11, 23, 21, 0)) == utc(2026, 11, 23, 21, 0)
    assert last_close(utc(2026, 11, 27, 19, 0)) == utc(2026, 11, 27, 18, 0)  # early close


def _week():
    import pandas as pd

    days = pd.date_range("2026-11-18", "2026-11-23")  # Wednesday .. Monday
    # Thursday +10, Friday +20, the weekend flat, Monday morning +10 from live currency rates.
    values = pd.Series([1000.0, 1010.0, 1030.0, 1030.0, 1030.0, 1040.0], index=days)
    flows = pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    moved = pd.DatetimeIndex(["2026-11-19", "2026-11-20", "2026-11-23"])
    return values, flows, moved


def test_today_by_session_keeps_the_last_session_until_the_open():
    import pandas as pd

    from finance_analytics.portfolio.today import today_result

    values, flows, moved = _week()
    monday_morning = utc(2026, 11, 23, 9, 0)
    calendar = today_result(values, flows, moved, by_us_session=False, now=monday_morning)
    assert calendar.day == pd.Timestamp("2026-11-23")
    assert calendar.change == pytest.approx((10.0, 10 / 1030))

    session = today_result(values, flows, moved, by_us_session=True, now=monday_morning)
    assert session.day == pd.Timestamp("2026-11-20")  # Friday's session until Monday's open
    assert session.change == pytest.approx((20.0, 20 / 1010))
    assert list(session.per_day.index) == [pd.Timestamp("2026-11-19"), pd.Timestamp("2026-11-20")]

    open_ = today_result(values, flows, moved, by_us_session=True, now=utc(2026, 11, 23, 15, 0))
    assert open_.day == pd.Timestamp("2026-11-23")
    assert open_.change == pytest.approx((10.0, 10 / 1030))  # since Friday's close, the weekend included
    assert open_.per_day.iloc[-1] == pytest.approx(10 / 1030)


def test_today_by_session_folds_a_holiday_and_ignores_deposits():
    import pandas as pd

    from finance_analytics.portfolio.today import today_result

    days = pd.date_range("2026-11-25", "2026-11-27")  # Wednesday, Thanksgiving, Friday
    values = pd.Series([1000.0, 1505.0, 1520.0], index=days)  # +5 on the currency on Thursday, a 500 deposit
    flows = pd.Series([500.0], index=[pd.Timestamp("2026-11-26")])
    moved = pd.DatetimeIndex(days[1:])
    friday = today_result(values, flows, moved, by_us_session=True, now=utc(2026, 11, 27, 17, 0))
    assert friday.day == pd.Timestamp("2026-11-27")
    amount, pct = friday.change
    assert amount == pytest.approx(20.0)  # Thursday's +5 and Friday's +15, not the deposit
    assert pct == pytest.approx(1505 / 1500 * 1520 / 1505 - 1)
