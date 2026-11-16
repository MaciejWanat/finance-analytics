"""Command line entry point: ``fa``."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import webbrowser
from contextlib import closing
from pathlib import Path

import click

from finance_analytics import __version__
from finance_analytics.config import DATA_DIR_ENV, get_settings
from finance_analytics.db import connect, migrate

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_MAIN = REPO_ROOT / "app" / "main.py"

ACCOUNTS_TEMPLATE = """\
# Accounts known to finance-analytics. This file is private: data/ is git-ignored.
# XTB accounts are added here automatically on the first import of an export folder.
# Change `alias` (the name the UI shows) whenever you like.
#
# Example entry (fake values):
#   - id: xtb-usd
#     institution: xtb
#     kind: broker            # broker | bank | bonds
#     currency: USD
#     alias: XTB USD
#     external_no: "00000000" # broker account number, stays local
#     tax_wrapper: null       # null | IKE | IKZE
accounts: []
"""


@click.group()
@click.version_option(__version__, prog_name="fa")
def main() -> None:
    """finance-analytics: local, private analytics for your savings."""


@main.command()
def init() -> None:
    """Create the local data directory, the database and the privacy git hook."""
    settings = get_settings()
    for directory in settings.all_dirs():
        directory.mkdir(parents=True, exist_ok=True)
    click.echo(f"Data directory: {settings.data_dir}")

    if not settings.accounts_file.exists():
        settings.accounts_file.write_text(ACCOUNTS_TEMPLATE, encoding="utf-8")
        click.echo(f"Created {settings.accounts_file}")

    with closing(connect(settings.db_path)) as conn:
        applied = migrate(conn)
    click.echo(f"Database: {settings.db_path} ({len(applied)} migration(s) applied)")

    _install_git_hooks()


@main.command()
@click.option("--port", default=8501, show_default=True, help="Port on localhost.")
@click.option("--dev", is_flag=True, help="Show developer pages (style preview on synthetic data).")
@click.option("--open/--no-open", "open_browser", default=True, show_default=True, help="Open a browser tab.")
def ui(port: int, dev: bool, open_browser: bool) -> None:
    """Start the web UI on localhost."""
    if not APP_MAIN.exists():
        raise click.ClickException(f"UI entry point not found: {APP_MAIN}")
    settings = get_settings()
    env = {**os.environ, DATA_DIR_ENV: str(settings.data_dir)}
    if dev:
        env["FA_DEV"] = "1"
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(APP_MAIN),
        "--server.port", str(port),
        # Also set in .streamlit/config.toml; repeated here so they hold even if
        # Streamlit is started from another working directory (D-011).
        "--server.address", "localhost",
        "--browser.gatherUsageStats", "false",
        # Headless skips Streamlit's first-run e-mail prompt; we open the tab ourselves.
        "--server.headless", "true",
    ]
    url = f"http://localhost:{port}"
    click.echo(f"Starting the UI at {url} (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(2.0, webbrowser.open, args=[url]).start()
    raise SystemExit(subprocess.call(cmd, cwd=REPO_ROOT, env=env))


@main.command("mock-xtb")
@click.argument("out_dir", type=click.Path(path_type=Path), default=Path("data-demo") / "xtb_export")
@click.option("--force", is_flag=True, help="Write even if the folder is not empty.")
def mock_xtb(out_dir: Path, force: bool) -> None:
    """Write a synthetic xStation export folder (real layout, fake values)."""
    from finance_analytics.mock.xtb_export import write_mock_export

    if out_dir.exists() and any(out_dir.iterdir()) and not force:
        raise click.ClickException(f"{out_dir} is not empty (use --force to overwrite)")
    for path in write_mock_export(out_dir):
        click.echo(f"  {path}")
    click.echo(f"Mock XTB export written to {out_dir} (synthetic data, git-ignored).")


def _install_git_hooks() -> None:
    """Point git at .githooks so the privacy pre-commit check runs (D-014)."""
    if not (REPO_ROOT / ".git").exists() or not (REPO_ROOT / ".githooks").is_dir():
        click.echo("Not a git checkout; skipping the privacy pre-commit hook.")
        return
    git = ["git", "-C", str(REPO_ROOT), "config"]
    current = subprocess.run([*git, "--get", "core.hooksPath"], capture_output=True, text=True).stdout.strip()
    if current == ".githooks":
        click.echo("Privacy pre-commit hook: already enabled.")
        return
    subprocess.run([*git, "core.hooksPath", ".githooks"], check=True)
    click.echo("Privacy pre-commit hook: enabled (git config core.hooksPath .githooks).")


if __name__ == "__main__":
    main()
