"""D-065: the app is an installable package; the UI ships inside it and data goes to a per-user folder."""

from __future__ import annotations

import ast
import fnmatch
import tomllib
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner
from conftest import APP, ROOT

from finance_analytics import cli, config
from finance_analytics.config import DATA_DIR_ENV

PACKAGE = ROOT / "src" / "finance_analytics"


def test_every_ui_file_is_listed_as_package_data():
    """A file the patterns miss would be absent from the wheel, and the installed app would break."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = pyproject["tool"]["setuptools"]["package-data"]["finance_analytics"]
    # static/ holds plotly.js copied at runtime from the plotly package (D-072); it is not shipped.
    files = [p for p in APP.rglob("*") if p.is_file() and "__pycache__" not in p.parts and "static" not in p.parts]
    assert APP / "main.py" in files and APP / ".streamlit" / "config.toml" in files
    missed = [
        p.relative_to(PACKAGE).as_posix() for p in files
        if not any(fnmatch.fnmatch(p.relative_to(PACKAGE).as_posix(), pattern) for pattern in patterns)
    ]
    assert not missed, f"add these to [tool.setuptools.package-data] in pyproject.toml: {missed}"


def test_streamlit_is_imported_only_by_the_ui():
    """Business logic stays free of Streamlit (D-012), even though the UI now lives in the package."""
    offenders = []
    for path in PACKAGE.rglob("*.py"):
        if APP in path.parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            if any(name.split(".")[0] == "streamlit" for name in names):
                offenders.append(path.relative_to(ROOT).as_posix())
    assert not offenders, offenders


def test_the_app_folder_constant_points_at_the_ui():
    assert config.APP_DIR == APP
    assert (config.APP_DIR / ".streamlit" / "config.toml").is_file()


def test_a_checkout_keeps_data_in_the_repository(monkeypatch):
    monkeypatch.delenv(DATA_DIR_ENV, raising=False)
    assert config.is_source_checkout()
    assert config.get_settings().data_dir == ROOT / "data"
    assert config.demo_data_dir() == ROOT / "data-demo"


def test_fa_data_dir_wins(monkeypatch, tmp_path):
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "elsewhere"))
    assert config.get_settings().data_dir == tmp_path / "elsewhere"


def test_an_installed_app_uses_a_per_user_folder(monkeypatch, tmp_path):
    monkeypatch.delenv(DATA_DIR_ENV, raising=False)
    monkeypatch.setattr(config, "is_source_checkout", lambda: False)

    monkeypatch.setattr(config, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert config.get_settings().data_dir == tmp_path / "Local" / "finance-analytics" / "data"
    assert config.demo_data_dir() == tmp_path / "Local" / "finance-analytics" / "demo"

    monkeypatch.setattr(config.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.setattr(config, "sys", SimpleNamespace(platform="darwin"))
    mac = tmp_path / "home" / "Library" / "Application Support"
    assert config.default_data_dir() == mac / "finance-analytics" / "data"

    monkeypatch.setattr(config, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert config.default_data_dir() == tmp_path / "xdg" / "finance-analytics" / "data"
    monkeypatch.setenv("XDG_DATA_HOME", "relative/path")  # not absolute: ignored, as the spec says
    assert config.default_data_dir() == tmp_path / "home" / ".local" / "share" / "finance-analytics" / "data"


def test_ui_runs_streamlit_from_the_app_folder(monkeypatch, tmp_path):
    """The working directory is the app folder, so its .streamlit/config.toml (theme, privacy) applies."""
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "data"))
    calls = []
    monkeypatch.setattr(cli.subprocess, "call", lambda cmd, cwd, env: calls.append((cmd, cwd, env)) or 0)

    result = CliRunner().invoke(cli.main, ["ui", "--no-open", "--port", "8599"])

    assert result.exit_code == 0, result.output
    (cmd, cwd, env), = calls
    assert Path(cwd) == APP and str(APP / "main.py") in cmd
    assert cmd[cmd.index("--server.address") + 1] == "localhost"
    assert env[DATA_DIR_ENV] == str(tmp_path / "data")
    assert str(tmp_path / "data") in result.output


def test_init_of_an_installed_app_leaves_git_alone(monkeypatch):
    monkeypatch.setattr(cli, "is_source_checkout", lambda: False)
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("git called")))
    cli._install_git_hooks()
