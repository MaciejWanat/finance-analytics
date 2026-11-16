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
data, lives only in `market/`, and must respect the online/offline setting (R-016).
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
fa ui              # Streamlit UI on http://localhost:8501
fa ui --dev        # plus developer pages (style preview on synthetic data)
pytest             # no network access in tests
ruff check .
python scripts/inspect_xtb_export.py <export_folder> --out data/samples/xtb_report.md
python scripts/check_no_private_data.py [--all]
fa mock-xtb [OUT_DIR]   # synthetic xStation export (default data-demo/xtb_export)
fa import xtb <folder>  # archive an export into data/raw/xtb and sync the database
fa sync / fa rebuild   # rebuild projection tables when files changed / always
fa update-market       # download missing prices (Yahoo), FX rates (NBP) and CPI (GUS) into the cache
fa settings [--online|--offline] [--refresh N]   # network mode (offline by default, D-021)
fa demo                # data-demo/ from a synthetic export, mock bond purchases and mock bank balances, then the UI on it
```

The XTB export format is described in `docs/xtb-export-format.md` and mirrored in
`src/finance_analytics/sources/xtb/schema.py`. Update both only from a fresh inspector
report, never from memory.

## Architecture

- `src/finance_analytics/`: all logic. No Streamlit imports here.
  - `config.py`: data directory layout (`FA_DATA_DIR`, default `./data`).
  - `db/`: plain `sqlite3`. Numbered migrations in `db/migrations/NNNN_name.sql`, version in `PRAGMA user_version`.
  - `sources/`: files → projection tables. Contents:
    - `xtb/schema.py` and `xtb/parser.py` for the export;
    - `accounts.py` for `accounts.yaml`;
    - `bonds.py` for `manual/bonds.csv`, `config/bond_series.yaml` and the shipped series files (D-026);
    - `cash.py` for `manual/cash_balances.csv` (bank balances) and `accounts.add_bank_account` (D-027);
    - `manual_csv.py`: shared helpers for the hand-edited CSV files (separator, append, delete, templates);
    - `sync.py` for import, rebuild and reconciliation.
  - `reports.py`: read-only queries for the UI.
  - `mock/`: synthetic data generators (XTB export, demo bond purchases, demo bank balances).
  - `resources/`: public data shipped with the app (bond series parameters, official bond rates, NBP
    reference rate history), built from official sources (D-026). The only CSVs allowed in the repo.
  - `market/`: **the only package allowed to use the network**; a test enforces this. Contents:
    - `nbp.py` for FX rates;
    - `gus.py` for the CPI (D-025);
    - `yahoo.py` for prices, splits and dividends;
    - `cache.py` for the covered ranges;
    - `update.py` to work out what the portfolio needs.
    - `network.py`: the online/offline gate. Every network entry point calls `require_online` first.
    - `live.py`: live quotes in online mode.
    - `auto.py`: the daily auto-update schedule.
  - `portfolio/`: pandas maths.
    - `valuation.py`: daily holdings and PLN value (D-019).
    - `returns.py`: TWR, XIRR, drawdown, monthly returns (D-022).
    - `attribution.py`: the PLN return split into prices × currencies × other (D-023).
    - `dividends.py`: dividends in PLN at NBP D-1 and the PIT-38 estimate (D-024).
    - `inflation.py`: price level from CPI, real returns, value in today's złoty (D-025).
    - `bonds.py`: treasury bonds: interest periods, rates, daily value, coupons, early redemption (D-026).
    - Bank cash (D-027) is valued inside `valuation.py`: a balance holds until the next snapshot, every change is an external flow.
- `app/`: thin Streamlit UI, in Polish.
  - `main.py`: navigation.
  - `views/`: one page per file.
  - `ui/data.py`: shared guard states and the cached valuation for analysis pages.
  - `ui/manual_data.py`: CSV download, template and validated upload for the manual files (on "Importy").
  - `ui/`: the design layer. Pages build charts and tiles only through `ui/charts.py` and `ui/components.py`, and format numbers only through `ui/fmt.py`.
- `scripts/`: standalone tools (inspector, privacy check). Standard library plus openpyxl only.
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
- Do not name commercial portfolio trackers as inspiration in docs, code or commits.
- Tests never touch the network or real data. Fixtures are synthetic and generated in code.

## Working style

- Small steps; every step leaves the project runnable (`fa init`, `fa ui`, `pytest`).
- Ask the user before any significant architectural decision.
- Propose a commit after each step, and commit only when the user asks (after the privacy check above).

## Decision log: `docs/decisions.md`

The single place for requirements (`R-xxx`), decisions (`D-xxx`) and open questions
(`Q-xxx`).
- Read it before planning work.
- Ideas for later (`I-xxx`) live in their own section. They are not planned work; do not build them unless the user asks.
- Every new requirement, decision or resolved question gets the next free ID, a date and a status.
- The log is append-only. A changed decision is marked `Superseded by D-xxx` and a new entry is added; nothing is deleted.
- Keep it in sync when work changes a decision, and add research findings to the *Integrations research* section.

## Skills

- `/ui-page`: design rules for building or changing pages in `app/`. It points to `docs/ui-guidelines.md` and ends with a browser check in light and dark mode.
- `/grill-me [topic]`: interviews the user one question at a time, with a recommended answer for each, until a plan or design is fully resolved. Then it offers to record the outcome in `docs/decisions.md`. Use it before starting a new view or integration.
