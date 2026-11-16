# finance-analytics

Self-hosted, privacy-first analytics for your savings and investments, valued in PLN.

Load your broker exports, bank balances and Polish retail treasury bonds. See what
your whole portfolio is worth, day by day, and where the return came from:
- the instruments themselves versus currency moves;
- dividends after tax;
- inflation-adjusted performance (TWR, XIRR, drawdown).

> **Status:** early development.
> - Works now: XTB import, a local cache of prices and FX rates, daily valuation in PLN, TWR/XIRR/drawdown, the split of returns into prices and currencies, dividends with a PIT-38 estimate, inflation-adjusted returns from GUS CPI, Polish retail treasury bonds (EDO, COI, ROS, ROD, TOS, OTS, ROR, DOR) valued from the issue-letter rules, and cash at banks entered by hand (balances on dates, valued in PLN) with CSV import and export of all manual data.
> - Next: statement importers for banks (see the decision log, Integrations research).

## Privacy first

Privacy is the point of this project. It can run **100% on your machine**: no account, no
server, no cloud processing, no telemetry.

- **Offline mode (the default)** makes no network calls at all; the app works on the data it already has.
- **Online mode** is switched on by you, on the *Ustawienia* page or with `fa settings --online`. It keeps
  prices live (polled every few minutes on weekdays) and downloads NBP rates daily. Only tickers,
  currency codes and dates are sent, never balances, quantities or account numbers.

- Your data stays on your machine. Everything lives in a local `data/` folder: one SQLite file plus your export files.
- The only outbound requests are public market data: prices (Yahoo Finance via `yfinance`), FX rates (NBP API) and inflation (GUS). They contain tickers and dates, nothing about your accounts.
- No telemetry: Streamlit usage statistics are disabled and the UI listens on `localhost` only.
- The repository can never contain your data. `.gitignore` and a pre-commit hook block exports, statements, databases and account numbers.

## Planned features

- Daily portfolio value in PLN, by account and by asset class.
- Return split into the instrument's own return and the FX effect: `(1 + r_PLN) = (1 + r_local) × (1 + r_FX)`.
- Dividends: gross, withholding tax and net, over time and per company.
- Nominal and real returns (CPI from GUS), TWR, XIRR, drawdown.
- Polish retail treasury bonds (EDO, COI, …) valued automatically, including inflation indexation.
- Cash balances at banks, entered by hand or imported from statement exports.

## Quick start

Requires Python 3.11+.

```bash
git clone <this repo> && cd finance-analytics
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -e ".[dev]"
fa init                         # creates data/, the database, and enables the privacy git hook
fa ui                           # opens http://localhost:8501
```

Import an XTB export (the folder xStation produces) and open the UI:

```bash
fa import xtb <export folder>
fa import inbox          # or set an inbox folder on Ustawienia: new exports are then imported automatically
fa settings --online   # allow market data downloads (offline by default)
fa update-market
fa ui
```

To try it without your own data, run `fa demo`. It builds a `data-demo/` directory from a synthetic export, a few mock bond purchases and two mock bank accounts, and opens the UI on it.

Treasury bonds are entered on the *Obligacje* page (series, purchase date, quantity) or in
`data/manual/bonds.csv` (`account_id,series,purchase_date,quantity,note`). The parameters of every series
sold since 2019 ship with the app; a newer series can be added in `data/config/bond_series.yaml`.

Cash at banks is entered on the *Gotówka* page (add a bank account, then save its balance on a date) or in
`data/manual/cash_balances.csv` (`account_id,date,balance,note`). A balance holds until the next one. The *Importy* page
downloads, and validates before appending, the CSV files of both bonds and balances.

## Project layout

```
src/finance_analytics/   logic: config, database, (soon) importers, market data, portfolio maths
app/                     Streamlit UI (Polish): pages in views/, design layer in ui/
scripts/                 standalone tools: XTB export inspector, privacy check
docs/decisions.md        requirements, decisions and open questions
data/                    your private data (git-ignored)
```

## Contributing

Read `docs/decisions.md` before proposing a change. Never commit real financial data:
tests use synthetic fixtures generated in code.
