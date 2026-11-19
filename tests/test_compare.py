"""Instruments, asset classes and references side by side (D-086)."""

from __future__ import annotations

import pandas as pd
import pytest
from test_slicing import mock_valuation  # noqa: F401 (a fixture)

from finance_analytics.portfolio.compare import (
    compare_parts,
    index_line,
    intraday_parts,
    intraday_twr,
    series_line,
)
from finance_analytics.portfolio.returns import returns_for
from finance_analytics.portfolio.slicing import Slice

DAYS = pd.date_range("2026-03-01", periods=7, freq="D")


def bought_sold_rebought():
    """Bought for 100 on day 2, worth 110 on day 3, sold for 110 on day 4, bought again for 50 on day 6, worth 60
    on day 7. By hand: TWR 1.1 × 1.2 − 1 = +32%, result 10 + 10 = 20 zł."""
    values = pd.Series([0.0, 100.0, 110.0, 0.0, 0.0, 50.0, 60.0], index=DAYS)
    flows = pd.Series([100.0, -110.0, 50.0], index=DAYS[[1, 3, 5]])
    return values, flows


def test_twr_continues_across_a_gap_and_the_line_breaks_while_nothing_is_held():
    values, flows = bought_sold_rebought()
    line = series_line(values, flows, DAYS[0], DAYS[-1])
    assert line.total_twr == pytest.approx(0.32)
    assert line.result == pytest.approx(20.0)
    assert line.end_value == pytest.approx(60.0)
    assert line.max_drawdown == pytest.approx(0.0)
    expected = [0.0, 0.0, 0.1, None, 0.1, 0.1, 0.32]  # day 1: the anchor before the purchase; day 4: the break
    for got, want in zip(line.twr.tolist(), expected, strict=True):
        assert pd.isna(got) if want is None else got == pytest.approx(want)


def test_a_period_starting_later_is_measured_from_its_first_close():
    values, flows = bought_sold_rebought()
    line = series_line(values, flows, DAYS[2], DAYS[-1])
    assert line.twr.iloc[0] == pytest.approx(0.0)
    assert line.total_twr == pytest.approx(1.2 - 1)
    assert line.result == pytest.approx(60 - 110 - (-110 + 50))  # 10 zł on the repurchase


def test_a_part_held_outside_the_period_has_no_line():
    values, flows = bought_sold_rebought()
    line = series_line(values.where(values.index < DAYS[4], 0.0), flows[flows.index < DAYS[4]], DAYS[4], DAYS[-1])
    assert not line.held
    assert line.twr.isna().all() and line.result is None


def test_the_whole_portfolio_matches_zwroty_and_every_class_together_too(mock_valuation):  # noqa: F811
    v = mock_valuation
    start, end = v.total.index[len(v.total) // 3], v.total.index[-1]
    everything = Slice(classes=frozenset(v.daily["asset_class"]))
    lines = compare_parts(v, {"all": Slice(), "every class": everything}, start, end)
    zwroty = returns_for(v.total, v.flows.groupby("date")["amount_pln"].sum(), start, end)
    assert lines["all"].total_twr == pytest.approx(zwroty.twr, rel=1e-9)
    assert lines["every class"].total_twr == pytest.approx(zwroty.twr, rel=1e-9)
    assert lines["all"].max_drawdown == pytest.approx(zwroty.drawdown.max_drawdown)


def test_class_results_add_up_to_the_portfolios_result(mock_valuation):  # noqa: F811
    v = mock_valuation
    start, end = v.total.index[10], v.total.index[-1]
    classes = {c: Slice(classes=frozenset({c})) for c in v.daily["asset_class"].unique()}
    lines = compare_parts(v, {"all": Slice(), **classes}, start, end)
    assert sum(lines[c].result for c in classes if lines[c].held) == pytest.approx(lines["all"].result, abs=0.01)


def test_the_index_is_measured_from_the_last_close_on_or_before_the_start():
    index = pd.Series([100.0, None, 110.0, 99.0], index=pd.date_range("2026-03-01", periods=4, freq="D"))
    line = index_line(index, pd.Timestamp("2026-03-02"), pd.Timestamp("2026-03-04"))
    assert line.total_twr == pytest.approx(-0.01)
    assert line.max_drawdown == pytest.approx(99 / 110 - 1)
    assert line.result is None
    assert index_line(index * float("nan"), index.index[0], index.index[-1]) is None


def test_within_a_day_each_part_moves_over_its_base_close():
    ts = pd.date_range("2026-03-02 09:00", periods=3, freq="5min", tz="Europe/Warsaw")
    rows = pd.DataFrame({"ts": list(ts) * 2, "symbol": ["A"] * 3 + ["B"] * 3, "asset_class": ["stock"] * 6,
                         "value_pln": [100.0, 102.0, 101.0, 50.0, 55.0, 60.0]})
    parts = {"all": Slice(), "A": Slice(symbols=frozenset({"A"})), "B": Slice(symbols=frozenset({"B"}))}
    values = intraday_parts(rows, parts)
    assert values["all"].tolist() == [150.0, 157.0, 161.0]
    twr = intraday_twr(values, {"all": 100.0, "A": 100.0, "B": 0.0})  # B bought today: from its first moment
    assert twr["A"].tolist() == pytest.approx([0.0, 0.02, 0.01])
    assert twr["B"].tolist() == pytest.approx([0.0, 0.1, 0.2])
