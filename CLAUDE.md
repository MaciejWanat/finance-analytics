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
```

## Architecture

- `src/finance_analytics/`: all logic. No Streamlit imports here.
  - `config.py`: data directory layout (`FA_DATA_DIR`, default `./data`).
  - `db/`: plain `sqlite3`. Numbered migrations in `db/migrations/NNNN_name.sql`, version in `PRAGMA user_version`.
  - `sources/` (planned): files → projection tables (XTB parser, manual CSV/YAML, sync).
  - `market/` (planned): **the only package allowed to use the network** (NBP, Yahoo, GUS); a test enforces this.
  - `portfolio/` (planned): holdings, valuation, returns, dividends, bonds (pandas).
- `app/`: thin Streamlit UI, in Polish.
  - `main.py`: navigation.
  - `views/`: one page per file.
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
- Every new requirement, decision or resolved question gets the next free ID, a date and a status.
- The log is append-only. A changed decision is marked `Superseded by D-xxx` and a new entry is added; nothing is deleted.
- Keep it in sync when work changes a decision, and add research findings to the *Integrations research* section.

## Skills

- `/grill-me [topic]`: interviews the user one question at a time, with a recommended answer for each, until a plan or design is fully resolved. Then it offers to record the outcome in `docs/decisions.md`. Use it before starting a new view or integration.
