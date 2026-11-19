# CLAUDE.md

## ⚠️ Critical rule: real financial data never enters the repository

Only synthetic mock data may be committed. Exports, statements, balances, account
numbers and the SQLite database stay in `data/` (git-ignored). See D-014 in
`docs/decisions.md`.

**Before every commit:**
1. Review the staged files: `git diff --cached --name-only`, then read the diff itself.
2. Run `python scripts/check_no_private_data.py` (it also runs as the pre-commit hook).
3. If anything looks like real data, or you are unsure, do not commit. Ask the user.

Never bypass the hook (`--no-verify`) and never `git add -f` an ignored file. Mock
data is generated in code (`tests/fixtures/`) or lives in `*.example.*` files with
fake values. Treat the user's real files as private: work from the masked inspector
reports, not from raw exports.

## Product principle: privacy first (R-015)

The main promise of the app is that it can run 100% locally. Every feature must keep
working without network access, on cached data. Network use is limited to public market
data, lives only in `market/`, and must respect the online/offline setting (R-016, D-031): automatic calls
only in online mode; an explicit user request (button, `fa update-market`) is allowed in both.
Never add a dependency or feature that sends data to a server: no telemetry, no hosted
APIs for processing, no cloud sync.

## What this is

A self-hosted, privacy-first portfolio tracker for a Polish investor:
- XTB brokerage accounts (PLN, EUR, USD, IKE, IKZE) loaded from xStation xlsx exports;
- cash at banks;
- Polish retail treasury bonds.

Everything is valued daily in PLN. The tool computes TWR, XIRR, drawdown, real
(inflation-adjusted) returns, dividends, and splits each return into the
instrument's own part and the FX part. Everything runs locally. The only outbound
requests are public market data: Yahoo via yfinance, NBP FX rates, GUS CPI.

## Commands

```bash
python -m venv .venv && .venv/Scripts/activate   # Windows; .venv/bin/activate elsewhere
pip install -e ".[dev]"
fa init            # data/ dirs, DB migrations, enables the privacy pre-commit hook
fa ui              # Streamlit UI on http://localhost:8501 (applies migrations first, and syncs if any ran)
fa ui --dev        # plus auto-rerun on save and developer pages (style preview on synthetic data)
fa demo [--no-ui]  # data-demo/ from a synthetic export, mock bond purchases and mock bank balances, then the UI on it
fa mock-xtb [OUT_DIR]   # synthetic xStation export (default xtb_export in the demo directory)
fa import xtb <folder|zip>  # archive an export (folder, xStation zip or .xlsx) into data/raw/xtb and sync
fa import inbox         # import new exports from the inbox folder set on Ustawienia (D-028)
fa sync / fa rebuild    # rebuild projection tables when files changed / always
fa reset [--keep-…] [--market] [--backup ZIP]   # delete source files in the data dir, rebuild (D-038)
fa settings [--online|--offline] [--live poll|stream] [--refresh 2m|5s]   # network mode (offline by default, D-021, D-069)
fa update-market        # download missing prices (Yahoo), FX rates (NBP) and CPI (GUS); an explicit request, so offline too (D-031)
pytest                  # no network access in tests (.venv/Scripts/python.exe -m pytest -q)
ruff check .
python scripts/check_no_private_data.py [--all]   # privacy check; the pre-commit hook runs it on staged files
python scripts/inspect_xtb_export.py <export_folder> --out data/samples/xtb_report.md
python -m pip wheel . --no-deps -w dist   # the release wheel (D-064, D-065); `uv tool install dist/<wheel>` to try it
```

Data directory (`config.py`, D-065): `FA_DATA_DIR` when set; in a source checkout `data/` in the
repository, and `data-demo/` for `fa demo` (both git-ignored); an installed package uses a per-user
folder (`%LOCALAPPDATA%\finance-analytics\data` on Windows, with `demo` next to it).

The XTB export format is described in `docs/xtb-export-format.md` and mirrored in
`src/finance_analytics/sources/xtb/schema.py`. Update both only from a fresh inspector
report, never from memory.

