"""Online mode: the live price feed that runs in the background while the app is open (D-069).

One feed per data directory and process (`get_feed`). It runs in its own thread, so the network never
delays a page, and writes to `live_quotes`; pages only read the database. Two sources:

- **poll**: `live.update_live` every `poll_seconds` (2 minutes at least) while some exchange is in session
  (US pre-market and post-market included), every 5 minutes while only currencies trade, not at all at the
  weekend; after a Yahoo rate limit it pauses for 2 minutes;
- **stream**: one connection to Yahoo's streaming service, subscribed to the held tickers and FX pairs; Yahoo
  pushes every new price. Ticks are saved at most once a second; the connection is rebuilt after a drop
  (5 s, then longer pauses up to a minute), the subscription follows the holdings every 5 minutes, and tickers
  the stream stays silent about while a market trades are polled every 5 minutes instead.

It also keeps the 5-minute bars of the "1D" range (`market.intraday`, D-070): when it starts, then every
15 minutes while some market or currencies trade.

The feed runs only in online mode (checked before every connection and on every tick) and only while someone
looks at the app: pages call `touch()`; after 2 minutes without it the thread ends and the connection closes.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from finance_analytics.config import Settings
from finance_analytics.market.hours import EXCHANGES
from finance_analytics.market.intraday import update_intraday
from finance_analytics.market.live import live_symbols, reference_prices, store_quotes, stream_quote, update_live
from finance_analytics.market.network import require_online
from finance_analytics.market.yahoo import YahooRateLimitError
from finance_analytics.preferences import Preferences, PreferencesError, load_preferences

TICK_SECONDS = 1.0  # how often the feed thread wakes up (flush ticks, check the settings)
IDLE_TIMEOUT = 120.0  # seconds without a page view after which the feed stops
QUIET_POLL = 300.0  # poll cadence while only currencies trade
RATE_LIMIT_PAUSE = 120.0
RESUBSCRIBE_EVERY = 300.0  # follow the holdings (a new purchase) in stream mode
SILENT_AFTER = 300.0  # a subscribed ticker without a tick for this long is polled instead
RECONNECT_DELAYS = (5.0, 10.0, 20.0, 40.0, 60.0)
INTRADAY_EVERY = 900.0  # 5-minute bars for the 1D range (D-070)
# A stream that sends nothing at all for this long while a market trades is treated as broken (D-075): Yahoo may
# keep the connection open without pushing a single price.
STREAM_MUTE_AFTER = 60.0
MUTE_POLL_EVERY = 120.0  # meanwhile poll every held ticker; not more often, or Yahoo refuses (D-069)
MUTE_RETRY_STREAM = 300.0  # and try the stream again after this long

# "muted": the stream is connected but sends nothing (seen 2026-11-18); prices come by polling meanwhile (D-075).
State = Literal["off", "connecting", "live", "paused", "error", "muted"]


class Stream(Protocol):
    """A streaming quote connection (yfinance `WebSocket` in production, a fake in tests)."""

    def subscribe(self, symbols: list[str]) -> None: ...
    def unsubscribe(self, symbols: list[str]) -> None: ...
    def listen(self, handler: Callable[[dict], None]) -> None: ...  # blocks until the connection ends
    def close(self) -> None: ...


def yahoo_stream() -> Stream:
    import yfinance as yf

    # websockets 14+ warns that yfinance opens its connection without a context manager; the connection works,
    # and the feed closes it itself. Only this one message from yfinance.live is silenced.
    warnings.filterwarnings("ignore", message=r"connect\(\) must be used as a context manager",
                            category=DeprecationWarning, module=r"yfinance\.live")
    logger = logging.getLogger("yfinance")
    if not any(isinstance(f, _NormalCloseFilter) for f in logger.filters):
        logger.addFilter(_NormalCloseFilter())
    return yf.WebSocket(verbose=False)


class _NormalCloseFilter(logging.Filter):
    """Drops yfinance's "Error while listening" record when the connection was closed normally (code 1000).

    The feed closes the stream itself (idle, resubscribe, mode change), and yfinance logs that as an error with a
    full traceback. A real drop (any other close) is still logged.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        return not (exc is not None and type(exc).__name__ == "ConnectionClosedOK")


