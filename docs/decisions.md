# Decision log

The single place for requirements, architecture decisions and open questions.
Append-only: new entries get the next free ID; a decision that changes is not edited
or deleted but marked `Superseded by D-xxx` and a new entry is added.

- **R-xxx**: requirement (what the tool must do or respect)
- **D-xxx**: decision (date, status, context, decision, consequences)
- **Q-xxx**: open question (resolved questions point to the decision that closed them)

Statuses: `Proposed`, `Accepted`, `Superseded by D-xxx`, `Rejected`.

---

## Requirements

| ID | Requirement | Added |
|---|---|---|
| R-001 | Daily historical value of the whole portfolio in PLN, split by account and by asset class. | 2026-11-16 |
| R-002 | Return split into the instrument's own return (in its currency) and the FX part: `(1 + r_PLN) = (1 + r_local) × (1 + r_FX)`. | 2026-11-16 |
| R-003 | Dividends: gross, withholding tax, net; over time and per company. | 2026-11-16 |
| R-004 | Nominal and real return (after inflation, using historical CPI from GUS). | 2026-11-16 |
| R-005 | Metrics: TWR, XIRR, drawdown. | 2026-11-16 |
| R-006 | XTB accounts (PLN, EUR, USD, IKE, IKZE) are loaded from the manual xlsx export of xStation's account history. XTB has no public API. | 2026-11-16 |
| R-007 | Cash at banks is entered by hand as a balance on a date; statement importers may follow (see *Integrations*). | 2026-11-16 |
| R-008 | Polish retail treasury bonds (EDO, COI, …) are entered by hand as series, purchase date and quantity. The tool values them itself, including inflation indexation. | 2026-11-16 |
| R-009 | Privacy: the user's data never leaves the machine. The only outbound traffic is public market-data requests (prices, FX rates, CPI, bond parameters). | 2026-11-16 |
| R-010 | Browser UI on localhost. A polished look and good charts are a requirement, not an extra. | 2026-11-16 |
| R-011 | Manual entries through UI forms or CSV/YAML files. | 2026-11-16 |
| R-012 | Market data is cached locally so APIs are not queried on every start. | 2026-11-16 |
| R-013 | Real financial data is never committed to the repository; only synthetic mock data. | 2026-11-16 |
| R-014 | Some XTB holdings are priced in USD and EUR (also on the PLN account), so FX rates are needed for valuation. | 2026-11-16 |

---

## Decisions

### D-001 Tech stack
- **Date:** 2026-11-16 · **Status:** Accepted
- **Context:** single-user tool, local only, data-analysis heavy.
- **Decision:** Python ≥ 3.11, pandas, SQLite (one local file), Streamlit + Plotly for the UI. Market data comes from yfinance (prices, dividends, splits), the NBP API table A (FX) and GUS (CPI).
- **Consequences:** one language end to end, no server to run besides `streamlit`.

### D-002 Files are the source of truth; SQLite is a projection plus a market cache
- **Date:** 2026-11-16 · **Status:** Accepted
- **Context:** parsers will change as we learn the export formats, and manual entries should be easy to back up and diff.
- **Decision:** raw broker exports are archived under `data/raw/` (XTB: `data/raw/xtb/<account_no>/`). Manual entries live in `data/manual/*.csv` and configuration in `data/config/*.yaml`. Database tables are of two kinds:
  - *projection* tables, rebuilt from those files;
  - *market cache* tables (prices, FX, CPI), which are persistent and never dropped by a rebuild.
- **Consequences:** a parser fix is one `fa rebuild`. Performance stays good because `fa sync` re-parses only files whose sha256 or parser version changed (tracked in `source_files`). Views read only from SQLite.

### D-003 Plain sqlite3 with numbered SQL migrations
- **Date:** 2026-11-16 · **Status:** Accepted
- **Decision:** standard-library `sqlite3`, migrations as `src/finance_analytics/db/migrations/NNNN_name.sql`, version tracked in `PRAGMA user_version`. No ORM. Analytics read through `pandas.read_sql`.
- **Consequences:** a transparent schema and few dependencies. Projection tables are cheap to reshape because they are rebuilt anyway.