## Architecture

- `src/finance_analytics/`: all logic. No Streamlit imports outside `app/` (a test enforces it).
  - `cli.py`: the `fa` command.
  - `config.py`: where the app lives (checkout or installed package) and the data directory layout (D-065).
  - `preferences.py`: `config/settings.yaml` (`network`, `live_source`, `poll_seconds`, `stream_seconds`, `inbox_dir`, `today_tile`).
  - `db/`: plain `sqlite3`. Numbered migrations `db/migrations/0001..0010_*.sql`, version in `PRAGMA user_version`.
  - `sources/`: files → projection tables. Contents:
    - `xtb/schema.py` and `xtb/parser.py` for the export;
    - `accounts.py` for `accounts.yaml` (XTB, bonds and bank accounts);
    - `bonds.py` for `manual/bonds.csv`, `config/bond_series.yaml` and the shipped series files (D-026);
    - `cash.py` for `manual/cash_balances.csv` (bank balances, D-027);
    - `instruments.py`: asset class of an instrument (rules plus `config/instruments.yaml` overrides, D-040);
    - `manual_csv.py`: shared helpers for the hand-edited CSV files (separator, append, delete, templates);
    - `inbox.py`: the XTB inbox folder (D-028);
    - `sync.py` for import, rebuild (fingerprint of every source file) and reconciliation.
  - `reports.py`: read-only queries for the UI.
  - `mock/`: synthetic data generators (XTB export, demo bond purchases, demo bank balances).
  - `resources/`: public data shipped with the app (bond series parameters, official bond rates, NBP
    reference rate history), built from official sources (D-026). The only CSVs allowed in the repo.
  - `market/`: **the only package allowed to use the network**; a test enforces this. Contents:
    - `network.py`: the online/offline gate. Every network entry point calls `require_online` first;
    - `update.py`: works out what the portfolio needs (tickers, currencies of accounts, bank balances and prices) and runs the incremental update;
    - `yahoo.py` for prices, splits and dividends; `nbp.py` for FX rates; `gus.py` for the CPI (D-025);
    - `cache.py` for the covered ranges (`fetch_log`);
    - `live.py`: live quotes in online mode (polling client, `live_quotes`); `auto.py`: the daily auto-update schedule.
    - `feed.py`: the background live price feed: polling or Yahoo's stream, in its own thread (D-069).
    - `intraday.py`: 5-minute bars and live points in `intraday_quotes` for the 1D range (D-070).
    - `hours.py`: hours, holidays and pre/post-market of the US, London, Xetra and GPW, from rules only, no network
      (sidebar list D-068, session-based "Dzisiaj" D-067).
  - `portfolio/`: pandas maths, pure functions of their inputs.
    - `valuation.py`: daily holdings and PLN value of positions, broker cash, bonds and bank cash (D-019, D-026, D-027); `MODEL_VERSION` keys the UI cache.
    - `returns.py`: TWR, XIRR, drawdown, monthly returns (D-022).
    - `today.py`: the "Dzisiaj" tile: which day or US session it shows and its result (D-063, D-067).
    - `intraday.py`: the portfolio within one day every 5 minutes, anchored to the daily valuation (D-070).
    - `attribution.py`: the PLN return split into prices × currencies × other (D-023).
    - `slicing.py`: a filtered part of the portfolio (asset classes, instruments) with its own flows (D-085).
    - `dividends.py`: dividends in PLN at NBP D-1 and the PIT-38 estimate (D-024).
    - `inflation.py`: price level from CPI, real returns, value in today's złoty (D-025).
    - `bonds.py`: treasury bonds: interest periods, rates, daily value, coupons, early redemption (D-026).