@dataclass(frozen=True)
class FeedStatus:
    source: Literal["poll", "stream"]
    state: State
    last_quote: datetime | None = None  # when the newest quote arrived (UTC)
    message: str | None = None  # why it is paused or failing, in Polish


def markets_active(now: datetime) -> bool:
    """Some exchange is in a session: regular, or the US pre-market or post-market."""
    return any(exchange.status(now).phase != "closed" for exchange in EXCHANGES)


def fx_trading(now: datetime) -> bool:
    """Currencies trade from Sunday 22:00 to Friday 22:00 UTC."""
    moment = now.astimezone(UTC)
    if moment.weekday() == 5:
        return False
    if moment.weekday() == 4:
        return moment.hour < 22
    if moment.weekday() == 6:
        return moment.hour >= 22
    return True


class LiveFeed:
    def __init__(
        self,
        settings: Settings,
        *,
        poll_client=None,
        bar_client=None,
        stream_factory: Callable[[], Stream] = yahoo_stream,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.settings = settings
        self.poll_client, self.bar_client = poll_client, bar_client
        self.stream_factory = stream_factory
        self.clock, self.now = clock, now
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_touch = clock()
        self._status = FeedStatus("poll", "off")
        # poll state
        self._next_poll = 0.0
        # stream state
        self._stream: Stream | None = None
        self._listener: threading.Thread | None = None
        self._subscribed: set[str] = set()
        self._buffer: dict[str, tuple[float, str | None]] = {}
        self._last_tick: dict[str, float] = {}
        self._next_connect = 0.0
        self._failures = 0
        self._next_resubscribe = 0.0
        self._next_silent_poll = 0.0
        self._listen_error: str | None = None
        self._connected_at = 0.0
        self._last_message: float | None = None  # when the stream last sent any price (clock seconds)
        self._muted = False  # the stream sent nothing: polling instead until the next try (D-075)
        self._next_mute_poll = 0.0
        self._references: dict[str, tuple[str | None, float | None]] = {}  # (currency, last price) per symbol
        # intraday bars
        self._next_intraday = 0.0
        self._intraday_done = False

    # ------------------------------------------------------------------------------------- public

    def heartbeat(self) -> None:
        """A page is being viewed: keep the feed alive for another `IDLE_TIMEOUT` seconds."""
        self._last_touch = self.clock()

    def touch(self) -> None:
        """A page is being viewed: keep the feed alive, and start it if online and not running."""
        self.heartbeat()
        preferences = self._preferences()
        if preferences is None or not preferences.online:
            return
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._stop.clear()
                self._thread = threading.Thread(target=self._run, name="live-feed", daemon=True)
                self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._close_stream()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)

    def status(self) -> FeedStatus:
        with self._lock:
            return self._status

    # ------------------------------------------------------------------------------------ the loop

    def _preferences(self) -> Preferences | None:
        try:
            return load_preferences(self.settings)
        except PreferencesError:
            return None

    def _set(self, source: str, state: State, message: str | None = None, quote: datetime | None = None) -> None:
        with self._lock:
            last = quote or (self._status.last_quote if self._status.source == source else None)
            self._status = FeedStatus(source, state, last, message)  # type: ignore[arg-type]

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                if not self.step():
                    break
                self._stop.wait(TICK_SECONDS)
        finally:
            self._close_stream()
            with self._lock:
                self._status = FeedStatus(self._status.source, "off", self._status.last_quote)

    def step(self) -> bool:
        """One wake-up of the feed thread; False when it should end (offline, nobody looking, settings broken)."""
        preferences = self._preferences()
        if preferences is None or not preferences.online or not self.settings.db_path.exists():
            return False
        if self.clock() - self._last_touch > IDLE_TIMEOUT:
            return False
        if preferences.live_source == "stream":
            self._stream_step()
        else:
            self._close_stream()
            self._poll_step(preferences)
        self._intraday_step()
        return True

    # -------------------------------------------------------------------------------------- 1D bars

    def _intraday_step(self) -> None:
        """5-minute bars once at the start (the last session, also at the weekend), then every 15 minutes
        while something trades."""
        now, moment = self.now(), self.clock()
        if moment < self._next_intraday:
            return
        self._next_intraday = moment + INTRADAY_EVERY
        if self._intraday_done and not (markets_active(now) or fx_trading(now)):
            return
        try:
            update_intraday(self.settings, live_symbols(self.settings), client=self.bar_client, now=now)
        except YahooRateLimitError:
            self._next_intraday = moment + RATE_LIMIT_PAUSE
            self._next_poll = max(self._next_poll, moment + RATE_LIMIT_PAUSE)
            return
        except Exception:  # network trouble: try again in 5 minutes; the live quotes still add points
            self._next_intraday = moment + QUIET_POLL
            return
        self._intraday_done = True

    # ------------------------------------------------------------------------------------------ poll

    def _poll_step(self, preferences: Preferences) -> None:
        now, moment = self.now(), self.clock()
        if moment < self._next_poll:
            return
        if markets_active(now):
            cadence = float(preferences.poll_seconds)
        elif fx_trading(now):
            cadence = max(float(preferences.poll_seconds), QUIET_POLL)
        else:
            self._set("poll", "paused", "Giełdy i rynek walut są zamknięte.")
            self._next_poll = moment + 60
            return
        try:
            report = update_live(self.settings, now=now, client=self.poll_client)
        except YahooRateLimitError:
            self._set("poll", "error", "Yahoo ogranicza liczbę zapytań; ponowię za 2 minuty.")
            self._next_poll = moment + RATE_LIMIT_PAUSE
            return
        except Exception as exc:  # network trouble: try again on the next interval
            self._set("poll", "error", f"Nie udało się pobrać cen: {exc}")
            self._next_poll = moment + max(cadence, 30.0)
            return
        self._set("poll", "live", quote=now if report.updated else None)
        self._next_poll = moment + cadence

    # ---------------------------------------------------------------------------------------- stream

    def _on_message(self, message: dict) -> None:
        """Runs on the listener thread: keep the newest price per symbol until the next flush."""
        symbol, price = message.get("id"), message.get("price")
        if not symbol or price is None or price != price or price <= 0:
            return
        quote = stream_quote(float(price), message.get("currency"), self._references.get(symbol, (None, None)))
        with self._lock:
            self._buffer[symbol] = quote
            self._last_tick[symbol] = self._last_message = self.clock()

    def _listen(self, stream: Stream) -> None:
        try:
            stream.listen(self._on_message)
            self._listen_error = None
        except Exception as exc:  # the connection dropped
            self._listen_error = str(exc) or type(exc).__name__

    def _close_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            with contextlib.suppress(Exception):
                stream.close()
        listener, self._listener = self._listener, None
        if listener is not None and listener is not threading.current_thread():
            listener.join(timeout=2)
        self._subscribed = set()

    def _flush(self) -> None:
        with self._lock:
            quotes, self._buffer = self._buffer, {}
        if quotes:
            now = self.now()
            store_quotes(self.settings, quotes, now)
            self._set("stream", "live", quote=now)

    def _connect(self) -> None:
        require_online(self.settings)
        symbols = live_symbols(self.settings)
        if not symbols:
            self._set("stream", "paused", "Brak instrumentów do śledzenia.")
            self._next_connect = self.clock() + 60
            return
        self._set("stream", "connecting")
        self._references = reference_prices(self.settings, symbols)
        stream = self.stream_factory()
        try:
            stream.subscribe(symbols)
        except Exception:
            with contextlib.suppress(Exception):
                stream.close()
            raise
        self._stream, self._subscribed = stream, set(symbols)
        moment = self.clock()
        self._connected_at, self._last_message = moment, None
        self._next_resubscribe = moment + RESUBSCRIBE_EVERY
        self._next_silent_poll = moment + SILENT_AFTER
        for symbol in symbols:
            self._last_tick.setdefault(symbol, moment)
        self._listener = threading.Thread(target=self._listen, args=(stream,), name="live-stream", daemon=True)
        self._listener.start()
        self._failures = 0
        self._set("stream", "live")

    def _stream_step(self) -> None:
        now, moment = self.now(), self.clock()
        if not (markets_active(now) or fx_trading(now)):
            self._close_stream()
            self._flush()
            self._set("stream", "paused", "Giełdy i rynek walut są zamknięte.")
            return
        self._flush()
        if self._stream is not None and (self._listener is None or not self._listener.is_alive()):
            error = self._listen_error or "połączenie zamknięte"
            self._close_stream()
            self._schedule_reconnect(f"Strumień przerwany ({error}); łączę ponownie.")
            return
        if self._stream is None:
            if self._muted:
                self._poll_muted(now, moment)
            if moment < self._next_connect:
                return
            try:
                self._connect()
            except Exception as exc:
                self._close_stream()
                self._schedule_reconnect(f"Nie udało się połączyć ze strumieniem: {exc}")
            return
        if self._is_mute(now, moment):
            self._close_stream()
            self._muted, self._next_mute_poll = True, moment
            self._next_connect = moment + MUTE_RETRY_STREAM
            self._poll_muted(now, moment)
            return
        if self._last_message is not None:
            self._muted = False  # the stream works (again)
        if moment >= self._next_resubscribe:
            self._resubscribe()
        if moment >= self._next_silent_poll:
            self._poll_silent(now)

    def _is_mute(self, now: datetime, moment: float) -> bool:
        """Connected, an exchange in session, and not one price for `STREAM_MUTE_AFTER` seconds."""
        if not markets_active(now):
            return False  # only currencies trade: the stream may well be quiet
        with self._lock:
            last = self._last_message
        return moment - (last if last is not None else self._connected_at) >= STREAM_MUTE_AFTER

    def _poll_muted(self, now: datetime, moment: float) -> None:
        """While the stream says nothing: every held ticker by polling, every `MUTE_POLL_EVERY` seconds."""
        if moment < self._next_mute_poll:
            return
        self._next_mute_poll = moment + MUTE_POLL_EVERY
        message = "Strumień Yahoo nie przysyła cen; pobieram je co 2 minuty i co 5 minut próbuję strumienia ponownie."
        try:
            report = update_live(self.settings, now=now, client=self.poll_client)
        except YahooRateLimitError:
            self._next_mute_poll = moment + RATE_LIMIT_PAUSE
            self._set("stream", "error", "Yahoo chwilowo odrzuca zapytania; ponowię za 2 minuty.")
            return
        except Exception as exc:  # network trouble: the next try in 2 minutes
            self._set("stream", "error", f"Strumień milczy, a pobieranie się nie udało: {exc}")
            return
        self._set("stream", "muted", message, quote=now if report.updated else None)

    def _schedule_reconnect(self, message: str) -> None:
        delay = RECONNECT_DELAYS[min(self._failures, len(RECONNECT_DELAYS) - 1)]
        self._failures += 1
        self._next_connect = self.clock() + delay
        self._set("stream", "error" if self._failures > 1 else "connecting", message)

    def _resubscribe(self) -> None:
        self._next_resubscribe = self.clock() + RESUBSCRIBE_EVERY
        wanted = set(live_symbols(self.settings))
        added, removed = sorted(wanted - self._subscribed), sorted(self._subscribed - wanted)
        if self._stream is None or not (added or removed):
            return
        self._references = reference_prices(self.settings, wanted)
        if added:
            self._stream.subscribe(added)
        if removed:
            self._stream.unsubscribe(removed)
        self._subscribed = wanted

    def _poll_silent(self, now: datetime) -> None:
        """Poll the subscribed tickers the stream has said nothing about lately (a market it does not push)."""
        moment = self.clock()
        self._next_silent_poll = moment + SILENT_AFTER
        if not markets_active(now):
            return
        with self._lock:
            silent = sorted(s for s in self._subscribed if moment - self._last_tick.get(s, 0.0) >= SILENT_AFTER)
        if not silent:
            return
        try:
            report = update_live(self.settings, now=now, client=self.poll_client, tickers=silent)
        except Exception:  # the stream keeps working; the next try is in 5 minutes
            return
        if report.updated:
            self._set("stream", "live", quote=now)


_FEEDS: dict[str, LiveFeed] = {}
_FEEDS_LOCK = threading.Lock()


def get_feed(settings: Settings) -> LiveFeed:
    """The one feed of this process for a data directory."""
    key = str(settings.data_dir.resolve())
    with _FEEDS_LOCK:
        feed = _FEEDS.get(key)
        if feed is None:
            feed = _FEEDS[key] = LiveFeed(settings)
        return feed


def last_quote_age(status: FeedStatus, now: datetime | None = None) -> timedelta | None:
    if status.last_quote is None:
        return None
    return (now or datetime.now(UTC)) - status.last_quote
