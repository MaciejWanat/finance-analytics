"""Resource diagnostics (D-073): CPU and memory of the app process, levels and advice."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from finance_analytics import diagnostics as d


class FakeProcess:
    def __init__(self) -> None:
        self.cpu = 0.0
        self.feed = 0.0
        self.rss = 300 * 2**20

    def cpu_times(self):
        return SimpleNamespace(user=self.cpu * 0.75, system=self.cpu * 0.25)

    def memory_info(self):
        return SimpleNamespace(rss=self.rss)

    def memory_percent(self) -> float:
        return 2.5

    def num_threads(self) -> int:
        return 12

    def threads(self):
        return [(1, self.cpu - self.feed, 0.0), (42, self.feed * 0.5, self.feed * 0.5)]


@pytest.fixture
def monitor():
    clock = SimpleNamespace(t=0.0)
    process = FakeProcess()
    mon = d.ResourceMonitor(process, cpu_count=4, clock=lambda: clock.t, feed_thread_ids=lambda: [42], warmup=0)
    return mon, process, clock


def test_first_sample_is_only_a_baseline(monitor):
    mon, _, _ = monitor
    assert mon.sample() is None
    snap = mon.snapshot()
    assert snap.current is None and snap.cpu_1min is None and snap.level == "ok"


def test_start_up_is_not_measured():
    clock = SimpleNamespace(t=0.0)
    process = FakeProcess()
    mon = d.ResourceMonitor(process, cpu_count=4, clock=lambda: clock.t, feed_thread_ids=lambda: [])
    for step in range(12):  # the first minute: busy start-up, nothing kept
        clock.t = step * 5.0
        process.cpu += 5.0
        assert mon.sample() is None
    assert mon.snapshot().warmup_left == pytest.approx(5.0)
    assert mon.snapshot().level == "ok"
    clock.t = 60.0
    process.cpu += 5.0
    assert mon.sample() is None  # the baseline (taken at 55 s) still lies in the warm-up
    clock.t, process.cpu = 65.0, process.cpu + 0.5
    assert mon.sample().cpu_pct == pytest.approx(10.0)  # only the calm part after the start
    assert mon.snapshot().warmup_left == 0.0

def test_cpu_is_a_share_of_one_core_and_feed_threads_are_counted(monitor):
    mon, process, clock = monitor
    mon.sample()
    clock.t, process.cpu, process.feed = 10.0, 4.0, 1.0  # 4 s of CPU in 10 s
    sample = mon.sample()
    assert sample.cpu_pct == pytest.approx(40.0)
    assert sample.feed_cpu_pct == pytest.approx(10.0)
    assert mon.cpu_count == 4
    assert sample.rss_bytes == 300 * 2**20 and sample.threads == 12 and sample.mem_pct == 2.5


def test_averages_over_one_and_five_minutes(monitor):
    mon, process, clock = monitor
    mon.sample()
    # 4 minutes at 20 %, then one minute at 0 %
    for step in range(1, 61):
        clock.t = step * 5.0
        process.cpu += 0.0 if step > 48 else 5.0 * 0.2
        mon.sample()
    snap = mon.snapshot()
    assert snap.cpu_1min == pytest.approx(0.0)
    assert snap.cpu_5min == pytest.approx(20.0 * 48 / 60)
    assert len(snap.history) == 60


def test_history_is_bounded(monitor):
    mon, process, clock = monitor
    for step in range(400):
        clock.t = step * 5.0
        process.cpu += 1
        mon.sample()
    assert len(mon._samples) == int(d.HISTORY_SECONDS / d.SAMPLE_SECONDS)


@pytest.mark.parametrize(("pct", "level"), [(None, "ok"), (24.9, "ok"), (25.0, "warn"), (49.9, "warn"), (50.0, "high")])
def test_cpu_level(pct, level):
    assert d.cpu_level(pct) == level


@pytest.mark.parametrize(("mb", "level"), [(599, "ok"), (600, "warn"), (1199, "warn"), (1200, "high")])
def test_memory_level(mb, level):
    assert d.memory_level(mb * 2**20) == level


def test_worst():
    assert d.worst("ok", "warn") == "warn"
    assert d.worst("high", "ok", "warn") == "high"


def test_advice():
    assert d.advice("ok", "stream", 5, True) is None
    assert "wydłuż odświeżanie" in d.advice("high", "stream", 5, True)
    assert "odpytywanie" in d.advice("warn", "stream", 60, True)
    assert "karty" in d.advice("high", "poll", 5, True)
    assert "karty" in d.advice("high", "stream", 5, False)


def test_real_process_sample():
    mon = d.ResourceMonitor(warmup=0)
    mon.sample()
    mon._measure_from -= 1.0
    mon._last = (mon._last[0] - 1.0, *mon._last[1:])  # pretend a second has passed
    sample = mon.sample()
    assert sample is not None and sample.rss_bytes > 0 and sample.threads >= 1