### D-004 Valuation computed on the fly
- **Date:** 2026-11-16 · **Status:** Accepted
- **Decision:** the daily valuation is computed in pandas from trades, prices and FX when a view opens, cached with `st.cache_data` keyed by a data version. It is not materialized in the database.
- **Consequences:** no invalidation logic. Revisit only if views become slow.

### D-005 Language
- **Date:** 2026-11-16 · **Status:** Accepted
- **Decision:** code, comments and documentation in English; the UI in Polish.

### D-006 XTB parser built from the real export structure
- **Date:** 2026-11-16 · **Status:** Accepted
- **Context:** sheet and column names must not be guessed. The export contains personal data and must not leave the machine.
- **Decision:** `scripts/inspect_xtb_export.py` runs locally on a real export and writes a masked structure report (sheets, header rows, columns, types, enumerations, masked patterns). The parser and synthetic test fixtures are built from that report. Fixtures are generated in code.
- **Consequences:** no real data in the repository or in conversations about the code.

### D-007 Scope v1: stocks and ETFs
- **Date:** 2026-11-16 · **Status:** Accepted
- **Decision:** v1 supports cash stocks and ETFs, including instruments priced in USD and EUR. CFD rows are rejected loudly, not silently skipped.

### D-008 FX rates: NBP table A
- **Date:** 2026-11-16 · **Status:** Accepted
- **Decision:** valuation uses the last NBP mid rate published on or before the valuation date. Tax-related conversions (dividends, withholding tax) use the rate from the last business day before the event (D-1), as Polish income tax rules require.

### D-009 Prices: yfinance with `auto_adjust=False`
- **Date:** 2026-11-16 · **Status:** Accepted
- **Context:** `auto_adjust=True` (the yfinance default) folds dividends into prices, which would double count them, because dividends are booked as cash from broker data.
- **Decision:** fetch with `auto_adjust=False`. `Close` is then split-adjusted but not dividend-adjusted, so historical quantities are adjusted for splits.
- **Consequences:** splits must be handled explicitly (see Q-001). London quotes in GBp are divided by 100.

### D-010 No bank aggregators
- **Date:** 2026-11-16 · **Status:** Accepted
- **Context:** an individual cannot use banks' PSD2 interfaces directly; only licensed third parties can.
- **Decision:** no PSD2 aggregators (GoCardless Bank Account Data, Salt Edge, Tink, Enable Banking, Kontomatik), because account data would pass through a third party. Bank integrations are file importers of statement exports only.

### D-011 Privacy guarantees in code
- **Date:** 2026-11-16 · **Status:** Accepted
- **Decision:**
  - Network access is allowed only in `src/finance_analytics/market/`; a test enforces it.
  - Streamlit telemetry is off (`browser.gatherUsageStats = false`) and the server binds to `localhost` only.
  - The server runs headless, so there is no first-run e-mail prompt.
  - Error displays show no "Ask Google / Ask ChatGPT" links (`client.showErrorLinks = false`), because tracebacks may contain data.
  - No external fonts or CDNs in the UI.

### D-012 UI quality through a dedicated UI layer
- **Date:** 2026-11-16 · **Status:** Accepted
- **Decision:** `app/ui/` holds:
  - a custom Plotly template: a CVD-validated categorical palette in fixed order, light and dark variants, transparent background, Polish separators, quiet gridlines, a trimmed modebar;
  - components: KPI tiles, page header, empty state;
  - Polish formatting (`12 345,67 zł`, `+3,4%`).

  Pages build charts only through this layer. A colour follows its entity (account, instrument), never its rank. Composition over time is shown as stacked bars or a single total area, and part-to-whole as a segmented bar rather than a donut.
- **Consequences:** a consistent look. Business logic stays in `src/`, so the UI could be replaced later without touching calculations.

