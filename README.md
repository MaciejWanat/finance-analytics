# finance-analytics

Self-hosted, privacy-first portfolio analytics for a Polish investor, valued in PLN.

It brings together XTB brokerage accounts, cash at banks and Polish retail treasury
bonds, values all of it day by day in złoty and shows where the return came from: the
instruments themselves or currency moves, dividends after tax, and performance after
inflation. Everything runs on your own computer, and it works fully offline.

## Features

The UI is a local Streamlit app, in Polish. Pages:

| Page | What it shows |
|---|---|
| **Portfel** | Value of everything in PLN over time; result for the period (TWR), contributed capital, total gain; composition and today's allocation by account, asset class, instrument or currency; current holdings with cost (NBP rate of the purchase day) and result; a "today's złoty" toggle that removes inflation. |
| **Zwroty** | TWR, XIRR, maximum and current drawdown for 1M / 3M / YTD / 1R / 3L / Maks.; cumulative TWR for the portfolio and each account; nominal vs real (after CPI) return; the split of the PLN return into prices × currencies × other, per instrument and per currency; underwater chart; per-account table; monthly returns heatmap. |
| **Dywidendy** | Gross, withholding tax and net dividends in PLN at the NBP rate of the day before payment (D-1), monthly by company, per company and per tax year, with an estimate of the Polish tax still due (PIT-38; none on IKE/IKZE). |
| **Obligacje** | Polish retail treasury bonds (OTS, ROR, DOR, TOS, COI, EDO, ROS, ROD) valued from the issue-letter rules: gross value, accrued interest, current rate and where it comes from, payout today after the early-redemption fee and tax; a form to add or delete purchases. |
| **Gotówka** | Bank balances you enter by hand (a balance holds until the next one), valued in PLN; stale balances are flagged; forms to add bank accounts and balances. |
| **Importy** | Upload xStation exports, rebuild the database, check the inbox folder; download, template and validated upload of the manual CSV files; accounts, cash operations, open and closed positions, import warnings. |
| **Dane rynkowe** | What is cached locally: prices per instrument, NBP rates, GUS CPI; a button to fetch what is missing (online mode). |
| **Ustawienia** | Offline / online mode, live refresh interval, the XTB inbox folder. |

Under the hood:
- XTB xlsx exports are parsed into lots and a cash ledger; overlapping exports are merged and cross-checked.
- Prices come from Yahoo (split-adjusted, not dividend-adjusted), FX from NBP table A, CPI from GUS; all cached in SQLite.
- Bonds are valued to the grosz without any network access: the parameters and official rates of every series sold since 2019 ship with the app.
- Every number has a tooltip that explains it in plain Polish.

## Privacy

Privacy is the point of this project. The app can run **100% on your machine**: no account,
no server, no cloud processing, no telemetry.

- **Offline is the default.** The app never goes online on its own: no background refresh, no automatic updates. It works on the data it already has. This is enforced in code and covered by tests. When you need market data (for example on first use), you fetch it once on purpose with the button on *Dane rynkowe* or `fa update-market`; only tickers, currency codes and dates are sent.
- **Online mode is your choice**, on *Ustawienia* or with `fa settings --online`. It then:
  - fetches daily prices from Yahoo Finance (via `yfinance`) and polls live prices every few minutes on weekdays;
  - fetches NBP exchange rates (daily, after the table is published);
  - downloads the public CPI file from GUS (at most once a day).

  Requests carry only tickers, currency codes and dates. Never balances, quantities, amounts or account numbers.
- **Your data stays local**: one SQLite file plus your own files in `data/`. The UI listens on `localhost` only, Streamlit usage statistics are off, and nothing is loaded from a CDN.
- **The repository never contains your data**: `data/` is git-ignored and a pre-commit hook blocks exports, statements, databases and anything that looks like an account or card number.

## Quick start

Requires Python 3.11+.

```bash
git clone <this repo> && cd finance-analytics
python -m venv .venv
.venv\Scripts\activate             # Windows
# source .venv/bin/activate        # macOS / Linux
pip install -e ".[dev]"
fa init                            # data/ folders, the database, the privacy git hook
```

Try it on synthetic data first:

