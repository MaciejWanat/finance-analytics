"""Asset class of XTB instruments: name rule, user overrides, migration 0009 (D-040)."""

from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from finance_analytics.config import Settings
from finance_analytics.db import connect, migrate
from finance_analytics.db.migrate import available_migrations
from finance_analytics.mock.xtb_export import write_mock_export
from finance_analytics.sources.instruments import (
    InstrumentsFileError,
    classify,
    instruments_file,
    is_precious_metal,
    load_overrides,
)
from finance_analytics.sources.sync import import_xtb, sync


@pytest.mark.parametrize(
    ("name", "category", "expected"),
    [
        ("Physical Gold ETC", "ETC", "precious_metals"),
        ("Xetra-Gold", "ETC", "precious_metals"),
        ("Physical Silver", "ETC", "precious_metals"),
        ("Physical Platinum", "ETN", "precious_metals"),
        ("Gold Bullion Securities", "ETC", "precious_metals"),
        ("Złoto fizyczne", "ETC", "precious_metals"),
        ("Gold ETF", "ETF", "precious_metals"),  # a fund holding the metal counts as the metal
        ("Gold Miners UCITS ETF", "ETF", "etf"),  # mining companies stay equities
        ("Junior Gold Mining", "ETF", "etf"),
        ("Physical Bitcoin", "ETC", "other"),
        ("Brent Crude Oil", "ETC", "other"),
        ("Goldman Sachs", "STOCK", "stock"),
        ("Goldman Sachs Equity ETF", "ETF", "etf"),  # 'Gold' must be a whole word
        ("Barrick Gold", "STOCK", "stock"),  # single stocks are never metals by name
        ("S&P 500 UCITS ETF Acc", "ETF", "etf"),
        (None, "ETC", "other"),
    ],
)
def test_classify_by_category_and_name(name, category, expected):
    assert classify("X.DE", name, category) == expected


def test_override_wins_over_the_rules():
    overrides = {"COIN.DE": "precious_metals", "SGLN.UK": "other"}
    assert classify("SGLN.UK", "Physical Gold ETC", "ETC", overrides) == "other"
    assert classify("COIN.DE", "Physical Bitcoin", "ETC", overrides) == "precious_metals"
    assert not is_precious_metal("Physical Gold", "STOCK")


def test_load_overrides(tmp_path):
    path = tmp_path / "instruments.yaml"
    assert load_overrides(path) == {}
    path.write_text("instruments:\n  ABC.DE: {asset_class: precious_metals}\n", encoding="utf-8")
    assert load_overrides(path) == {"ABC.DE": "precious_metals"}
    path.write_text("instruments:\n  ABC.DE: {asset_class: crypto}\n", encoding="utf-8")
    with pytest.raises(InstrumentsFileError):
        load_overrides(path)


@pytest.fixture(scope="module")
def export(tmp_path_factory):
    root = tmp_path_factory.mktemp("export")
    write_mock_export(root)
    return root


def _classes(settings) -> dict[str, str]:
    with closing(sqlite3.connect(settings.db_path)) as conn:
        return dict(conn.execute("SELECT xtb_symbol, asset_class FROM instruments"))


def test_sync_classifies_the_mock_gold_etc_and_applies_overrides(tmp_path, export):
    settings = Settings(data_dir=tmp_path / "data")
    import_xtb(export, settings)
    sync(settings)
    classes = _classes(settings)
    assert classes["SGLN.UK"] == "precious_metals"
    assert classes["VUAA.UK"] == "etf" and classes["NVDA.US"] == "stock"

    path = instruments_file(settings.config_dir)
    path.write_text("instruments:\n  SGLN.UK: {asset_class: other}\n", encoding="utf-8")
    assert sync(settings).rebuilt  # the overrides file is part of the fingerprint
    assert _classes(settings)["SGLN.UK"] == "other"

    path.write_text("instruments: [oops]\n", encoding="utf-8")
    result = sync(settings)
    assert any("instruments.yaml" in e for e in result.errors)
    assert _classes(settings)["SGLN.UK"] == "precious_metals"  # broken file: rules only, import still works


def test_migration_0009_recreates_instruments_and_forces_a_rebuild(tmp_path, export):
    settings = Settings(data_dir=tmp_path / "data")
    import_xtb(export, settings)
    sync(settings)
    # Downgrade the instruments table to its 0008 shape and pretend 0009 never ran.
    with closing(connect(settings.db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0] > 0
        conn.execute("PRAGMA user_version = 8")
        conn.commit()
        assert migrate(conn) == [available_migrations()[8][1]]
        assert conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 0
        conn.execute("INSERT INTO instruments (xtb_symbol, asset_class) VALUES ('T.DE', 'precious_metals')")
        conn.execute("DELETE FROM instruments")
        conn.commit()
    assert sync(settings).rebuilt
    assert _classes(settings)["SGLN.UK"] == "precious_metals"
