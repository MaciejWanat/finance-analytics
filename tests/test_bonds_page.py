"""Smoke test of the "Obligacje" page on a synthetic data directory (Streamlit AppTest, offline)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from finance_analytics.config import APP_DIR, DATA_DIR_ENV, Settings
from finance_analytics.mock.bonds import write_mock_bonds
from finance_analytics.sources.bonds import bonds_file, read_lots
from finance_analytics.sources.sync import sync

PAGE = str(APP_DIR / "views" / "bonds.py")


@pytest.fixture
def settings(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data")
    monkeypatch.setenv(DATA_DIR_ENV, str(settings.data_dir))
    return settings


def test_empty_state_then_add_a_purchase(settings):
    code = f"EDO{date.today():%m}{(date.today().year + 10) % 100:02d}"  # the series on sale today
    # Declared by the user, so the test does not depend on the shipped file covering today's month.
    settings.config_dir.mkdir(parents=True)
    (settings.config_dir / "bond_series.yaml").write_text(
        f"series:\n  {code}:\n    first_rate: 5.0\n    margin: 2.0\n    early_fee: 3.0\n", encoding="utf-8")
    sync(settings)
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert any("Nie masz jeszcze obligacji" in m.value for m in at.markdown)
    at.text_input[0].input(code)
    at.number_input[0].set_value(3)
    at.button[0].click().run()
    assert not at.exception and not at.error
    (lot,) = read_lots(bonds_file(settings.manual_dir), {code}).lots
    assert (lot.series, lot.purchase_date, lot.quantity) == (code, date.today(), 3)


def test_page_with_demo_bonds(settings):
    write_mock_bonds(bonds_file(settings.manual_dir))
    sync(settings)
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert [m.label for m in at.metric] == ["Wartość brutto", "Odsetki naliczone", "Do wypłaty dziś",
                                            "Średnie oprocentowanie"]
    assert "Twoje obligacje" in [s.value for s in at.subheader]


def test_market_page_offers_the_update_with_bonds_only(settings):
    # Regression (D-029): bonds need the CPI, so "Dane rynkowe" must not ask for a broker export first.
    write_mock_bonds(bonds_file(settings.manual_dir))
    sync(settings)
    at = AppTest.from_file(str(Path(PAGE).parents[1] / "main.py"), default_timeout=60).run()
    at.switch_page("views/market.py").run()  # through navigation: the page links to other pages
    assert not at.exception
    assert any(b.label == "Pobierz brakujące dane" for b in at.button)