- `src/finance_analytics/app/`: thin Streamlit UI, in Polish. Shipped inside the package as data files (every file must
  match `[tool.setuptools.package-data]`, a test checks it); `fa ui` runs Streamlit from this folder so its
  `.streamlit/config.toml` (theme, privacy settings, D-011) applies. Its modules import each other as `ui.*`.
  - `main.py`: navigation (Analiza: Portfel, Zwroty, Dywidendy, Obligacje, Gotówka; Dane: Importy, Dane rynkowe;
    Aplikacja: Ustawienia; Deweloper with `--dev`) and the sidebar fragment (inbox check, online refresh, mode badge).
  - `views/`: one page per file.
  - `ui/`: the design layer. Pages build everything through it:
    - `components.py` (page header, section, KPI row, table, empty state), `charts.py` (chart builders, `show`),
      `theme.py` (palette, light/dark tokens), `fmt.py` (Polish number, money and date formatting),
      `glossary.py` (tooltip texts, `G[...]`);
    - `data.py`: shared guard states (`require_database`, `require_valued_data`), periods and the cached valuation;
    - `manual_data.py`: CSV download, template and validated upload for the manual files (on "Importy").
- `scripts/`: standalone tools (inspector, privacy check). Standard library plus openpyxl only.
- `.githooks/pre-commit`: runs the privacy check; enabled by `fa init`.
- `tests/`: pytest, synthetic data generated in code, fake network clients; Streamlit AppTest smoke tests for pages.
- `data/` (git-ignored): `finance.db`, `raw/` (archived exports), `manual/` (CSV), `config/` (YAML), `samples/` (masked reports).

Data model principle (D-002): files in `data/` are the source of truth. SQLite holds
two kinds of tables:
- *projection* tables, rebuildable from those files;
- a persistent *market cache* (prices, FX, CPI).

## Conventions

- Code, comments and docs in English; UI text in Polish (D-005).
- Money is shown with Polish formatting (`12 345,67 zł`, `+3,4%`).
- Charts:
  - use the validated palette in fixed order;
  - a colour follows its entity, never its rank;
  - always a legend for 2+ series;
  - never two y-axes;
  - load the `dataviz` skill before designing a new chart.
- No external fonts, CDNs or telemetry in the UI (D-011).
- UI work follows `docs/ui-guidelines.md` (page anatomy, building blocks, chart and copy rules, checklist). The `/ui-page` skill loads it for UI tasks.
- `docs/panels.md` documents, per page, what reruns it and what it recomputes on every (live) redraw. Update a page's
  section together with any change to that page, its fragments or what it computes (a test checks every page has one).
- Do not name commercial portfolio trackers as inspiration in docs, code or commits.
- Tests never touch the network or real data. Fixtures are synthetic and generated in code.

## Working style

- Small steps; every step leaves the project runnable (`fa init`, `fa ui`, `pytest`).
- Ask the user before any significant architectural decision.
- Propose a commit after each step, and commit only when the user asks (after the privacy check above).
- Note user-visible changes in `CHANGELOG.md` under `Unreleased`. Releases follow D-064 and D-065: bump
  `__version__`, date the changelog section, tag `vX.Y.Z` on `main`, attach the wheel to the GitHub release.

## Decision log: `docs/decisions.md`

The single place for requirements (`R-xxx`), decisions (`D-xxx`) and open questions
(`Q-xxx`).
- Read it before planning work.
- Ideas for later (`I-xxx`) live in their own section. They are not planned work; do not build them unless the user asks.
- Every new requirement, decision or resolved question gets the next free ID, a date and a status.
- The log is append-only. A changed decision is marked `Superseded by D-xxx` and a new entry is added; nothing is deleted.
- Keep it in sync when work changes a decision, and add research findings to the *Integrations research* section.

## Skills

- `/ui-page`: design rules for building or changing pages in `src/finance_analytics/app/`. It points to `docs/ui-guidelines.md` and ends with a browser check in light and dark mode.
- `/grill-me [topic]`: interviews the user one question at a time, with a recommended answer for each, until a plan or design is fully resolved. Then it offers to record the outcome in `docs/decisions.md`. Use it before starting a new view or integration.
- `/orchestrate [tasks]`: splits a batch of independent tasks into separate sessions, one per task, each on its own worktree, with a model picked by difficulty (Haiku mechanical, Sonnet standard, the strongest for maths, performance and data model). Briefs restate the privacy and commit rules.
