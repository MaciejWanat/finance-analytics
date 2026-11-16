# UI guidelines

The design system of the Streamlit UI. It covers how pages are laid out, which building
blocks to use, how charts and numbers look, and what to check before a UI change is
done. Decisions behind it: D-005 (Polish UI), D-011 (privacy), D-012 (UI layer).

The UI is a data tool for one person's money. **Clarity and trust beat novelty:**
- every number must be readable, labelled and consistent across the app;
- no decoration that competes with the data;
- nothing loaded from the internet.

---

## 1. Principles

1. **Data is the loudest thing on the page.** Chrome (borders, gridlines, labels) stays quiet; colour is spent on data.
2. **One headline per view.** A page leads with its KPI row and one main chart; details come after.
3. **A control sits right above what it changes.**
   - A filter that scopes the whole page goes at the top (e.g. *Okres*).
   - A filter for one block goes directly above that block (e.g. *Podział*).
   - Never put a control where its effect is off-screen.
4. **Same thing, same look.** One builder per chart form, one table helper, one formatter per kind of value. Pages never style things by hand.
5. **Honest numbers.** No percentage that misleads (a +9 000% from a tiny base becomes an amount). Simplified metrics say so in their `help`. Missing data is shown as "–" and explained, never as 0.
6. **Private by construction.**
   - No external fonts, CDNs, images or analytics.
   - Error displays carry no external links.
   - Account numbers are shown masked (`…123`).

## 2. Page anatomy

Every page in `app/views/` follows this order (skip what does not apply):

| # | Block | How |
|---|---|---|
| 1 | Title + one-line purpose | `page_header(title, caption)` |
| 2 | Guard states (no DB, no data, missing prerequisite) | `empty_state(...)` + `st.page_link` to the page that fixes it, then `st.stop()` |
| 3 | Page-wide filter | `st.segmented_control`, one row, label in Polish |
| 4 | KPI row (≤ 4 tiles) | `kpi_row([Kpi(...)])`; every tile has a `trend` so heights match |
| 5 | Main chart | `section(...)` + one builder from `ui/charts.py` |
| 6 | Block filter + detail charts | control directly above `st.columns([3, 2])` |
| 7 | Table | `table(...)`, sorted by the most important column |
| 8 | Notes / warnings | `st.expander(":material/warning: …")` at the bottom |

Use `layout="wide"` (set once in `main.py`). Sections are separated by `section()` headings, not by dividers.

## 3. Building blocks (`app/ui/`)

| Need | Use | Never |
|---|---|---|
| Money, numbers, %, dates | `ui/fmt.py`: `fmt_money`, `fmt_money_compact`, `fmt_number`, `fmt_pct`, `fmt_date` | f-strings with `:,.2f`, English separators |
| KPI tiles | `kpi_row`, `Kpi(label, value, delta, help, trend)` | bare `st.metric` |
| Tables | `table(df, numbers=, percents=, signed=, datetimes=, trends=, labels=)` | bare `st.dataframe`; `column_config` number formats |
| Charts | `area_total`, `line_chart`, `stacked_bars`, `segmented_bar`, then `show(fig, key=)` | `px.*` defaults, `st.plotly_chart` directly, `theme="streamlit"` |
| Colours | `ui/theme.py`: `TOKENS[mode]`, `color_map(keys, mode)` | hex codes in pages |
| Empty / guard states | `empty_state(title, body, icon=, steps=)` | `st.info` walls of text |
| Explaining terms | `help=G[...]` from `ui/glossary.py` on KPIs, `section(..., help=)`, filters, and `table(..., helps=)` for column headers | ad-hoc tooltip texts written in a page |
| Long actions | button with a spinner state (see §6) | plain `st.spinner` under a button |

If a page needs something these do not cover, **add it to `app/ui/` first** (with a test in `tests/test_ui_layer.py`) and then use it. Do not inline it in the page.

## 4. Charts

Load the `dataviz` skill before designing a new chart form.

