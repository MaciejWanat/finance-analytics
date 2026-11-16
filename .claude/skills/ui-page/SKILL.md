---
name: ui-page
description: Design rules for building or changing Streamlit pages and UI components in this project (app/views, app/ui). Use whenever a task adds or edits a page, a chart, a table, a KPI tile, a filter or any UI text, before writing the code.
---

# UI page

This app is a private finance dashboard. Clarity, consistency and trustworthy numbers
matter more than novelty. Without guidance, UI code drifts toward ad-hoc styling:
- bare `st.dataframe`;
- default Plotly colours;
- English number formats;
- controls far from what they change.

Prevent that.

## Before coding

1. Read `docs/ui-guidelines.md` (page anatomy, building blocks, charts, Polish copy, states, checklist).
2. Look at an existing page with the same shape, e.g. `app/views/portfolio.py` or `app/views/market.py`, and reuse its structure.
3. For a new chart form, load the `dataviz` skill first.

## Rules that are easy to get wrong

- **Use only `app/ui/` blocks:**
  - `page_header`, `section`, `kpi_row`/`Kpi`, `table`, `empty_state`;
  - chart builders with `show()`;
  - `fmt_*` formatters;
  - `TOKENS` and `color_map`.

  If something is missing, add it to `app/ui/` with a test, then use it.
- **Placement:** a filter sits right above what it changes. A page-wide filter goes at the top; a block filter goes above its block.
- **KPI tiles:** at most 4; every tile has a `trend` so heights match; a percentage only when its base is meaningful.
- **Colour:** it follows the entity in a stable order, never rank or position; past 8 parts, fold into "Inne"; never two y-axes; a legend from 2 series.
- **Text:** UI text in Polish, code and comments in English. Numbers like `12 345,67 zł` and `+3,4%`; show "–" for missing values, never `None`/`NaN`/0.
- **Long actions:** use a two-run spinner button (pattern in the guidelines, §6).
- **Privacy:** no external fonts, CDNs, images or links; account numbers masked (`…123`).

## Before saying it is done

1. Run `fa demo` (or reuse a running one; it reruns on save).
2. Check the page in the browser in light and dark mode, wide and narrow.
3. Fix label collisions, empty or `None` cells, and uneven tiles.
4. Run `pytest` and `ruff check .`.
5. Report what you checked and what you could not check.
