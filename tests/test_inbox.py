"""XTB inbox folder (D-028): new exports are imported by themselves, offline, source never changed."""

from __future__ import annotations

import shutil
import socket

import pytest

from finance_analytics.config import Settings
from finance_analytics.mock.xtb_export import write_mock_export
from finance_analytics.preferences import Preferences, load_preferences, save_preferences
from finance_analytics.sources.inbox import check_inbox


@pytest.fixture(scope="module")
def export(tmp_path_factory):
    root = tmp_path_factory.mktemp("inbox_export")
    write_mock_export(root)
    return root


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def inbox(tmp_path, export):
    folder = tmp_path / "XTB"
    shutil.copytree(export, folder)
    return folder


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _configure(settings, folder):
    save_preferences(settings, Preferences(inbox_dir=str(folder)))


def test_none_when_no_inbox_configured(settings):
    assert check_inbox(settings) is None


def test_missing_folder_gives_error_not_crash(settings, tmp_path):
    _configure(settings, tmp_path / "does-not-exist")
    result = check_inbox(settings)
    assert result is not None
    assert result.error and "nie istnieje" in result.error
    assert result.copied == [] and result.sync is None


def test_imports_new_exports_once(settings, inbox, no_network):
    before = sorted(p.relative_to(inbox) for p in inbox.rglob("*"))
    _configure(settings, inbox)

    first = check_inbox(settings)
    assert first.error is None
    assert len(first.copied) == 5
    assert first.sync is not None and first.sync.rebuilt and not first.sync.errors

    second = check_inbox(settings)
    assert second.copied == []
    assert second.already_imported == 5
    assert second.sync is None  # nothing new, so no rebuild

    # The source folder is only read.
    assert sorted(p.relative_to(inbox) for p in inbox.rglob("*")) == before


def test_preferences_roundtrip_with_inbox_dir(settings, tmp_path):
    save_preferences(settings, Preferences(network="online", inbox_dir=str(tmp_path)))
    loaded = load_preferences(settings)
    assert loaded.inbox_dir == str(tmp_path) and loaded.online

    # settings.yaml written before the inbox existed still loads, with the feature off.
    settings.preferences_file.write_text("network: offline\nrefresh_minutes: 5\n", encoding="utf-8")
    assert load_preferences(settings).inbox_dir is None
