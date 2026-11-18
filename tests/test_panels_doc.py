"""docs/panels.md has a complete section for every page (D-071): it is updated together with the pages."""

from __future__ import annotations

import re

from conftest import ROOT

from finance_analytics.config import APP_DIR

DOC = ROOT / "docs" / "panels.md"
FIELDS = ["Refresh", "Inputs", "Computed once per data version", "Computed on every redraw", "Sent to the browser"]
DEVELOPER_PAGES = {"style_preview"}  # synthetic data only, shown with `fa ui --dev`


def sections() -> dict[str, str]:
    """Page file (e.g. 'views/portfolio.py' or 'main.py') -> the text of its section."""
    parts = re.split(r"^## ", DOC.read_text(encoding="utf-8"), flags=re.MULTILINE)[1:]
    found = {}
    for part in parts:
        heading, _, body = part.partition("\n")
        match = re.search(r"`((?:views/)?\w+\.py)`", heading)
        if match:
            found[match.group(1)] = body
    return found


def test_every_page_and_the_sidebar_have_a_complete_section():
    documented = sections()
    pages = {f"views/{path.name}" for path in (APP_DIR / "views").glob("*.py") if path.stem not in DEVELOPER_PAGES}
    missing = sorted((pages | {"main.py"}) - set(documented))
    assert not missing, f"docs/panels.md has no section for: {missing}"
    for page, body in documented.items():
        absent = [field for field in FIELDS if f"**{field}:**" not in body]
        assert not absent, f"docs/panels.md, {page}: missing {absent}"


def test_no_section_for_a_page_that_is_gone():
    pages = {f"views/{path.name}" for path in (APP_DIR / "views").glob("*.py")} | {"main.py"}
    assert set(sections()) <= pages
