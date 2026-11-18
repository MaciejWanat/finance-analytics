# Panels: what each one recomputes and when

One section per page of the UI (`src/finance_analytics/app/views/`) and one for the sidebar. Each section answers:
what makes the panel run again, what it reads, what is computed once per data version, what is computed on every
redraw, and what goes to the browser. **Update a page's section in the same change that alters the page, its
fragments, or what it computes** (CLAUDE.md, `docs/ui-guidelines.md` §7 and §8). `tests/test_panels_doc.py` checks that every page
has a section with all five fields.

## How redrawing works (D-069, D-071)

- The browser keeps one WebSocket to Streamlit. There is no page reload: a *full run* reruns the page script after a
  click, a page change or `st.rerun()`. A *fragment* (`@st.fragment(run_every=…)`) reruns only its own function on
  a timer, and only its elements go to the browser.
- `st.plotly_chart` gives a chart a new element ID whenever its figure changes, and its frontend reads the figure only
  on mount: a live redraw removed the chart and drew it from scratch, empty for a frame or two (a blink). Charts in
  live fragments therefore use `ui.live_chart` (`show(..., live=True)`, `show_spark`, `show_detail`): one chart per
  key, updated in place with `Plotly.react`, plotly.js served locally from the app's `static/` folder (D-072).
  While a fragment runs, its elements are not dimmed (CSS in `ui.components`); a full run still dims and shows
  "Przeliczam…".
- A fragment must draw all of its elements on every run; what it does not draw disappears. So "redraw only when
  something changed" is not possible inside a fragment. Instead, the work behind each redraw is kept small (below),
  and live fragments slow down while markets are quiet (`ui.data.live_every`, D-071):
  - the user's pace (`Preferences.redraw_seconds`: the stream setting, 1–60 s (D-077), or 30 s while polling) while any
    tracked exchange is in session, US pre-market and post-market included;
  - 60 s while only currencies trade (weekday nights), 5 min while nothing trades (weekends);
  - an exchange opening or the last one closing reruns the page once, so the new pace applies (not while a chart
    dialog is open).
- Live quotes change only the last day. The valuation of the whole history is cached once per data version and day
  (`ui.data._history`, without live quotes). Every redraw lays the newest quotes over its last day
  (`valuation.apply_live`), number for number what a full valuation with them gives (tested). The whole history is
  valued again only when `data_version` changes (an import, a market update, a manual entry), at midnight, or where
  the shortcut could differ (`apply_live` returns None).
