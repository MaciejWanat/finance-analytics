"""Import button on "Importy": spinner state while the import runs (Streamlit AppTest, offline)."""

from __future__ import annotations

from contextlib import closing

import pytest
from streamlit.testing.v1 import AppTest

from finance_analytics.config import APP_DIR, DATA_DIR_ENV, Settings
from finance_analytics.db import connect, migrate

PAGE = str(APP_DIR / "views" / "imports.py")


@pytest.fixture
def settings(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data")
    monkeypatch.setenv(DATA_DIR_ENV, str(settings.data_dir))
    settings.config_dir.mkdir(parents=True)
    with closing(connect(settings.db_path)) as conn:
        migrate(conn)
    return settings


def _import_button(at):
    return next(b for b in at.button if b.key == "xtb_import")


def test_import_button_is_idle_and_disabled_without_files(settings):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    button = _import_button(at)
    assert button.label == "Importuj" and button.disabled


def test_import_run_draws_a_spinner_button_then_resets(settings):
    # The click only sets this flag; the run it triggers draws the button as a disabled spinner,
    # imports, clears the flag and reruns (so the final state is idle again).
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["xtb_importing"] = True
    at.run()
    assert not at.exception
    assert at.session_state["xtb_importing"] is False
    assert _import_button(at).label == "Importuj"
    assert at.session_state["xtb_upload_round"] == 1
