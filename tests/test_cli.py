from contextlib import closing

from click.testing import CliRunner

from finance_analytics import cli
from finance_analytics.config import DATA_DIR_ENV, Settings
from finance_analytics.db import connect


def test_init_creates_data_dir_db_and_accounts_template(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv(DATA_DIR_ENV, str(data_dir))
    monkeypatch.setattr(cli, "_install_git_hooks", lambda: None)  # don't touch the repo's git config

    result = CliRunner().invoke(cli.main, ["init"])

    assert result.exit_code == 0, result.output
    for sub in ("raw", "manual", "config", "samples"):
        assert (data_dir / sub).is_dir()
    assert "accounts: []" in (data_dir / "config" / "accounts.yaml").read_text(encoding="utf-8")
    with closing(connect(data_dir / "finance.db")) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] >= 1

    # Running again keeps existing files and applies nothing new.
    again = CliRunner().invoke(cli.main, ["init"])
    assert again.exit_code == 0
    assert "0 migration(s) applied" in again.output


def test_settings_command_switches_mode(tmp_path, monkeypatch):
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "data"))
    runner = CliRunner()
    shown = runner.invoke(cli.main, ["settings"])
    assert "Network mode: offline" in shown.output
    changed = runner.invoke(cli.main, ["settings", "--online", "--refresh", "10"])
    assert "Network mode: online" in changed.output and "every 10 min" in changed.output
    back = runner.invoke(cli.main, ["settings", "--offline"])
    assert "Network mode: offline" in back.output


def test_update_market_refuses_offline(tmp_path, monkeypatch):
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "data"))
    result = CliRunner().invoke(cli.main, ["update-market"])
    assert result.exit_code != 0 and "offline mode" in result.output


def test_import_inbox_command(tmp_path, monkeypatch):
    from finance_analytics.mock.xtb_export import write_mock_export
    from finance_analytics.preferences import Preferences, save_preferences

    data_dir = tmp_path / "data"
    monkeypatch.setenv(DATA_DIR_ENV, str(data_dir))
    runner = CliRunner()
    assert "No inbox folder configured" in runner.invoke(cli.main, ["import", "inbox"]).output

    inbox = tmp_path / "XTB"
    write_mock_export(inbox)
    save_preferences(Settings(data_dir=data_dir), Preferences(inbox_dir=str(inbox)))
    first = runner.invoke(cli.main, ["import", "inbox"])
    assert first.exit_code == 0, first.output
    assert "copied 5 new file(s)" in first.output
    again = runner.invoke(cli.main, ["import", "inbox"])
    assert "copied 0 new file(s)" in again.output


def test_import_inbox_reports_missing_folder(tmp_path, monkeypatch):
    from finance_analytics.preferences import Preferences, save_preferences

    data_dir = tmp_path / "data"
    monkeypatch.setenv(DATA_DIR_ENV, str(data_dir))
    save_preferences(Settings(data_dir=data_dir), Preferences(inbox_dir=str(tmp_path / "missing")))
    result = CliRunner().invoke(cli.main, ["import", "inbox"])
    assert result.exit_code != 0 and "nie istnieje" in result.output
