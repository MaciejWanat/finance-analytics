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


def test_every_glossary_key_used_by_pages_exists():
    import re

    from conftest import ROOT
    from ui.glossary import G

    used = set()
    for path in (ROOT / "app").rglob("*.py"):
        used |= set(re.findall(r'G\["([a-z0-9_]+)"\]', path.read_text(encoding="utf-8")))
    assert used, "pages should use the glossary"
    assert used <= set(G), sorted(used - set(G))