### D-013 XTB import unit is the whole export folder
- **Date:** 2026-11-16 · **Status:** Accepted
- **Context:** the xStation export is a folder with one subfolder per XTB account number. Inside, xlsx files are named starting with the currency (`PLN`, `EUR`, `USD`) or the tax wrapper (`IKE`, `IKZE`).
- **Decision:** `fa import xtb <folder>` takes the whole folder. The account is identified by the subfolder name, and the type of account by the file prefix. Account numbers stay local; the UI shows aliases from `accounts.yaml`.

### D-014 Real financial data never enters the repository
- **Date:** 2026-11-16 · **Status:** Accepted
- **Decision:** three layers of protection.
  1. `.gitignore` acts as a deny-list: `data/`, spreadsheets, statements, documents, databases and secrets. Exceptions are only public data and `*.example.*` files with fake values.
  2. A pre-commit hook (`.githooks/pre-commit`, enabled by `fa init` via `core.hooksPath`) runs `scripts/check_no_private_data.py`. The script blocks staged files from `data/`, blocked file types, YAML outside the allowlist, and content that looks like an IBAN/NRB (checksum validated) or a card number (Luhn validated).
  3. A rule in CLAUDE.md: before every commit, review the staged file list and diff and run the check.
- **Consequences:** test fixtures are generated in code. The hook is never bypassed with `--no-verify`.

---

## Open questions

| ID | Question | Status |
|---|---|---|
| Q-001 | How does XTB record stock splits in position history (adjusted volumes and prices, or a separate operation)? | Open: check against real data |
| Q-002 | Where do COI coupons go? If to a bank account outside the tracked portfolio, they count as a withdrawal. | Open |
| Q-003 | IKE and IKZE accounts exist at XTB. Effects to model: no capital-gains tax on dividends and sales (withholding tax still applies), maybe a view of yearly contribution limits. Can bonds be held in IKE too? | Open |
| Q-004 | Benchmark for comparisons (e.g. WIG, MSCI ACWI in PLN): whether and when? | Open |
| Q-005 | Open-source licence (e.g. MIT, Apache-2.0, AGPL-3.0). | Open |

---

## Integrations research (2026-11)

Can banks, brokers and the bond registry be connected without sending data through a third party?

| Source | API for an individual | Plan |
|---|---|---|
| Revolut | None. The API is for Business plans and licensed third parties only. | Importer for the per-currency statement export (CSV). It has a running *Balance* column, so it gives balances on dates; keep only `COMPLETED` rows. |
| Trade Republic | No official API | Importer for the official CSV transaction export (in the app since April 2026). The unofficial `pytr` talks to TR directly but needs phone + PIN and can break; optional, later. |
| Erste Bank Polska (formerly Santander Bank Polska) | None | Importer for the account history CSV export. |
| Wise | Personal API tokens cannot read statements for EU customers | Importer for the CSV statement. |
| PSD2 aggregators | An individual has no direct PSD2 access | Rejected (D-010). |
| Treasury bonds (PKO BP registry) | No API; no CSV/XLS export found | Manual entry (3 fields) with automatic valuation. Series parameters come from the public issue letters ("list emisyjny") and the Ministry of Finance rate file. |

Public data sources:

- **FX:** `https://api.nbp.pl/api/exchangerates/rates/a/{code}/{from}/{to}/?format=json`. At most 93 days per request; 404 means no quotes in the range. Data from 2002.
- **CPI:** the GUS CSV "Miesięczne wskaźniki cen towarów i usług konsumpcyjnych od 1982 roku".
  - The file name changes with each release, so read the link from the page.
  - `;` separator, decimal comma, likely cp1250.
  - Index types: previous month = 100, same month a year earlier = 100, December = 100.
  - The flash estimate comes out at month end, final data around the 15th of the next month.
- **Bonds (EDO, COI):** from the second period the rate is the y/y CPI announced in the month before the period starts (in practice the figure for two months earlier), floored at 0, plus the series margin. EDO capitalises interest yearly; COI pays a yearly coupon. Early-redemption fees differ per series, so they are stored per series.
- **Prices:** yfinance (unofficial; rate-limited by Yahoo). Cache everything, fetch incrementally, back off on `YFRateLimitError`. Ticker suffixes: `.WA` Warsaw, `.L` London, `.DE` Xetra, `.AS` Amsterdam.
