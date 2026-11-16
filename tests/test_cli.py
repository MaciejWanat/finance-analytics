from contextlib import closing

from click.testing import CliRunner

from finance_analytics import cli
from finance_analytics.config import DATA_DIR_ENV
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
