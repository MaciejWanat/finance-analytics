"""How much CPU and memory the app's own process uses (D-073). Local only: psutil reads this process, nothing is sent.

One `ResourceMonitor` per process (`get_monitor`) samples in its own thread every `SAMPLE_SECONDS` and keeps the
last `HISTORY_SECONDS`. The Ustawienia page reads averages over the last 1 and 5 minutes, so the load of pages the
user has just left (Portfel's live redraws) shows up there too.

CPU is in percent of one core: Python runs mostly on one core (the GIL), so a share of the whole machine would
stay small on a many-core computer however busy the app is. The share of the whole machine is
`cpu_pct / cpu_count`. The live feed's part is the CPU time of its threads (`live-feed`, `live-stream`,
see `market.feed`).
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal, Protocol

import psutil

SAMPLE_SECONDS = 5.0
HISTORY_SECONDS = 900.0  # 15 minutes
FEED_THREADS = ("live-feed", "live-stream")

# Thresholds (D-073). CPU: the 1-minute average, % of one core. Memory: resident size of the process.
CPU_WARN, CPU_HIGH = 25.0, 50.0
MEMORY_WARN, MEMORY_HIGH = 600 * 2**20, 1200 * 2**20

Level = Literal["ok", "warn", "high"]
_ORDER: dict[Level, int] = {"ok": 0, "warn": 1, "high": 2}


class Process(Protocol):
    """The part of `psutil.Process` the monitor uses (a fake in tests)."""

    def cpu_times(self): ...  # .user, .system in seconds
    def memory_info(self): ...  # .rss in bytes
    def memory_percent(self) -> float: ...
    def num_threads(self) -> int: ...
    def threads(self): ...  # [(id, user_time, system_time)]


@dataclass(frozen=True)
class ResourceSample:
    at: float  # monotonic seconds
    cpu_pct: float  # % of one core since the previous sample
    feed_cpu_pct: float  # the live feed threads' part of it
    rss_bytes: int
    mem_pct: float  # % of the machine's memory
    threads: int


@dataclass(frozen=True)
class ResourceSnapshot:
    current: ResourceSample | None
    cpu_1min: float | None
    cpu_5min: float | None
    feed_cpu_1min: float | None
    history: list[float]  # CPU % of the last 5 minutes, oldest first

    @property
    def cpu_level(self) -> Level:
        return cpu_level(self.cpu_1min)

    @property
    def memory_level(self) -> Level:
        return memory_level(self.current.rss_bytes if self.current else None)

    @property
    def level(self) -> Level:
        return worst(self.cpu_level, self.memory_level)


def cpu_level(pct: float | None) -> Level:
    if pct is None or pct < CPU_WARN:
        return "ok"
    return "warn" if pct < CPU_HIGH else "high"


def memory_level(rss_bytes: int | None) -> Level:
    if rss_bytes is None or rss_bytes < MEMORY_WARN:
        return "ok"
    return "warn" if rss_bytes < MEMORY_HIGH else "high"


def worst(*levels: Level) -> Level:
    return max(levels, key=_ORDER.__getitem__)


def advice(level: Level, live_source: str, stream_seconds: int, online: bool) -> str | None:
    """What to do about a warn or high level, in Polish; None while everything is fine."""
    if level == "ok":
        return None
    if online and live_source == "stream" and stream_seconds < 30:
        return ("Przełącz źródło cen na odpytywanie albo wydłuż odświeżanie strony do 30 s lub dłużej. "
                "Najwięcej kosztuje otwarta strona Portfel, przerysowywana co kilka sekund.")
    if online and live_source == "stream":
        return "Przełącz źródło cen na odpytywanie: strumień trzyma stałe połączenie i przerysowuje stronę Portfel."
    return ("Zamknij zbędne karty przeglądarki z aplikacją: każda otwarta karta liczy swoje strony osobno. "
            "Jeśli to nie pomoże, uruchom aplikację ponownie.")


def _feed_thread_ids() -> set[int]:
    return {t.native_id for t in threading.enumerate() if t.name in FEED_THREADS and t.native_id is not None}


class ResourceMonitor:
    def __init__(
        self,
        process: Process | None = None,
        *,
        cpu_count: int | None = None,
        clock: Callable[[], float] = time.monotonic,
        feed_thread_ids: Callable[[], Iterable[int]] = _feed_thread_ids,
    ) -> None:
        self.process = process if process is not None else psutil.Process()
        self.cpu_count = max(1, cpu_count or psutil.cpu_count() or 1)
        self.clock = clock
        self.feed_thread_ids = feed_thread_ids
        self._samples: deque[ResourceSample] = deque(maxlen=int(HISTORY_SECONDS / SAMPLE_SECONDS))
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last: tuple[float, float, dict[int, float]] | None = None  # (at, process CPU time, per-thread time)

    def _thread_times(self) -> dict[int, float]:
        try:
            return {t[0]: t[1] + t[2] for t in self.process.threads()}
        except (psutil.Error, OSError):
            return {}

    def sample(self) -> ResourceSample | None:
        """Take one sample; the first call only sets the baseline and returns None."""
        at = self.clock()
        times = self.process.cpu_times()
        cpu_time = times.user + times.system
        threads = self._thread_times()
        last, self._last = self._last, (at, cpu_time, threads)
        if last is None or at <= last[0]:
            return None
        wall = at - last[0]
        scale = 100.0 / wall
        feed_ids = set(self.feed_thread_ids())
        feed_time = sum(max(0.0, threads[i] - last[2].get(i, 0.0)) for i in feed_ids if i in threads)
        sample = ResourceSample(
            at=at,
            cpu_pct=max(0.0, cpu_time - last[1]) * scale,
            feed_cpu_pct=feed_time * scale,
            rss_bytes=int(self.process.memory_info().rss),
            mem_pct=float(self.process.memory_percent()),
            threads=int(self.process.num_threads()),
        )
        with self._lock:
            self._samples.append(sample)
        return sample

    def snapshot(self) -> ResourceSnapshot:
        with self._lock:
            samples = list(self._samples)
        if not samples:
            return ResourceSnapshot(None, None, None, None, [])
        now = samples[-1].at

        def recent(seconds: float) -> list[ResourceSample]:
            return [s for s in samples if now - s.at < seconds]

        def mean(values: list[float]) -> float:
            return sum(values) / len(values)

        last_1, last_5 = recent(60), recent(300)
        return ResourceSnapshot(
            current=samples[-1],
            cpu_1min=mean([s.cpu_pct for s in last_1]),
            cpu_5min=mean([s.cpu_pct for s in last_5]),
            feed_cpu_1min=mean([s.feed_cpu_pct for s in last_1]),
            history=[s.cpu_pct for s in last_5],
        )

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="resource-monitor", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            with contextlib.suppress(psutil.Error, OSError):  # a failed reading must never take the app down
                self.sample()
            self._stop.wait(SAMPLE_SECONDS)


_MONITOR: ResourceMonitor | None = None
_MONITOR_LOCK = threading.Lock()


def get_monitor() -> ResourceMonitor:
    """The one monitor of this process, running."""
    global _MONITOR
    with _MONITOR_LOCK:
        if _MONITOR is None:
            _MONITOR = ResourceMonitor()
        _MONITOR.start()
        return _MONITOR
