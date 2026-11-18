"""Stock exchange hours, computed from each exchange's rules alone, so they work offline and need no data.

Used by the sidebar list of exchanges (D-066, D-068), the session-based "Dzisiaj" tile (D-067) and the daily
update after the US close. Each exchange keeps its own time zone, so zoneinfo handles the weeks in March and
October/November when the US and Europe are on different daylight-saving time. Unscheduled closures (a
national day of mourning, a storm) cannot be known in advance.

- USA (NYSE, Nasdaq): 9:30-16:00 New York time, pre-market from 4:00, post-market until 20:00. Closed on the
  NYSE holidays: one on a Saturday is observed on the Friday before, one on a Sunday on the Monday after, except
  New Year's Day on a Saturday, which is not moved to 31 December. Early close at 13:00 (post-market until
  17:00) on 3 July (when Independence Day falls Tuesday to Friday), the day after Thanksgiving and 24 December.
- London (LSE): 8:00-16:30 London time; closed on the bank holidays of England (a weekend one moves to the next
  weekday); 12:30 on 24 and 31 December.
- Germany (Xetra, Frankfurt): 9:00-17:30 Berlin time; closed on 1 January, Good Friday, Easter Monday, 1 May
  and 24, 25, 26 and 31 December.
- Warsaw (GPW): 9:00-17:00 Warsaw time; closed on Polish public holidays, Good Friday, 24 and 31 December.

European exchanges have no extended sessions, only opening and closing auctions of a few minutes, which are
left out.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import cache
from zoneinfo import ZoneInfo

from finance_analytics.portfolio.bonds import easter_sunday, polish_holidays

NEW_YORK = ZoneInfo("America/New_York")
OPEN = time(9, 30)
CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The n-th given weekday of a month (Monday is 0); n = -1 is the last one."""
    if n > 0:
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    last = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _thanksgiving(year: int) -> date:
    return _nth_weekday(year, 11, 3, 4)


@cache
def us_holidays(year: int) -> frozenset[date]:
    """Full-day closures of the US exchanges in a year, as observed."""
    days = {
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday
        easter_sunday(year) - timedelta(days=2),  # Good Friday
        _nth_weekday(year, 5, 0, -1),  # Memorial Day
        _observed(date(year, 7, 4)),  # Independence Day
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _thanksgiving(year),
        _observed(date(year, 12, 25)),  # Christmas
    }
    if year >= 2022:
        days.add(_observed(date(year, 6, 19)))  # Juneteenth
    new_year = date(year, 1, 1)
    if new_year.weekday() != 5:
        days.add(_observed(new_year))
    return frozenset(days)


def is_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in us_holidays(day.year)


def closing_time(day: date) -> time:
    """New York closing time of a trading day: 16:00, or 13:00 on the scheduled early-close days."""
    early = (
        ((day.month, day.day) == (7, 3) and day.weekday() <= 3)
        or day == _thanksgiving(day.year) + timedelta(days=1)
        or (day.month, day.day) == (12, 24)
    )
    return EARLY_CLOSE if early else CLOSE


def session_of(day: date) -> date:
    """The US trading day a calendar day counts towards: itself, or the next trading day after a weekend or
    holiday, so moves between two sessions (currencies, other exchanges) go to the next one (D-067)."""
    while not is_trading_day(day):
        day += timedelta(days=1)
    return day


def previous_trading_day(day: date) -> date:
    day -= timedelta(days=1)
    while not is_trading_day(day):
        day -= timedelta(days=1)
    return day


def last_opened_session(now: datetime) -> date:
    """The trading day whose session opened most recently: today's from the open on, before it the previous
    one, which stays after its close until the next open (D-067)."""
    local = now.astimezone(NEW_YORK)
    day = local.date()
    if is_trading_day(day) and local >= datetime.combine(day, OPEN, tzinfo=NEW_YORK):
        return day
    return previous_trading_day(day)


def last_close(now: datetime) -> datetime:
    """The most recent close of a US session at or before `now` (timezone-aware)."""
    local = now.astimezone(NEW_YORK)
    day = local.date()
    if is_trading_day(day) and datetime.combine(day, closing_time(day), tzinfo=NEW_YORK) <= local:
        return datetime.combine(day, closing_time(day), tzinfo=NEW_YORK)
    day = previous_trading_day(day)
    return datetime.combine(day, closing_time(day), tzinfo=NEW_YORK)


# ------------------------------------------------------------------------ European exchanges


