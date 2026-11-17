# finance-analytics

Self-hosted, privacy-first portfolio analytics for a Polish investor, valued in PLN.

It brings together XTB brokerage accounts, cash at banks and Polish retail treasury bonds,
values all of it day by day in złoty and shows where the return came from: the instruments
themselves or currency moves, dividends after tax, and performance after inflation.
Everything runs on your own computer, and it works fully offline.

- [What it does](#what-it-does)
- [Core principles](#core-principles)
- [Install](#install)
- [First steps](#first-steps)
- [Everyday use](#everyday-use)
- [Troubleshooting](#troubleshooting)
- [Command reference](#command-reference)
- [Your data files](#your-data-files)
- [Development](#development)
- [Limitations and roadmap](#limitations-and-roadmap)

## What it does

You give it three kinds of input:

- **XTB accounts** (PLN, EUR, USD, IKE, IKZE): the account history export from xStation
  (xlsx files, or the zip xStation saves). XTB has no public API, so the export is the source.
- **Polish retail treasury bonds** (OTS, ROR, DOR, TOS, COI, EDO, ROS, ROD): only the series,
  purchase date and quantity. The app values them itself, interest and inflation indexation included.
- **Cash at banks**: a balance on a date, entered by hand. A balance holds until the next one.

It adds public market data (prices from Yahoo, NBP exchange rates, GUS inflation), keeps
everything in one local SQLite file and shows it in a browser UI on `localhost`, in Polish:

| Page | What it shows |
|---|---|
| **Portfel** | Value of everything in PLN over time; tiles for today's result, the result for the period (TWR), the result on currencies, contributed capital and profit vs deposits; allocation by account, asset class, instrument or currency; current holdings with cost (NBP rate of the purchase day), result and a 90-day sparkline; a "Po inflacji" switch that shows everything in today's złoty. |
| **Zwroty** | TWR, XIRR, maximum and current drawdown for 1M / 3M / YTD / 1R / 3L / Maks.; cumulative TWR for the portfolio and each account; nominal vs real (after CPI) return; the split of the PLN return into prices × currencies × other, per instrument and per currency; underwater chart; per-account table; monthly returns heatmap. |
| **Dywidendy** | Gross, withholding tax and net dividends in PLN at the NBP rate of the day before payment (D-1), monthly, per company and per tax year, with an estimate of the Polish tax still due (PIT-38; none on IKE/IKZE). |
| **Obligacje** | Treasury bonds valued from the issue-letter rules: gross value, accrued interest, current rate and where it comes from, payout today after the early-redemption fee and tax; a form to add or delete purchases. |
| **Gotówka** | Bank balances valued in PLN; stale balances are flagged; forms to add bank accounts and balances. |
| **Importy** | Upload xStation exports, rebuild the database, check the inbox folder; download, template and validated upload of the manual CSV files; accounts, cash operations, positions and import warnings. |
| **Dane rynkowe** | What is cached locally: prices per instrument, NBP rates, GUS CPI; a button to fetch what is missing. |
| **Ustawienia** | Offline / online mode, live refresh interval, the XTB inbox folder, resetting your data. |

Under the hood:

- XTB exports are parsed into lots and a cash ledger; overlapping exports are merged and cross-checked.
- Prices come from Yahoo (split-adjusted, not dividend-adjusted), FX from NBP table A, CPI from GUS; all of it is cached in SQLite and fetched incrementally.
- Bonds are valued to the grosz without any network access: the parameters and official rates of every series sold since 2019 ship with the app.
- Every number has a tooltip that explains it in plain Polish.

## Core principles

1. **Privacy first: it runs 100% on your machine.** No account, no server, no cloud processing,
   no telemetry. The only outbound requests are for public market data, and they carry only
   tickers, currency codes and dates. Never balances, quantities, amounts or account numbers.
   Network code lives in one package (`market/`), and a test enforces it.
2. **Offline by default.** A fresh install never goes online on its own: no background refresh,
   no automatic updates. You fetch market data on purpose (a button or `fa update-market`).
   Online mode, which keeps prices live, is an explicit opt-in on *Ustawienia*.
3. **Your files are the source of truth.** Exports, CSV files and YAML settings live in one data
   folder that you can back up, read and edit. The database is a projection rebuilt from those
   files, plus a cache of public market data. A parser fix is one `fa rebuild`.
4. **Polish rules, PLN everywhere.** Valuation uses the NBP mid rate (table A); dividends and tax
   use the rate of the business day before the event, as Polish tax rules require; no Polish
   capital-gains tax is estimated on IKE and IKZE; bond rules follow the issue letters.
5. **Nothing is guessed silently.** A cost the export does not prove is shown as unknown, an
   assumed export format is reported as a warning, a missing inflation figure is never invented.
6. **Your data never enters the repository.** The data folder is git-ignored, and a pre-commit
   hook blocks exports, databases and anything that looks like an account or card number.

## Install

There are two ways in: install a **release** to use the app, or install **from source** to work on it.

### Install a release (recommended)

Each [GitHub release](https://github.com/MaciejWanat/finance-analytics/releases) has the app
attached as one file, a wheel named like `finance_analytics-0.10.0-py3-none-any.whl`. You install
it with [uv](https://docs.astral.sh/uv/), a free, open-source installer for Python programs:
it puts the app in its own isolated environment, adds the `fa` command, and downloads a suitable
Python by itself if your computer has none. You need neither git nor Python beforehand.

1. **Install uv** (once). On Windows:

   ```powershell
   winget install astral-sh.uv
   ```

   On macOS `brew install uv`; on any system with Python `pip install uv`. Other ways are listed in
   the [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/).

2. **Download the wheel** of the version you want from the release page, under *Assets*. While
   the repository is private you must be signed in to GitHub with access to it; from a terminal,
   with the GitHub CLI:

   ```bash
   gh release download v0.10.0 --repo MaciejWanat/finance-analytics --pattern "*.whl"
   ```

3. **Install it:**

   ```bash
   uv tool install finance_analytics-0.10.0-py3-none-any.whl
   ```

   If the terminal then does not recognise `fa`, run `uv tool update-shell` once and open a new
   terminal.

4. **Initialise and start:**

   ```bash
   fa init        # your data folder and the database
   fa demo        # optional: look around on synthetic data first
   fa ui          # the app, on http://localhost:8501
   ```

If you have git, steps 2 and 3 can be one command that builds the release straight from its tag:
`uv tool install "git+https://github.com/MaciejWanat/finance-analytics@v0.10.0"`.

### Install from source (development)

Requires Python 3.11 or newer and git.

```bash
git clone https://github.com/MaciejWanat/finance-analytics.git
cd finance-analytics
```

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
fa init
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
fa init
```

- `-e` (editable) makes your code changes take effect without reinstalling; `[dev]` adds the
  tests, `ruff` and fast auto-rerun.
- If PowerShell refuses to run `Activate.ps1`, allow scripts for this window only with
  `Set-ExecutionPolicy -Scope Process RemoteSigned`, or call `.venv\Scripts\fa.exe` directly.
- From source, `fa init` also enables the privacy pre-commit hook
  (`git config core.hooksPath .githooks`), and the data folder is `data/` in the repository.
- `main` holds the latest code; `git checkout v0.10.0` gives a released version. What changed in
  each release is in [CHANGELOG.md](CHANGELOG.md).

## First steps

### Try the demo

```bash
fa demo
```

It builds a separate demo folder from a synthetic XTB export, mock bond purchases and mock bank
balances, then opens the UI at http://localhost:8501. Your own data is not touched.

- The demo prints warnings about an assumed export format; they are expected.
- The demo starts without market data. To see prices and currency values, open *Dane rynkowe*
  and click **Pobierz brakujące dane** (it downloads public data only).
- The demo runs in developer mode, so it also shows a *Deweloper* page with the style preview.
- Stop it with `Ctrl+C`. `fa demo --no-ui` only prepares the files.

### Load your own data

**XTB.** In xStation, export the account history to xlsx. Choose the whole period since the
account was opened: the cash balance and the cost of each position come from that history, and
a position bought before the export range has an unknown cost. Then import the zip xStation
saved, its folder, or a single `.xlsx`:

```bash
fa import xtb "C:\Users\me\Downloads\export.zip"
```

or use **Importuj** on the *Importy* page. The source is only read: the files are copied into
`raw/xtb/` in the data folder, and files already imported are skipped. New accounts appear in
`config/accounts.yaml` as "XTB PLN", "XTB IKE" and so on; change `alias` there to rename them.

**Treasury bonds.** On *Obligacje*, add each purchase with the form (series such as `EDO0736`,
purchase date, number of bonds). You can also edit `manual/bonds.csv` or upload a CSV on
*Importy*.

**Cash at banks.** On *Gotówka*, add a bank account, then save its balance whenever you like.
The file behind it is `manual/cash_balances.csv`.

**Market data.** Fetch prices, NBP rates and CPI once:

```bash
fa update-market
```

or click **Pobierz brakujące dane** on *Dane rynkowe*. Only missing days are downloaded, so the
next runs take seconds. If you want prices kept up to date while the app is open, switch to
online mode on *Ustawienia* or with `fa settings --online`.

### Start the app

```bash
fa ui
```

The UI opens at http://localhost:8501 and listens on this computer only. The terminal shows which
data folder it uses. Stop it with `Ctrl+C`.

## Everyday use

- **New XTB export:** import it as above. Overlapping exports are fine: operations are
  de-duplicated and the newest export wins. Easier still, set an inbox folder on *Ustawienia*
  (the folder where you save xStation exports): while the app is open, new files there are
  imported by themselves about once a minute. `fa import inbox` checks it once from the terminal.
- **Prices:** in offline mode, click **Pobierz brakujące dane** (or run `fa update-market`)
  when you want fresh prices. In online mode they refresh on their own.
- **Updating the app:** for a release, download the new wheel and install it the same way
  (`uv tool install finance_analytics-<new version>-py3-none-any.whl`); uv replaces the old
  version. From source, `git pull` and `pip install -e ".[dev]"`. Either way, the next `fa ui`
  applies new database migrations and rebuilds the tables from your files.
- **Backup:** copy the whole data folder. Everything that matters is there; the market cache can
  always be downloaded again. *Ustawienia* also offers a zip of your files.
- **Starting over:** *Resetowanie danych* on *Ustawienia*, or `fa reset --backup backup.zip`,
  deletes your source files and empties the database. Preferences and the inbox folder are kept.
- **Uninstalling:** `uv tool uninstall finance-analytics`. Your data folder stays; delete it
  yourself if you want it gone.

### Where your data lives

| How you run the app | Data folder |
|---|---|
| Installed release, Windows | `%LOCALAPPDATA%\finance-analytics\data`, e.g. `C:\Users\<you>\AppData\Local\finance-analytics\data` |
| Installed release, macOS | `~/Library/Application Support/finance-analytics/data` |
| Installed release, Linux | `~/.local/share/finance-analytics/data` (or under `$XDG_DATA_HOME`) |
| From source | `data/` in the repository |

The demo uses a `demo` folder next to it (`data-demo/` from source). `fa init` and `fa ui` print
the folder they use. It is deliberately not in Documents: on Windows, Documents is often synced to
OneDrive, which would copy your financial data to the cloud.

To keep the data somewhere else (for example on an encrypted drive), set `FA_DATA_DIR` to an
absolute path before running `fa`:

```powershell
$env:FA_DATA_DIR = "D:\Finanse\data"     # Windows PowerShell, this window only
```

```bash
export FA_DATA_DIR="$HOME/finanse/data"  # macOS / Linux, this shell only
```

## Troubleshooting

| Problem | What to do |
|---|---|
| `fa` is not recognised | Release: run `uv tool update-shell` and open a new terminal. From source: activate the virtual environment, or call `.venv\Scripts\fa.exe` (Windows) / `.venv/bin/fa`. |
| The app shows no data, or different data | An installed release and a source checkout use different data folders. Check the folder `fa ui` prints, and set `FA_DATA_DIR` if you want one shared folder. |
| Port 8501 is already in use | Another instance is running (for example the demo). Stop it, or use `fa ui --port 8502`. |
| "Brak notowań w Yahoo dla …" | Yahoo knows that instrument under another ticker. Map it in `config/yahoo_tickers.yaml` (`XTB_SYMBOL: YAHOO_TICKER`), then fetch again. Until then the position is valued at your own trade prices. |
| A position's cost is shown as unknown | The export does not include its purchase. Import an export that starts before it, ideally from the account opening date. |
| Yahoo stops answering (rate limit) | Wait a few minutes and fetch again; already downloaded data is kept. |
| An instrument is in the wrong asset class | Override it in `config/instruments.yaml`, e.g. `instruments: {SGLN.UK: {asset_class: precious_metals}}`. |
| Something looks wrong after an update | `fa rebuild` rebuilds the database from your files; nothing in the data folder is lost. |

## Command reference

| Command | What it does |
|---|---|
| `fa init` | Data folder, database, privacy git hook. |
| `fa ui [--port N] [--no-open] [--dev]` | Start the UI on `localhost`; `--dev` adds auto-rerun on save and developer pages. |
| `fa demo [--no-ui] [--port N]` | Build the demo folder from synthetic data and open the UI on it. |
| `fa import xtb <folder\|zip\|xlsx>` | Archive an xStation export into the data folder and sync. |
| `fa import inbox` | Check the inbox folder set on *Ustawienia* once. |
| `fa update-market` | Download missing prices (Yahoo), FX rates (NBP) and CPI (GUS); works in offline mode too, because you asked. |
| `fa settings [--online\|--offline] [--refresh N]` | Show or change the network mode and the live refresh interval (minutes). |
| `fa sync` / `fa rebuild` | Rebuild the database when a file changed / always. |
| `fa reset [--keep-exports] [--keep-manual] [--keep-accounts] [--market] [--backup ZIP] [--yes]` | Delete source files in the data folder and rebuild. |
| `fa mock-xtb [OUT_DIR]` | Write a synthetic xStation export. |

## Your data files

Files in the data folder are the source of truth; the database is rebuilt from them. All of them
can be edited by hand or through the UI.

| File | Content |
|---|---|
| `raw/xtb/<account>/*.xlsx` | Archived xStation exports (copied by `fa import xtb`, the inbox or the *Importy* page). |
| `manual/bonds.csv` | Bond purchases: `account_id,series,purchase_date,quantity,note`. Series like `EDO0736`; date `YYYY-MM-DD` (or `DD.MM.YYYY`); whole bonds of 100 zł. |
| `manual/cash_balances.csv` | Bank balances: `account_id,date,balance,note`. The balance is in the account's currency and holds until the next row for that account; decimal comma accepted. |
| `config/accounts.yaml` | Accounts: `id, institution, kind (broker / bank / bonds), currency, alias, external_no, tax_wrapper (null / IKE / IKZE)`. XTB and bond accounts are added automatically, bank accounts on *Gotówka*; change `alias` to rename. |
| `config/settings.yaml` | Preferences: `network (offline / online)`, `refresh_minutes (1–60)`, `inbox_dir`. |
| `config/yahoo_tickers.yaml` | Optional: `XTB_SYMBOL: YAHOO_TICKER` for instruments the suffix rule maps wrongly. |
| `config/instruments.yaml` | Optional: `instruments: {SYMBOL: {asset_class: stock / etf / precious_metals / other}}`. |
| `config/bond_series.yaml` | Optional: a series or an official rate newer than the app, as `series: {CODE: {first_rate, margin, early_fee, maturity_interest, rates: {period: rate}}}`. |

The CSV files accept `,` or `;` as the separator. Every row is validated; a bad row is reported on
the page and skipped, never a crash.

## Development

```bash
pip install -e ".[dev]"
pytest                                          # never touches the network or real data
ruff check .
python scripts/check_no_private_data.py --all   # also runs as the pre-commit hook on staged files
fa ui --dev                                     # auto-rerun on save, plus a style preview page
python -m pip wheel . --no-deps -w dist         # the release wheel; try it with `uv tool install dist/<wheel>`
```

Project layout:

```
src/finance_analytics/   the package: all logic, plus the UI in app/
  app/                   Streamlit UI: pages in views/, design layer in ui/, theme in .streamlit/
  sources/               files -> SQLite: XTB parser, accounts, bonds, bank balances, inbox, sync
  market/                the only network code: Yahoo, NBP, GUS, cache, online/offline gate, live quotes
  portfolio/             pandas maths: valuation, returns, attribution, dividends, inflation, bonds
  db/migrations/         numbered SQL migrations
  resources/             public bond data shipped with the app
  mock/                  synthetic data generators for tests and the demo
scripts/                 XTB export inspector (masked report), privacy check
docs/                    decision log, UI guidelines, XTB export format
tests/                   pytest; synthetic data only, no network
```

Read `docs/decisions.md` (requirements, decisions, open questions) before proposing a change, and
`docs/ui-guidelines.md` before changing a page. Never commit real financial data: test fixtures
are generated in code, and the hook must never be bypassed.

## Limitations and roadmap

- **XTB only** among brokers. Bank statement importers (Revolut, Erste, Trade Republic, Wise) are planned but wait for a masked inspection of real exports; until then bank cash is entered by hand.
- **XTB format details not yet seen in a real export** (Closed Positions values, fees, FX conversion, the currency of USD instruments held on a PLN account) are handled by assumptions that the import reports as warnings. Stock splits are detected heuristically.
- Tickers are mapped to Yahoo by suffix (`.US`, `.UK`, `.DE`, `.PL`); anything else needs a line in `config/yahoo_tickers.yaml`.
- The shipped bond data must be refreshed with each release; newer interest periods are computed from CPI or the NBP rate and labelled as such.
- Tax figures are estimates, not tax advice.
- Ideas for later: a customisable home page built from modules, editing asset classes in the UI, a benchmark comparison.
- **Licence:** MIT, see [LICENSE](LICENSE).