- Keys used below: *data version* = `valuation.data_version(db)` + today's date + `MODEL_VERSION`; *live key* =
  the live prices and rates from `live_quotes` (today's only).

Measured on the demo data (1039 days, 26 positions, 13 tickers), stream every 5 s, period "Maks.", on 2026-11-18.
Profiled times are about 1.5–2× the real ones.

| | before D-071 | after D-071 |
|---|---|---|
| valuation per redraw (profiled) | 219 ms (whole history) | 27 ms (`apply_live`) |
| `headline()` per redraw, Maks. / 1D (profiled) | 207 / 306 ms | 108 / 179 ms |
| `positions()` per redraw (profiled) | 90 ms | 63 ms |
| Streamlit process on Portfel, 1 min (whole process) | 9.9 % of a core | 5.8 % of a core |
| the same on Ustawienia (feed and sidebar only; code not changed) | – | 2.5 % of a core |

## Portfel (`views/portfolio.py`)

- **Refresh:** full run on load and on any filter change (Okres, Po inflacji, Podział). Two live fragments in
  online mode, `headline()` and `positions()`, every `live_every(preferences)`. Offline: no timer. A fragment run
  that finds a new day, or a change of market pace, reruns the whole page.
- **Inputs:** `ui.data.load_valuation` (positions, cash ledger, prices, NBP rates, bonds, bank balances,
  `live_quotes`), `cpi_monthly` (Po inflacji), `intraday_quotes` (1D), `config/settings.yaml`.
- **Computed once per data version:** the valuation of the whole history (`_history`); the CPI factor; the
  composition and allocation block (`wide`, bars, segmented bar, shares table), which is outside the fragments and
  so changes only on a full run.
- **Computed on every redraw:**
  - `headline()`: live valuation (`apply_live`, cached per live key, 6 entries); `total`, flows, TWR, underwater,
    `fx_pnl` and "Dzisiaj" over the whole history (cheap vector maths, still the largest part); six sparklines
    (one Plotly constructor each); the value chart. With 1D also `one_day` and `load_intraday`
    (`intraday_values`, every row × every 5 minutes, vectorised).
  - `positions()`: holdings on the last day, cost of open lots, 90-day result trends
    (`returns.position_result_trends`, one as-of join), the table.
- **Sent to the browser:** per `headline()` run: six KPI tiles with sparklines (~3.5 KB each) and the value chart
  (~44 KB on Maks.). Per `positions()` run: the holdings table (~55 KB with 26 positions). Whole page ~142 KB
  (Maks.), ~117 KB (1D). The value chart, the sparklines and the "Pełny wykres" dialog are live charts
  (`ui.live_chart`, D-072): the same chart takes each new figure with `Plotly.react`, so it never disappears. Zoom
  survives redraws of the same view (`view=` period and unit) and resets on a new one. An open KPI dialog stays
  open. The composition and allocation charts outside the fragments stay on `st.plotly_chart`. The KPI values roll
  their changed digits (`ui.ticker`, D-074): a page script over the tiles, nothing extra from the server. While
  "Pełny wykres" is open, `headline()` also computes today every 5 minutes for that tile (`Kpi.series_today`,
  D-076), only then.

## Zwroty (`views/returns.py`)

- **Refresh:** full run on load and on filter changes. No fragments. In online mode the sidebar reruns the whole
  app at most once a minute when new live quotes arrived (`main.LIVE_PAGES`). Kept that way after measuring
  (D-071): ~170 ms per run (Maks.), ~220 ms (1D).
- **Inputs:** `load_valuation`, `cpi_monthly`, `intraday_quotes` (1D).
- **Computed once per data version:** the valuation of the history (`_history`).
- **Computed on every redraw:** live valuation (`apply_live`), TWR and XIRR for the portfolio and each account,
  drawdowns, monthly returns heatmap, attribution (prices × currencies × other); 1D: `load_intraday`.
- **Sent to the browser:** the whole page on each run: KPI row, TWR line chart, drawdown chart, heatmap, tables.

## Dywidendy (`views/dividends.py`)

- **Refresh:** full run on load and on filter changes; like Zwroty, at most once a minute in online mode when
  new live quotes arrived (`main.LIVE_PAGES`), ~70 ms per run.
- **Inputs:** `load_valuation` (portfolio value for the yield), dividend and withholding-tax events with NBP rates
  (`dividends.load_events`).
- **Computed once per data version:** `dividend_payments` (`st.cache_data` keyed by the data version) and the
  valued history.
- **Computed on every redraw:** live valuation (`apply_live`), the period window, sums per month, company and tax
  year, PIT-38 estimate.
- **Sent to the browser:** the whole page: KPI row, monthly stacked bars, tables.

## Obligacje (`views/bonds.py`)

- **Refresh:** full run on load, on filter changes and after an edit of `manual/bonds.csv` (form or upload, then
  `sync` and `st.rerun()`). No timer: bonds do not use live quotes.
- **Inputs:** `bond_lots`, `bond_series`, `bond_accounts`, `bond_issues`, the shipped series and rate files,
  `cpi_monthly`.
- **Computed once per data version:** `bond_inputs` and `bond_history` (`bonds.value_lots`), both `st.cache_data`
  keyed by the data version.
- **Computed on every redraw:** tables, KPI tiles and the value chart from the cached history.
- **Sent to the browser:** the whole page on each run.

## Gotówka (`views/cash.py`)

- **Refresh:** full run on load and after an edit of `manual/cash_balances.csv` (form or upload, then `sync` and
  `st.rerun()`). No timer.
- **Inputs:** `bank_accounts`, `cash_snapshots`, `cash_issues`, `load_valuation` (bank rows of the valuation, live
  rates on the last day in online mode).
- **Computed once per data version:** the valued history (`_history`).
- **Computed on every redraw:** live valuation (`apply_live`, only on a full run here), balances per account and
  currency, charts.
- **Sent to the browser:** the whole page on each run.

## Importy (`views/imports.py`)

- **Refresh:** full run on load and after an import (upload or inbox, then `st.rerun()`). No timer; the inbox is
  checked by the sidebar.
- **Inputs:** `source_files`, `accounts`, `cash_ledger`, `positions`, `issues` (via `reports`), the manual CSV
  files.
- **Computed once per data version:** nothing cached; every query is a small read of SQLite.
- **Computed on every redraw:** account overview, operations and positions of the chosen account, issues.
- **Sent to the browser:** the whole page on each run (tables can be large for a long history).

## Dane rynkowe (`views/market.py`)

- **Refresh:** full run on load and after "Pobierz brakujące dane" (`update_market`, then `st.rerun()`). No timer.
- **Inputs:** `prices`, `fx_rates`, `cpi_monthly`, `fetch_log` (via `reports`).
- **Computed once per data version:** nothing cached.
- **Computed on every redraw:** coverage tables and the price or rate chart of the chosen ticker or currency.
- **Sent to the browser:** the whole page on each run.

## Ustawienia (`views/settings.py`)

- **Refresh:** full run on load and after saving a setting or a reset (`st.rerun()`). A reset also clears
  `st.cache_data` and `st.cache_resource`. The fragment `resource_usage()` ("Zużycie zasobów", D-073) redraws
  every 5 s.
- **Inputs:** `config/settings.yaml`, the list of files in the data directory (reset), the resource monitor's
  samples (`diagnostics.get_monitor`, sampled in its own thread every 5 s, from one minute after start-up).
- **Computed once per data version:** nothing.
- **Computed on every redraw:** the form state; in the fragment only the 1- and 5-minute averages of at most
  60 samples and four small tiles.
- **Sent to the browser:** the whole page on each run (small).

## Sidebar (`main.py`)

- **Refresh:** two fragments on every page: `network_status()` every 5 s, `market_clock()` every 30 s. Online,
  `network_status()` reruns the whole app when the daily market update brought data, or (on Zwroty and Dywidendy)
  at most once a minute when new live quotes arrived; never while a dialog is open. The inbox check imports new
  exports at most once a minute and reruns the app if it did.
- **Inputs:** `config/settings.yaml`, the feed status (`market.feed`), `live_quotes` (time of the last price), the
  inbox folder, market hours (rules only, no network), the resource monitor (D-073): a red "Wysokie zużycie
  zasobów" link to Ustawienia only while the 1-minute CPU or the memory is high.
- **Computed once per data version:** nothing.
- **Computed on every redraw:** the mode badge, the live lamp and text, the list of exchanges with the time to
  their next change. The feed itself runs in its own thread and is only `touch()`ed here. With the stream on, a stream
  that sends nothing for a minute while markets trade is replaced by polling every 2 minutes ("strumień milczy",
  D-075).
- **Sent to the browser:** a few small elements per run. With the stream on and the Ustawienia page open (no live
  page fragments), the whole Streamlit process used 2.5 % of a core (feed and sidebar).
