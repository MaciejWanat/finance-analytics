"""Command line entry point: ``fa``."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import webbrowser
from contextlib import closing
from pathlib import Path

import click

from finance_analytics import __version__
from finance_analytics.config import (
    APP_DIR,
    DATA_DIR_ENV,
    SOURCE_ROOT,
    Settings,
    demo_data_dir,
    get_settings,
    is_source_checkout,
)
from finance_analytics.db import connect, migrate
from finance_analytics.sources import accounts as accounts_file

APP_MAIN = APP_DIR / "main.py"

@click.group()
@click.version_option(__version__, prog_name="fa")
def main() -> None:
    """finance-analytics: local, private analytics for your savings."""


def _prepare(settings: Settings) -> list[str]:
    """Data directories, accounts file and database schema. Returns applied migrations."""
    for directory in settings.all_dirs():
        directory.mkdir(parents=True, exist_ok=True)
    if not settings.accounts_file.exists():
        settings.accounts_file.write_text(accounts_file.HEADER + "\naccounts: []\n", encoding="utf-8")
        click.echo(f"Created {settings.accounts_file}")
    with closing(connect(settings.db_path)) as conn:
        return migrate(conn)


@main.command()
def init() -> None:
    """Create the local data directory, the database and the privacy git hook."""
    settings = get_settings()
    click.echo(f"Data directory: {settings.data_dir}")
    applied = _prepare(settings)
    click.echo(f"Database: {settings.db_path} ({len(applied)} migration(s) applied)")
    _install_git_hooks()


def _report_sync(result) -> None:
    if not result.rebuilt:
        click.echo(f"Sync: nothing changed ({result.files} file(s)).")
        return
    click.echo(f"Sync: rebuilt from {result.files} file(s).")
    for alias in result.accounts_added:
        click.echo(f"  new account: {alias} (rename it in config/accounts.yaml in the data directory)")
    for message in result.errors:
        click.secho(f"  ERROR {message}", fg="red")
    for message in result.warnings:
        click.secho(f"  warning: {message}", fg="yellow")


@main.command()
@click.option("--force", is_flag=True, help="Rebuild even if no file changed.")
def sync(force: bool) -> None:
    """Rebuild the database from the files in the data directory when they changed."""
    from finance_analytics.sources.sync import sync as run_sync

    settings = get_settings()
    _prepare(settings)
    _report_sync(run_sync(settings, force=force))


@main.command()
def rebuild() -> None:
    """Rebuild the database from the files in the data directory, unconditionally."""
    from finance_analytics.sources.sync import sync as run_sync

    settings = get_settings()
    _prepare(settings)
    _report_sync(run_sync(settings, force=True))


@main.command()
@click.option("--keep-exports", is_flag=True, help="Keep the archived XTB exports (data/raw).")
@click.option("--keep-manual", is_flag=True, help="Keep bonds.csv and cash_balances.csv.")
@click.option("--keep-accounts", is_flag=True, help="Keep accounts.yaml and bond_series.yaml.")
@click.option("--market", is_flag=True, help="Also clear cached prices, FX rates and CPI.")
@click.option("--backup", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Write a zip backup of the data files here first.")
@click.option("--yes", is_flag=True, help="Do not ask for confirmation.")
def reset(keep_exports: bool, keep_manual: bool, keep_accounts: bool, market: bool, backup: Path | None,
          yes: bool) -> None:
    """Delete source files in the data directory and empty the database (D-038).

    Preferences (settings.yaml) and the inbox folder are never touched.
    """
    from finance_analytics.sources.reset import ResetChoice, backup_zip, files_for, reset_data

    settings = get_settings()
    choice = ResetChoice(exports=not keep_exports, manual=not keep_manual, accounts=not keep_accounts,
                         market=market)
    files = files_for(settings, choice)
    click.echo(f"Data directory: {settings.data_dir}")
    click.echo(f"Files to delete: {len(files)}" + ("; cached market data will be cleared." if market else "."))
    if not files and not market:
        click.echo("Nothing to delete.")
        return
    if not yes:
        click.confirm("This cannot be undone. Continue?", abort=True)
    if backup is not None:
        backup.write_bytes(backup_zip(settings))
        click.echo(f"Backup written to {backup}")
    result = reset_data(settings, choice)
    click.echo(f"Deleted {len(result.removed)} file(s)." + (" Market cache cleared." if result.market_cleared else ""))


def _refresh_seconds(ctx: click.Context, param: click.Parameter, value: str | None) -> int | None:
    """'5s', '30s', '5m' or a bare number of minutes (as before D-069) -> seconds; the range depends on the
    source and is checked in the command."""
    if value is None:
        return None
    text = value.strip().lower()
    try:
        seconds = int(text[:-1]) if text.endswith("s") else int(text.removesuffix("m")) * 60
    except ValueError:
        raise click.BadParameter("use e.g. 5s, 30s, 5m or a number of minutes") from None
    if seconds <= 0:
        raise click.BadParameter("must be positive")
    return seconds


def _interval_text(seconds: int) -> str:
    return f"{seconds // 60} min" if seconds % 60 == 0 else f"{seconds} s"


@main.command("settings")
@click.option("--online/--offline", "online", default=None, help="Switch the network mode (default: offline).")
@click.option("--live", "live_source", type=click.Choice(["poll", "stream"]), default=None,
              help="How live prices arrive online: poll Yahoo every interval, or one streaming connection (D-069).")
@click.option("--refresh", callback=_refresh_seconds, default=None,
              help="Interval of the chosen source: polling 2m-60m, stream redraw 5s-60s (a bare number means "
                   "minutes).")
def settings_command(online: bool | None, live_source: str | None, refresh: int | None) -> None:
    """Show or change preferences: network mode and live prices (D-021, D-069)."""
    from finance_analytics.preferences import POLL_SECONDS, STREAM_SECONDS, load_preferences, save_preferences

    settings = get_settings()
    preferences = load_preferences(settings)
    changes: dict[str, object] = {}
    if online is not None:
        changes["network"] = "online" if online else "offline"
    if live_source is not None:
        changes["live_source"] = live_source
    if refresh is not None:
        stream = (live_source or preferences.live_source) == "stream"
        low, high = STREAM_SECONDS if stream else POLL_SECONDS
        if not low <= refresh <= high:
            raise click.BadParameter(
                f"{'the stream redraws' if stream else 'polling runs'} every {_interval_text(low)} to "
                f"{_interval_text(high)}", param_hint="--refresh")
        changes["stream_seconds" if stream else "poll_seconds"] = refresh
    if changes:
        preferences = preferences.model_copy(update=changes)
        save_preferences(settings, preferences)
    click.echo(f"Network mode: {preferences.network}")
    if preferences.live_source == "stream":
        click.echo(f"Live prices: stream; Portfel redraws every {_interval_text(preferences.stream_seconds)} "
                   "(online mode only)")
    else:
        click.echo(f"Live prices: polling every {_interval_text(preferences.poll_seconds)} (online mode only)")
    if preferences.online:
        click.echo("Online: tickers, currency codes and dates are sent to Yahoo Finance and NBP, and the public CPI "
                   "file is downloaded from GUS; nothing else.")
    else:
        click.echo("Offline: no network calls; the app works on cached data only.")


@main.command("update-market")
def update_market_command() -> None:
    """Download missing prices (Yahoo), FX rates (NBP) and CPI (GUS) into the local cache.

    An explicit request, so it works in offline mode too (D-031): offline only stops the
    app from going online on its own.
    """
    from finance_analytics.market.update import update_market
    from finance_analytics.preferences import load_preferences

    settings = get_settings()
    _prepare(settings)
    if not load_preferences(settings).online:
        click.echo("Offline mode: fetching once because you asked; the app will not fetch on its own.")
    report = update_market(settings, manual=True)
    click.echo(
        f"Prices: {sum(report.prices.fetched.values())} rows for {len(report.prices.fetched)} ticker(s); "
        f"FX: {sum(report.fx.fetched.values())} rows for {len(report.fx.fetched)} currency(ies)."
    )
    if report.cpi.skipped:
        click.echo("CPI (GUS): already fetched today.")
    elif not report.cpi.error:
        click.echo(f"CPI (GUS): {report.cpi.fetched} monthly rows.")
    for symbol in report.unresolved:
        click.secho(f"  no Yahoo ticker for {symbol} (add a mapping rule)", fg="yellow")
    for key, message in report.errors.items():
        click.secho(f"  ERROR {key}: {message}", fg="red")


@main.group("import")
def import_() -> None:
    """Import broker exports into the data directory."""


@import_.command("xtb")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
def import_xtb_command(source: Path) -> None:
    """Import an xStation export: a folder, the .zip xStation saves, or one .xlsx file. The source is only read."""
    from finance_analytics.sources.sync import import_xtb
    from finance_analytics.sources.sync import sync as run_sync

    settings = get_settings()
    _prepare(settings)
    result = import_xtb(source, settings)
    click.echo(f"Copied {len(result.copied)} new file(s), {len(result.unchanged)} already imported.")
    for path, reason in result.skipped:
        click.secho(f"  skipped {path.name}: {reason}", fg="yellow")
    _report_sync(run_sync(settings))


@import_.command("inbox")
def import_inbox_command() -> None:
    """Check the inbox folder set on the Ustawienia page once and import new exports (D-028)."""
    from finance_analytics.preferences import PreferencesError
    from finance_analytics.sources.inbox import check_inbox

    settings = get_settings()
    _prepare(settings)
    try:
        result = check_inbox(settings)
    except PreferencesError as exc:
        raise click.ClickException(f"Invalid settings file: {exc}") from exc
    if result is None:
        click.echo("No inbox folder configured. Set it on the Ustawienia page (inbox_dir in settings.yaml).")
        return
    if result.error:
        raise click.ClickException(result.error)
    click.echo(
        f"Inbox {result.folder}: copied {len(result.copied)} new file(s), "
        f"{result.already_imported} already imported."
    )
    for path, reason in result.skipped:
        click.secho(f"  skipped {path.name}: {reason}", fg="yellow")
    if result.sync is not None:
        _report_sync(result.sync)


@main.command()
@click.option("--port", default=8501, show_default=True, help="Port on localhost.")
@click.option("--dev", is_flag=True, help="Show developer pages (style preview on synthetic data).")
@click.option("--open/--no-open", "open_browser", default=True, show_default=True, help="Open a browser tab.")
def ui(port: int, dev: bool, open_browser: bool) -> None:
    """Start the web UI on localhost."""
    _launch_ui(get_settings(), port, dev, open_browser)


@main.command()
@click.option("--port", default=8501, show_default=True, help="Port on localhost.")
@click.option("--open/--no-open", "open_browser", default=True, show_default=True, help="Open a browser tab.")
@click.option("--no-ui", is_flag=True, help="Only prepare the demo data.")
def demo(port: int, open_browser: bool, no_ui: bool) -> None:
    """Build the demo data directory from a synthetic XTB export, mock bonds and bank balances, then open the UI."""
    from finance_analytics.mock.bonds import write_mock_bonds
    from finance_analytics.mock.cash import write_mock_cash
    from finance_analytics.mock.xtb_export import write_mock_export
    from finance_analytics.sources.bonds import bonds_file
    from finance_analytics.sources.cash import cash_file
    from finance_analytics.sources.sync import import_xtb
    from finance_analytics.sources.sync import sync as run_sync

    settings = Settings(data_dir=demo_data_dir())  # data-demo/ in a checkout, never the real data directory
    # Start from fresh demo files so repeated runs don't stack copies, but keep the
    # database: its market cache (prices, FX) saves re-downloading on every demo run.
    export = settings.data_dir / "xtb_export"
    for folder in (export, settings.raw_dir):
        if folder.exists():
            shutil.rmtree(folder)
    settings.accounts_file.unlink(missing_ok=True)  # settings.yaml (network mode) is kept
    write_mock_export(export)
    _prepare(settings)
    write_mock_bonds(bonds_file(settings.manual_dir))  # synthetic purchases, only ever in the demo directory
    write_mock_cash(settings.accounts_file, cash_file(settings.manual_dir))  # two mock bank accounts
    import_xtb(export, settings)
    _report_sync(run_sync(settings, force=True))
    click.echo(f"Demo data directory: {settings.data_dir} (synthetic data only)")
    if not no_ui:
        _launch_ui(settings, port, dev=True, open_browser=open_browser)


def _launch_ui(settings: Settings, port: int, dev: bool, open_browser: bool) -> None:
    if not APP_MAIN.exists():
        raise click.ClickException(f"UI entry point not found: {APP_MAIN}")
    if _prepare(settings):  # schema up to date before any page reads it
        # A migration may add or reshape projection tables (e.g. 0007 empties bond_series); refill them now,
        # so an upgraded database is never read half-built. A no-op when no source file changed.
        from finance_analytics.sources.sync import sync as run_sync

        _report_sync(run_sync(settings))
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
        # Dev mode: rerun the app automatically when a source file is saved.
        "--server.runOnSave", "true" if dev else "false",
    ]
    url = f"http://localhost:{port}"
    click.echo(f"Data directory: {settings.data_dir}")
    click.echo(f"Starting the UI at {url} (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(2.0, webbrowser.open, args=[url]).start()
    # Streamlit reads .streamlit/config.toml (theme, privacy settings) from its working directory: the app folder.
    raise SystemExit(subprocess.call(cmd, cwd=APP_DIR, env=env))


@main.command("mock-xtb")
@click.argument("out_dir", type=click.Path(path_type=Path), required=False)
@click.option("--force", is_flag=True, help="Write even if the folder is not empty.")
def mock_xtb(out_dir: Path | None, force: bool) -> None:
    """Write a synthetic xStation export folder (real layout, fake values); default: xtb_export in the demo folder."""
    from finance_analytics.mock.xtb_export import write_mock_export

    out_dir = out_dir or demo_data_dir() / "xtb_export"

    if out_dir.exists() and any(out_dir.iterdir()) and not force:
        raise click.ClickException(f"{out_dir} is not empty (use --force to overwrite)")
    for path in write_mock_export(out_dir):
        click.echo(f"  {path}")
    click.echo(f"Mock XTB export written to {out_dir} (synthetic data, git-ignored).")


def _install_git_hooks() -> None:
    """Point git at .githooks so the privacy pre-commit check runs (D-014). Only a source checkout needs it."""
    if not is_source_checkout():
        return
    if not (SOURCE_ROOT / ".git").exists() or not (SOURCE_ROOT / ".githooks").is_dir():
        click.echo("Not a git checkout; skipping the privacy pre-commit hook.")
        return
    git = ["git", "-C", str(SOURCE_ROOT), "config"]
    current = subprocess.run([*git, "--get", "core.hooksPath"], capture_output=True, text=True).stdout.strip()
    if current == ".githooks":
        click.echo("Privacy pre-commit hook: already enabled.")
        return
    subprocess.run([*git, "core.hooksPath", ".githooks"], check=True)
    click.echo("Privacy pre-commit hook: enabled (git config core.hooksPath .githooks).")


if __name__ == "__main__":
    main()