@cache
def london_holidays(year: int) -> frozenset[date]:
    """Bank holidays of England and Wales, as observed (a weekend one moves to the next weekday)."""
    easter = easter_sunday(year)
    new_year = date(year, 1, 1)
    days = {
        new_year + timedelta(days={5: 2, 6: 1}.get(new_year.weekday(), 0)),
        easter - timedelta(days=2),
        easter + timedelta(days=1),
        _nth_weekday(year, 5, 0, 1),  # Early May bank holiday
        _nth_weekday(year, 5, 0, -1),  # Spring bank holiday
        _nth_weekday(year, 8, 0, -1),  # Summer bank holiday
    }
    christmas = date(year, 12, 25)
    # Christmas and Boxing Day take the first two weekdays from 25 December on.
    day, left = christmas, 2
    while left:
        if day.weekday() < 5:
            days.add(day)
            left -= 1
        day += timedelta(days=1)
    return frozenset(days)


def _london_close(day: date) -> time:
    return time(12, 30) if (day.month, day.day) in ((12, 24), (12, 31)) else time(16, 30)


@cache
def xetra_holidays(year: int) -> frozenset[date]:
    easter = easter_sunday(year)
    return frozenset({
        date(year, 1, 1), easter - timedelta(days=2), easter + timedelta(days=1), date(year, 5, 1),
        date(year, 12, 24), date(year, 12, 25), date(year, 12, 26), date(year, 12, 31),
    })


@cache
def gpw_holidays(year: int) -> frozenset[date]:
    """Polish public holidays plus the days the Warsaw exchange is closed anyway."""
    good_friday = easter_sunday(year) - timedelta(days=2)
    return frozenset(polish_holidays(year) | {good_friday, date(year, 12, 24), date(year, 12, 31)})


# ------------------------------------------------------------------------ every exchange


@dataclass(frozen=True)
class MarketStatus:
    phase: str  # now: "open", "pre" (pre-market), "post" (post-market) or "closed"
    next_phase: str  # the phase that comes next
    next_change: datetime  # when it starts (aware)
    next_open: datetime  # the next regular open (aware); while open, the next trading day's


@dataclass(frozen=True)
class Exchange:
    name: str  # Polish label
    tz: ZoneInfo
    opens: time
    holidays: Callable[[int], frozenset[date]]
    closes: Callable[[date], time]  # closing time of a trading day
    pre_market: time | None = None  # start of the extended session before the open
    post_market: timedelta | None = None  # length of the extended session after the close

    def is_trading_day(self, day: date) -> bool:
        return day.weekday() < 5 and day not in self.holidays(day.year)

    def _at(self, day: date, moment: time) -> datetime:
        return datetime.combine(day, moment, tzinfo=self.tz)

    def _next_open(self, day: date) -> datetime:
        while not self.is_trading_day(day):
            day += timedelta(days=1)
        return self._at(day, self.opens)

    def _closed_until(self, day: date) -> MarketStatus:
        """Closed until the first phase of the next trading day from `day` on: pre-market or the open."""
        opens = self._next_open(day)
        if self.pre_market is not None:
            return MarketStatus("closed", "pre", self._at(opens.date(), self.pre_market), opens)
        return MarketStatus("closed", "open", opens, opens)

    def status(self, now: datetime) -> MarketStatus:
        """The phase at `now` (timezone-aware), the one after it, when that starts, and the next regular open."""
        local = now.astimezone(self.tz)
        day = local.date()
        if self.is_trading_day(day):
            opens, closes = self._at(day, self.opens), self._at(day, self.closes(day))
            if self.pre_market is not None and local < self._at(day, self.pre_market):
                return self._closed_until(day)
            if local < opens:
                return MarketStatus("pre" if self.pre_market is not None else "closed", "open", opens, opens)
            tomorrow = self._next_open(day + timedelta(days=1))
            if local < closes:
                return MarketStatus("open", "closed" if self.post_market is None else "post", closes, tomorrow)
            if self.post_market is not None and local < closes + self.post_market:
                return MarketStatus("post", "closed", closes + self.post_market, tomorrow)
        return self._closed_until(day + timedelta(days=1))


US = Exchange("USA", NEW_YORK, OPEN, us_holidays, closing_time, pre_market=time(4, 0), post_market=timedelta(hours=4))
EXCHANGES = (
    US,
    Exchange("Londyn", ZoneInfo("Europe/London"), time(8, 0), london_holidays, _london_close),
    Exchange("Niemcy", ZoneInfo("Europe/Berlin"), time(9, 0), xetra_holidays, lambda day: time(17, 30)),
    Exchange("Warszawa", ZoneInfo("Europe/Warsaw"), time(9, 0), gpw_holidays, lambda day: time(17, 0)),
)
