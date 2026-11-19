"""The live price feed (D-069): polling cadence, the streaming connection, pauses and the offline guarantee.

No network: a fake quote client, a fake stream and a fake clock.
"""

from __future__ import annotations

import socket
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest
from conftest import go_online

from finance_analytics.config import Settings
from finance_analytics.market import feed as feed_module
from finance_analytics.market.feed import LiveFeed, fx_trading, markets_active
from finance_analytics.market.intraday import read_intraday
from finance_analytics.market.live import read_live
from finance_analytics.market.yahoo import YahooRateLimitError
from finance_analytics.mock.xtb_export import write_mock_export
from finance_analytics.preferences import Preferences, load_preferences, save_preferences
from finance_analytics.sources.sync import import_xtb, sync

MONDAY_US_OPEN = datetime(2026, 11, 16, 16, 0, tzinfo=UTC)  # 11:00 in New York: every exchange is in session
TUESDAY_NIGHT = datetime(2026, 11, 17, 3, 0, tzinfo=UTC)  # all exchanges closed, currencies trade
SATURDAY = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


@pytest.fixture
def imported(tmp_path):
    settings = Settings(data_dir=tmp_path / "data")
    write_mock_export(tmp_path / "export")
    import_xtb(tmp_path / "export", settings)
    sync(settings)
    return settings


class Clock:
    def __init__(self, now: datetime):
        self.seconds, self.moment = 1000.0, now
        self.feeds: list[LiveFeed] = []

    def advance(self, seconds: float, *, viewed: bool = True) -> None:
        """Time passes; with `viewed` a page keeps looking, so the feeds get their heartbeat."""
        self.seconds += seconds
        self.moment += timedelta(seconds=seconds)
        if viewed:
            for feed in self.feeds:
                feed.heartbeat()


class FakeQuotes:
    def __init__(self, error: Exception | None = None):
        self.calls: list[list[str]] = []
        self.error = error

    def last_prices(self, tickers):
        tickers = list(tickers)
        self.calls.append(tickers)
        if self.error:
            raise self.error
        return {t: (4.0, "PLN") if t.endswith("PLN=X") else (100.0, "USD") for t in tickers}


class FakeBars:
    """5-minute bars: two per symbol, the last one a minute before the clock's now."""

    def __init__(self, clock):
        self.clock, self.calls = clock, []

    def bars(self, ticker):
        self.calls.append(ticker)
        price = 4.0 if ticker.endswith("PLN=X") else 100.0
        now = self.clock.moment
        return [(now - timedelta(minutes=6), price * 0.99), (now - timedelta(minutes=1), price)]


class FakeStream:
    """Delivers its messages, then stays connected until closed (or drops at once with `drop=True`)."""

    def __init__(self, messages=(), drop=False):
        self.messages, self.drop = list(messages), drop
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []
        self.closed = threading.Event()
        self.delivered = threading.Event()

    def subscribe(self, symbols):
        self.subscribed += list(symbols)

    def unsubscribe(self, symbols):
        self.unsubscribed += list(symbols)

    def listen(self, handler):
        for message in self.messages:
            handler(message)
        self.delivered.set()
        if self.drop:
            raise ConnectionError("dropped")
        self.closed.wait(5)

    def close(self):
        self.closed.set()


def make_feed(settings, clock, **kwargs) -> LiveFeed:
    kwargs.setdefault("bar_client", FakeBars(clock))
    feed = LiveFeed(settings, clock=lambda: clock.seconds, now=lambda: clock.moment, **kwargs)
    clock.feeds.append(feed)
    return feed


def set_live(settings, **changes) -> None:
    save_preferences(settings, load_preferences(settings).model_copy(update=changes))


def test_market_sessions_and_currency_hours():
    assert markets_active(MONDAY_US_OPEN)
    assert not markets_active(TUESDAY_NIGHT) and fx_trading(TUESDAY_NIGHT)
    assert not markets_active(SATURDAY) and not fx_trading(SATURDAY)
    assert fx_trading(datetime(2026, 11, 22, 22, 30, tzinfo=UTC))  # Sunday evening: Asia opens