- **Pick the form by the job:**

  | Job | Form |
  |---|---|
  | one series over time | `area_total` |
  | several series to compare | `line_chart` |
  | composition over time | `stacked_bars` (weekly ≤ 100 days, monthly otherwise) |
  | part-to-whole today | `segmented_bar` + a small table (no donuts) |
- **Colour follows the entity, never its rank.**
  - Assign slots with `color_map` over a stable (alphabetical) key order.
  - More than 8 parts: keep the 7 largest and fold the rest into `OTHER_LABEL` ("Inne").
- **Legend for 2+ series; none for one** (the section title names it). **Never two y-axes.**
- **Axes and labels:** Polish separators (the template sets `separators=", "`); numeric dates (`07.2026`); hover values in `zł` or the instrument currency; hover dates `dd.mm.yyyy`.
- **Text never wears a series colour.** Labels and values use ink tokens; the coloured mark next to them carries identity.
- **Light and dark:** pass `current_mode()` to every builder; the palette is validated for both.

## 5. Numbers and text (Polish)

- Amounts `12 345,67 zł`; compact in tiles `463,5 tys. zł`, `1,24 mln zł`; other currencies keep their ISO code (`99,00 USD`).
- Percentages from fractions: `+3,4%`. A sign only where direction matters (results, changes), not for shares.
- Gains are green and losses red, via `signed=` in `table` and `delta` in `Kpi`. Colour is never the only signal: the sign or arrow is always there too.
- Dates `16.11.2026`; timestamps in tables `2026-11-16 14:30` (sortable); say when a time is UTC.
- Copy:
  - write in sentence case and as short statements;
  - address the user as "Ty" only when giving an instruction ("Zaimportuj folder…");
  - keep the precise definition of a metric in its `help` tooltip, not on the page;
  - **every term that may not be obvious gets a "?" tooltip.** This covers TWR, XIRR, drawdown, NBP rate, cost, IKE/IKZE, ticker, split, the "other" part of returns, and similar terms.
  - The text comes from `ui/glossary.py`, so a word is always explained the same way.
  - Add new terms there first; a test checks that every `G["…"]` used by a page exists.
  - Explain in plain Polish, one or two sentences, and say what the number means for the user, not just how it is computed.
- Material icons (`:material/name:`) for headings of cards, empty states and buttons. Emoji are not used.

## 6. States

| State | Pattern |
|---|---|
| No database / no data / missing prices | `empty_state` with the reason, numbered steps and a `page_link` to the fixing page |
| Loading on page open | `st.cache_data(show_spinner="…")` on the computation, keyed by `data_version` |
| Long user action | two-run button: the click sets a flag; the next run redraws the button disabled with `icon="spinner"`, does the work, clears the flag in `finally`, then `st.rerun()`; the result shows below as `st.success`/`st.warning` |
| Recoverable problem | `st.warning` with what to do; detailed lists in an expander |
| Error that blocks a feature | `st.error` naming the file or item and the fix |
| Offline mode (D-021) | features that need the network are disabled, with an `st.info` explaining why and a `page_link` to *Ustawienia*; everything else keeps working on cached data |

## 7. Performance

- Pages read through `finance_analytics.reports` or `portfolio.*`, never with ad-hoc SQL beyond trivial guard checks.
- Heavy computations go through `st.cache_data`, keyed by the data fingerprint, never by time.
- Any table that can exceed a few hundred rows gets a filter (e.g. by type) above it.

## 8. Checklist before a UI change is done

- [ ] Built only from `app/ui/` blocks; no hex codes, no bare `st.dataframe`/`st.plotly_chart`/`st.metric`.
- [ ] Page anatomy order kept; every control is right above what it changes.
- [ ] Checked in the browser on demo data (`fa demo`), in **light and dark** mode, at about 1280 px and at a narrow width.
- [ ] Numbers formatted in Polish; no `None`/`NaN` visible; tiles in a row are the same height.
- [ ] Every non-obvious term (KPI, section, filter, column) has a tooltip from `ui/glossary.py`.
- [ ] New strings are Polish; new code and comments English.
- [ ] Empty and loading states work (try a fresh `FA_DATA_DIR`).
- [ ] `pytest` and `ruff check .` pass.
