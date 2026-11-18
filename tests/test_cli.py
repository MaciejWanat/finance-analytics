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
    # D-069, D-077: each source has its own range: polling 2-60 min, the stream's redraw 1-60 s.
    stream = runner.invoke(cli.main, ["settings", "--live", "stream", "--refresh", "1s"])
    assert stream.exit_code == 0 and "Portfel redraws every 1 s" in stream.output
    assert runner.invoke(cli.main, ["settings", "--refresh", "0s"]).exit_code != 0
    assert runner.invoke(cli.main, ["settings", "--refresh", "2m"]).exit_code != 0  # too slow for the stream
    poll = runner.invoke(cli.main, ["settings", "--live", "poll", "--refresh", "2m"])
    assert poll.exit_code == 0 and "polling every 2 min" in poll.output
    assert runner.invoke(cli.main, ["settings", "--refresh", "30s"]).exit_code != 0  # Yahoo would refuse
    assert runner.invoke(cli.main, ["settings", "--refresh", "soon"]).exit_code != 0


def test_update_market_is_a_manual_request_allowed_offline(tmp_path, monkeypatch):
    """Offline means "never on its own"; an explicit `fa update-market` still fetches (D-031)."""
    from finance_analytics.market import update

    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "data"))
    calls = []

    def fake_update(settings, *, manual=False, **kwargs):
        calls.append(manual)
        from finance_analytics.market.gus import CpiReport

        return update.MarketReport(prices=update.PriceReport(), fx=update.FxReport(), cpi=CpiReport())

    monkeypatch.setattr(update, "update_market", fake_update)
    result = CliRunner().invoke(cli.main, ["update-market"])
    assert result.exit_code == 0, result.output
    assert calls == [True] and "fetching once because you asked" in result.output


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


def test_ui_refills_projection_tables_after_a_migration(tmp_path, monkeypatch):
    # Regression (D-029): migration 0007 empties bond_series; `fa ui` on an upgraded database must sync.
    from finance_analytics.mock.bonds import write_mock_bonds
    from finance_analytics.sources.bonds import bonds_file

    data_dir = tmp_path / "data"
    monkeypatch.setenv(DATA_DIR_ENV, str(data_dir))
    settings = Settings(data_dir=data_dir)
    write_mock_bonds(bonds_file(settings.manual_dir))
    with closing(connect(settings.db_path)) as conn:
        conn.execute("PRAGMA user_version = 6")  # an old database: 0007 and 0008 still to apply
        from finance_analytics.db.migrate import available_migrations
        for _, _, sql in available_migrations()[:6]:
            conn.executescript(sql)
    monkeypatch.setattr(cli.subprocess, "call", lambda *a, **k: 0)

    result = CliRunner().invoke(cli.main, ["ui", "--no-open"])

    assert result.exit_code == 0, result.output
    with closing(connect(settings.db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM bond_series").fetchone()[0] > 0
        assert conn.execute("SELECT COUNT(*) FROM bond_lots").fetchone()[0] > 0