def test_polling_follows_the_interval_and_slows_down_when_markets_close(imported):
    go_online(imported)
    set_live(imported, poll_seconds=120)  # the shortest polling interval (D-069)
    clock, client = Clock(MONDAY_US_OPEN), FakeQuotes()
    feed = make_feed(imported, clock, poll_client=client)
    assert feed.step() and len(client.calls) == 1
    assert "USDPLN=X" in client.calls[0]
    clock.advance(60)
    feed.step()
    assert len(client.calls) == 1  # within the interval
    clock.advance(60)
    feed.step()
    assert len(client.calls) == 2
    assert feed.status().state == "live" and feed.status().source == "poll"
    assert read_live(imported.db_path, now=clock.moment)[2] is not None

    clock.moment = TUESDAY_NIGHT  # only currencies trade: at most every 5 minutes
    clock.advance(120)
    feed.step()
    calls = len(client.calls)
    clock.advance(60)
    feed.step()
    assert len(client.calls) == calls
    clock.advance(240)
    feed.step()
    assert len(client.calls) == calls + 1

    clock.moment = SATURDAY
    clock.advance(600)
    feed.step()
    assert len(client.calls) == calls + 1 and feed.status().state == "paused"


def test_rate_limit_pauses_polling_for_two_minutes(imported):
    go_online(imported)
    clock, client = Clock(MONDAY_US_OPEN), FakeQuotes(error=YahooRateLimitError("429"))
    feed = make_feed(imported, clock, poll_client=client)
    feed.step()
    assert feed.status().state == "error" and "2 minuty" in feed.status().message
    clock.advance(60)
    feed.step()
    assert len(client.calls) == 1
    clock.advance(61)
    feed.step()
    assert len(client.calls) == 2


def test_feed_ends_offline_and_when_nobody_looks(imported):
    go_online(imported)
    clock = Clock(MONDAY_US_OPEN)
    feed = make_feed(imported, clock, poll_client=FakeQuotes())
    assert feed.step()
    clock.advance(feed_module.IDLE_TIMEOUT + 1, viewed=False)
    assert not feed.step()  # no page view for 2 minutes
    feed.touch()
    feed.stop()
    save_preferences(imported, Preferences(network="offline"))
    assert not feed.step()