```bash
fa demo        # builds data-demo/ (mock XTB export, bond purchases, bank balances) and opens the UI
```

Then with your own data:

```bash
fa import xtb <export folder>      # the folder xStation writes; the source is only read
fa import inbox                    # or: set an inbox folder on Ustawienia, new exports then import by themselves
fa settings --online               # allow public market data downloads (offline by default)
fa update-market                   # prices (Yahoo), FX rates (NBP) and CPI (GUS) into the local cache
fa ui                              # http://localhost:8501
```

Other commands: `fa sync` (rebuild the database when a file changed), `fa rebuild` (always),
`fa settings [--offline] [--refresh N]`, `fa mock-xtb [OUT_DIR]` (a synthetic export),
`fa ui --dev` (auto-rerun on save, plus a style preview page). The data directory is `./data`,
or the one set in `FA_DATA_DIR`.

## Your data files

Files in `data/` are the source of truth; the database is rebuilt from them. All of them can be
edited by hand or through the UI.

| File | Content |
|---|---|
| `raw/xtb/<account>/*.xlsx` | Archived xStation exports (copied by `fa import xtb`, the inbox or the *Importy* page). |
| `manual/bonds.csv` | Bond purchases: `account_id,series,purchase_date,quantity,note`. Series like `EDO0736`; date `YYYY-MM-DD` (or `DD.MM.YYYY`); whole bonds of 100 zł. |
| `manual/cash_balances.csv` | Bank balances: `account_id,date,balance,note`. The balance is in the account's currency and holds until the next row for that account; decimal comma accepted. |
| `config/accounts.yaml` | Accounts: `id, institution, kind (broker / bank / bonds), currency, alias, external_no, tax_wrapper (null / IKE / IKZE)`. XTB and bond accounts are added automatically, bank accounts on *Gotówka*; change `alias` to rename. |
| `config/settings.yaml` | Preferences: `network (offline / online)`, `refresh_minutes (1–60)`, `inbox_dir`. |
| `config/bond_series.yaml` | Optional: a series or an official rate newer than the app, as `series: {CODE: {first_rate, margin, early_fee, maturity_interest, rates: {period: rate}}}`. |

The CSV files accept `,` or `;` as the separator. Every row is validated; a bad row is reported on the
page and skipped, never a crash.

## Project layout

```
src/finance_analytics/   all logic, no UI code
  sources/               files -> SQLite: XTB parser, accounts, bonds, bank balances, inbox, sync
  market/                the only network code: Yahoo, NBP, GUS, cache, online/offline gate, live quotes
  portfolio/             pandas maths: valuation, returns, attribution, dividends, inflation, bonds
  db/migrations/         numbered SQL migrations
  resources/             public bond data shipped with the app
  mock/                  synthetic data generators for tests and the demo
app/                     Streamlit UI: pages in views/, design layer in ui/
scripts/                 XTB export inspector (masked report), privacy check
docs/                    decision log, UI guidelines, XTB export format
tests/                   pytest; synthetic data only, no network
```

## Development

```bash
pytest                                       # never touches the network or real data
ruff check .
python scripts/check_no_private_data.py --all   # also runs as the pre-commit hook on staged files
```

Read `docs/decisions.md` (requirements, decisions, open questions) before proposing a change, and
`docs/ui-guidelines.md` before changing a page. Never commit real financial data: test fixtures are
generated in code, and the hook must never be bypassed.

## Limitations and roadmap

- **XTB only** among brokers. Bank statement importers (Revolut, Erste, Trade Republic, Wise) are planned but wait for a masked inspection of real exports; until then bank cash is entered by hand.
- **XTB format details not yet seen in a real export** (sales, withdrawals, fees, FX conversion, currencies of USD instruments held on a PLN account) are handled by assumptions that the import reports as warnings. Stock splits are detected heuristically.
- Ticker mapping to Yahoo covers `.US` and `.UK` symbols; other markets are valued at purchase cost until a rule is added.
- The shipped bond data must be refreshed with each release; newer interest periods are computed from CPI or the NBP rate and labelled as such.
- Tax figures are estimates, not tax advice.
- Ideas for later: a customisable home page built from modules (I-001 in the decision log), a benchmark comparison.
- **Licence:** MIT, see [LICENSE](LICENSE).