def test_offline_feed_never_starts_or_connects(imported, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    feed = LiveFeed(imported, stream_factory=lambda: pytest.fail("stream opened offline"))
    feed.touch()
    assert feed._thread is None and feed.status().state == "off"
    assert not feed.step()


def test_stream_subscribes_and_saves_ticks(imported):
    go_online(imported)
    set_live(imported, live_source="stream")
    messages = [{"id": "NVDA", "price": 181.5, "currency": "USD"},
                {"id": "VUAA.L", "price": 10450.0, "currency": "GBp"},
                {"id": "USDPLN=X", "price": 3.65},
                {"id": "BAD", "price": float("nan")}]
    stream = FakeStream(messages)
    clock = Clock(MONDAY_US_OPEN)
    feed = make_feed(imported, clock, stream_factory=lambda: stream, poll_client=FakeQuotes())
    feed.step()
    assert "USDPLN=X" in stream.subscribed and "NVDA" in stream.subscribed
    assert stream.delivered.wait(5)
    feed.step()  # flush
    prices, fx, at = read_live(imported.db_path, now=clock.moment)
    assert prices["NVDA"] == 181.5 and prices["VUAA.L"] == pytest.approx(104.5) and fx["USD"] == 3.65
    assert "BAD" not in prices and at is not None
    assert feed.status().source == "stream" and feed.status().state == "live"
    feed.stop()
    assert stream.closed.is_set()


def test_stream_reconnects_after_a_drop_with_growing_pauses(imported):
    go_online(imported)
    set_live(imported, live_source="stream")
    streams = []

    def factory():
        streams.append(FakeStream(drop=True))
        return streams[-1]

    clock = Clock(MONDAY_US_OPEN)
    feed = make_feed(imported, clock, stream_factory=factory, poll_client=FakeQuotes())
    feed.step()
    assert streams[0].delivered.wait(5)
    _wait_for(lambda: not feed._listener.is_alive())
    feed.step()  # notices the drop
    assert feed.status().state == "connecting" and "przerwany" in feed.status().message
    feed.step()
    assert len(streams) == 1  # waits 5 s first
    clock.advance(5)
    feed.step()
    assert len(streams) == 2
    feed.stop()


def test_stream_polls_tickers_it_is_silent_about(imported):
    go_online(imported)
    set_live(imported, live_source="stream")
    stream, client = FakeStream([{"id": "NVDA", "price": 181.5, "currency": "USD"}]), FakeQuotes()
    clock = Clock(MONDAY_US_OPEN)
    feed = make_feed(imported, clock, stream_factory=lambda: stream, poll_client=client)
    feed.step()
    assert stream.delivered.wait(5)
    clock.advance(feed_module.SILENT_AFTER)
    feed._last_tick["NVDA"] = feed._last_message = clock.seconds  # NVDA keeps ticking (the stream is not mute)
    feed.step()
    assert client.calls and "NVDA" not in client.calls[0] and "USDPLN=X" in client.calls[0]
    feed.stop()


def test_stream_pauses_when_every_market_is_closed(imported):
    go_online(imported)
    set_live(imported, live_source="stream")
    clock = Clock(SATURDAY)
    feed = make_feed(imported, clock, stream_factory=lambda: pytest.fail("connected at the weekend"))
    feed.step()
    assert feed.status().state == "paused"


def _wait_for(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_feed_keeps_the_intraday_bars(imported):
    """D-070: 5-minute bars when the feed starts, then every 15 minutes while something trades."""
    go_online(imported)
    clock = Clock(MONDAY_US_OPEN)
    bars = FakeBars(clock)
    feed = make_feed(imported, clock, poll_client=FakeQuotes(), bar_client=bars)
    feed.step()
    first = len(bars.calls)
    assert first and "USDPLN=X" in bars.calls
    clock.advance(600)
    feed.step()
    assert len(bars.calls) == first
    clock.advance(301)
    feed.step()
    assert len(bars.calls) == 2 * first
    quotes = read_intraday(imported.db_path, clock.moment - timedelta(hours=1), clock.moment)
    assert "NVDA" in quotes.columns and len(quotes) >= 3  # bars plus the polled live quotes


def test_a_stream_that_sends_nothing_is_replaced_by_polling(imported):
    """D-075: Yahoo kept the connection open and sent no price at all. After a minute of silence while markets
    trade, the feed polls every held ticker every 2 minutes, says so, and tries the stream again after 5 minutes."""
    go_online(imported)
    set_live(imported, live_source="stream")
    streams, client = [], FakeQuotes()

    def factory():
        streams.append(FakeStream())  # connected, silent
        return streams[-1]

    clock = Clock(MONDAY_US_OPEN)
    feed = make_feed(imported, clock, stream_factory=factory, poll_client=client)
    feed.step()
    assert feed.status().state == "live" and not client.calls
    clock.advance(feed_module.STREAM_MUTE_AFTER - 1)
    feed.step()
    assert not client.calls  # not yet
    clock.advance(1)
    feed.step()
    assert streams[0].closed.is_set() and len(client.calls) == 1 and "USDPLN=X" in client.calls[0]
    status = feed.status()
    assert status.state == "muted" and status.source == "stream" and "nie przysyła" in status.message
    assert read_live(imported.db_path, now=clock.moment)[2] is not None
    clock.advance(60)
    feed.step()
    assert len(client.calls) == 1  # every 2 minutes, not more often
    clock.advance(60)
    feed.step()
    assert len(client.calls) == 2
    clock.advance(feed_module.MUTE_RETRY_STREAM)
    feed.step()
    assert len(streams) == 2  # the stream gets another chance
    feed.stop()


def test_a_working_stream_is_not_taken_for_a_mute_one(imported):
    go_online(imported)
    set_live(imported, live_source="stream")
    stream, client = FakeStream([{"id": "NVDA", "price": 181.5, "currency": "USD"}]), FakeQuotes()
    clock = Clock(MONDAY_US_OPEN)
    feed = make_feed(imported, clock, stream_factory=lambda: stream, poll_client=client)
    feed.step()
    assert stream.delivered.wait(5)
    clock.advance(30)
    feed._last_message = clock.seconds  # it keeps sending
    clock.advance(30)
    feed.step()
    assert not client.calls and not stream.closed.is_set() and feed.status().state == "live"
    feed.stop()


def test_a_quiet_stream_at_night_is_fine(imported):
    """Only currencies trade: a stream with nothing to say for a while is not broken."""
    go_online(imported)
    set_live(imported, live_source="stream")
    stream, client = FakeStream(), FakeQuotes()
    clock = Clock(TUESDAY_NIGHT)
    feed = make_feed(imported, clock, stream_factory=lambda: stream, poll_client=client)
    feed.step()
    clock.advance(feed_module.STREAM_MUTE_AFTER * 3)
    feed.step()
    assert not stream.closed.is_set() and feed.status().state != "muted"
    feed.stop()


def test_normal_close_is_not_logged_as_an_error():
    import logging

    from websockets.exceptions import ConnectionClosedOK

    def record(exc: BaseException) -> logging.LogRecord:
        return logging.LogRecord("yfinance", logging.ERROR, "live.py", 1, "Error while listening to messages: %s",
                                 (exc,), (type(exc), exc, None))

    flt = feed_module._NormalCloseFilter()
    assert not flt.filter(record(ConnectionClosedOK(None, None)))
    assert flt.filter(record(ConnectionError("dropped")))
