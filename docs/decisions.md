# Decision log

The single place for requirements, architecture decisions and open questions.
Append-only: new entries get the next free ID; a decision that changes is not edited
or deleted but marked `Superseded by D-xxx` and a new entry is added.

- **R-xxx**: requirement (what the tool must do or respect)
- **D-xxx**: decision (date, status, context, decision, consequences)
- **Q-xxx**: open question (resolved questions point to the decision that closed them)
- **I-xxx**: idea for later; not planned yet, revisit once the prototype works

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
| R-015 | **Privacy-first is the product's main promise.** The app must be able to run 100% locally: no server-side processing, no telemetry, no outbound calls at all when the user chooses so. Any network use is limited to public market data, is visible to the user and can be switched off. | 2026-11-16 |
| R-016 | Online/offline mode, switchable in the app settings. **Online:** live prices, FX rates and all other external data kept up to date automatically. **Offline:** the app works only on already fetched data and makes no network calls. | 2026-11-16 |

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
- **Date:** 2026-11-16 · **Status:** Superseded by D-015
- **Context:** the xStation export is a folder with one subfolder per XTB account number. Inside, xlsx files are named starting with the currency (`PLN`, `EUR`, `USD`) or the tax wrapper (`IKE`, `IKZE`).
- **Decision:** `fa import xtb <folder>` takes the whole folder. The account is identified by the subfolder name, and the type of account by the file prefix. Account numbers stay local; the UI shows aliases from `accounts.yaml`.

### D-014 Real financial data never enters the repository
- **Date:** 2026-11-16 · **Status:** Accepted
- **Decision:** three layers of protection.
  1. `.gitignore` acts as a deny-list: `data/`, spreadsheets, statements, documents, databases and secrets. Exceptions are only public data and `*.example.*` files with fake values.
  2. A pre-commit hook (`.githooks/pre-commit`, enabled by `fa init` via `core.hooksPath`) runs `scripts/check_no_private_data.py`. The script blocks staged files from `data/`, blocked file types, YAML outside the allowlist, and content that looks like an IBAN/NRB (checksum validated) or a card number (Luhn validated).
  3. A rule in CLAUDE.md: before every commit, review the staged file list and diff and run the check.
- **Consequences:** test fixtures are generated in code. The hook is never bypassed with `--no-verify`.

### D-015 XTB account identity comes from the file, not the folder
- **Date:** 2026-11-16 · **Status:** Accepted (supersedes D-013)
- **Context:** the inspector report of a real export showed that one export subfolder can hold several account files (e.g. `PLN`, `IKE` and `IKZE`), each with its own account number in the file name (7 or 8 digits). Accounts with no activity still produce a file, but with three completely empty sheets. Format details: `docs/xtb-export-format.md`.
- **Decision:**
  - `fa import xtb <folder>` still takes the whole export folder and walks all subfolders.
  - Each xlsx file is one account. Its number comes from the file name (`<PREFIX>_<number>_<from>_<to>.xlsx`) and is cross-checked with the `Account number` cell (B1). The account type comes from the prefix.
  - Subfolder names are ignored.
  - Files with empty sheets are valid; they register the account without data.
- **Consequences:**
  - Sheet and column names live in one module, `sources/xtb/schema.py`.
  - `fa mock-xtb` writes a synthetic export with this exact layout, for tests and the demo.

### D-016 XTB data model: positions as lots plus a cash ledger
- **Date:** 2026-11-16 · **Status:** Accepted
- **Context:**
  - The Open Positions sheet lists every open position with its open time and price, regardless of the export's date range.
  - Cash Operations only covers the exported range.
- **Decision:**
  - `positions` holds one row per broker position (lot). It is opened once (from Open or Closed Positions) and optionally closed once.
  - `cash_ledger` holds every cash operation in the account currency, with a normalised type: DEPOSIT, BUY, SELL, DIVIDEND, WHT, INTEREST, INTEREST_TAX, …
  - Overlapping exports are merged:
    - operations are de-duplicated by their ID;
    - a closed record of a position wins over an open one;
    - otherwise the export with the latest end date wins.
  - Reconciliation warnings, never silent fixes, cover three cases: a purchase without a position, a sale without a closed position, and a position open in an older export but missing from the newest.
  - Formats not yet seen in a real export (`Stock sale`, Closed Positions values) are accepted with a warning so the demo works. Unknown types still fail the file.
- **Consequences:**
  - Daily holdings come from lots, independent of the cash range.
  - The cash balance comes from the ledger, so it needs exports covering the whole history.

### D-017 Market data cache and incremental updates
- **Date:** 2026-11-16 · **Status:** Accepted
- **Decision:**
  - Market data lives in persistent tables (`prices`, `corporate_actions`, `ticker_info`, `fx_rates`, `fetch_log`) that `fa sync`/`fa rebuild` never drop.
  - `fa update-market` (or the button on "Dane rynkowe") fetches only what is missing:
    - **what is needed:** each ticker from 7 days before its first trade or cash event; each currency from the first operation in that currency (account currency or instrument price currency);
    - **which days are final:** today is never marked final, so the next run asks for it again;
    - **Yahoo corrections:** the last 5 days are re-read every time to pick up late fixes;
    - **NBP:** at most 93 days per request; 404 means no quotes in the range.
  - Network access only in `market/`. Requests carry tickers, currency codes and dates, and a generic User-Agent.
  - XTB → Yahoo ticker rules: `.US` → no suffix, `.UK` → `.L`. Anything else stays unresolved (warning) until a rule is added.
  - Quotes in minor units (GBp/GBX) are converted.
  - `fa demo` rebuilds its files but keeps its database, so the market cache is not downloaded again.
- **Consequences:**
  - Re-running the update takes seconds.
  - Tests use fake clients and never touch the network.

### D-018 Developer auto-rerun
- **Date:** 2026-11-16 · **Status:** Accepted
- **Decision:** `fa ui --dev` and `fa demo` start Streamlit with `server.runOnSave = true` (with `watchdog` in the dev extras). Saving a source file reruns the open page automatically; session state survives. Plain `fa ui` does not watch files.

### D-019 Daily valuation rules
- **Date:** 2026-11-16 · **Status:** Accepted
- **Decision:** `portfolio/valuation.py` values every calendar day from the first event to today.
  - **Quantity:** +volume on the day a lot opens, −volume on the day it closes. A lot closed on day d is not held at the end of d.
  - **Price:** Yahoo close (split-adjusted), carried forward over days without trading.
  - **FX:** the last NBP rate published on or before the day; PLN = 1.
  - **Cash:** running sum of the cash ledger per account, converted at the same rate.
  - **Instruments without prices** are valued at purchase cost and flagged (`priced = False`, warning).
  - **Splits (Q-001):** when a split happened after a lot was opened, the lot volume is multiplied by the ratio only if its open price is within 25% of ratio × the adjusted close on the opening day. That case means the broker kept the pre-split volume. Every such case is reported.
  - **Cost in PLN** uses the rate of the opening day. External flows (deposits, withdrawals) use the rate of their day.
  - **"Wynik w okresie"** on the Portfel page is a simple approximation: value change minus net flows, divided by the start value plus inflows. TWR and XIRR come with the returns step.
- **Consequences:**
  - Valuation is a pure function of the inputs, tested on hand-computed examples.
  - The UI caches it per data version (`data_version`).
  - About 0.5 s for the demo portfolio (5 accounts, 2 years).

### D-020 UI guidelines as a document plus a skill
- **Date:** 2026-11-16 · **Status:** Accepted
- **Context:** Anthropic recommends packaging design guidance as a skill that loads only for UI work, rather than growing CLAUDE.md. Its generic frontend-aesthetics advice (distinctive web fonts, gradients, load animations) targets marketing pages. It conflicts with D-011 (no external fonts) and with a data-dense dashboard.
- **Decision:**
  - `docs/ui-guidelines.md` is the design system: principles, page anatomy, building blocks, charts, Polish copy, states, checklist.
  - `.claude/skills/ui-page/SKILL.md` is a short skill that loads it for UI tasks and requires a browser check.
  - CLAUDE.md keeps a one-line pointer.

### D-021 Online/offline mode (R-015, R-016)
- **Date:** 2026-11-16 · **Status:** Accepted
- **Decision:**
  - **Setting:** `data/config/settings.yaml` holds `network: offline | online` and `refresh_minutes`. It can be changed on the "Ustawienia" page or with `fa settings`.
  - **Default is offline**: a fresh install makes no network calls until the user switches online, after a clear explanation of what is sent.
  - **Offline:** every network entry point (`market.update.update_market`, `market.live.update_live`, the auto-refresh) checks the setting first through `market.network.require_online` and refuses with `OfflineError`. The app works only on cached data. Tests check that no socket is opened in offline mode.
  - **Online, prices:** while the app is open, polling every `refresh_minutes` (default 5, weekdays only) fetches the latest quote of every held ticker in one pass and stores it in `live_quotes`. A Streamlit fragment polls and reruns the page only when something changed. This was chosen over Yahoo's streaming WebSocket: simpler and robust to rate limits, and seconds do not matter for long-term savings.
  - **Online, FX:**
    - History, cost and tax use NBP table A (D-008). Today's NBP table is fetched by a daily refresh after 12:15 on business days.
    - Today's live value uses the market rate from Yahoo (`USDPLN=X`, …), polled together with prices.
    - Today's NBP rate is never overwritten in the database; the live rate only feeds the valuation of the current day.
  - **Online, daily data:** the incremental market update (D-017) runs automatically at most every 6 hours, and again after the NBP publication window.
- **Consequences:**
  - Offline is a hard guarantee in code, not a convention.
  - Live values are labelled with the time of the quote.

### D-022 Return metrics: TWR, XIRR, drawdown
- **Date:** 2026-11-16 · **Status:** Accepted (R-005)
- **Decision:** `portfolio/returns.py`, all in PLN.
  - **External flows** are deposits (+) and withdrawals (−) only; buys, sells, dividends and taxes are internal. Each account uses its own deposits and withdrawals.
  - **TWR:**
    - Daily sub-periods `r_t = V_t / (V_{t-1} + F_t) − 1`, with flows at the start of the day, chained into an index. Days with no capital yet count as 0.
    - The return of a window runs from the close of its first day; for "Maks." it starts at 1.0.
    - It is annualized only for windows of a year or more.
  - **XIRR:**
    - The annual rate that zeroes the cash flows: start value (money in), deposits (in), withdrawals (out), end value (out).
    - Solved with Newton's method, falling back to bisection on (−99.99%, 1000%).
    - Shown only for windows of a year or more, because an annual rate over weeks is meaningless.
  - **Drawdown:** measured on the TWR index of the window, so deposits cannot hide a fall. It reports the depth, the peak and trough dates, the recovery date and the current distance from the peak.
  - **Monthly grid:** TWR per calendar month and year, over the whole history.
  - **UI:**
    - The "Zwroty" page shows KPIs, cumulative TWR (portfolio and each account), an underwater chart, a per-account table and a monthly heatmap with a diverging blue/red scale capped at ±8%.
    - "Wynik w okresie" on Portfel now shows TWR instead of the simplified rate from D-019.
- **Consequences:** tested on hand-computed cases, including the Excel XIRR example and a case where TWR < 0 < XIRR.
  - In the demo, buys at mock prices are valued at real Yahoo prices the same day. That creates artificial jumps, so demo returns are illustrative only.

---

## Open questions

| ID | Question | Status |
|---|---|---|
| Q-001 | How does XTB record stock splits in position history (adjusted volumes and prices, or a separate operation)? | Open: check against real data |
| Q-002 | Where do COI coupons go? If to a bank account outside the tracked portfolio, they count as a withdrawal. | Open |
| Q-003 | IKE and IKZE accounts exist at XTB. Effects to model: no capital-gains tax on dividends and sales (withholding tax still applies), maybe a view of yearly contribution limits. Can bonds be held in IKE too? | Open |
| Q-004 | Benchmark for comparisons (e.g. WIG, MSCI ACWI in PLN): whether and when? | Open |
| Q-005 | Open-source licence (e.g. MIT, Apache-2.0, AGPL-3.0). | Open |
| Q-007 | Online mode: how to keep prices live, where the setting lives, how offline is enforced. | Resolved 2026-11-16 by D-021 |
| Q-006 | XTB export details not yet confirmed: ~~(a) the text-only row in an empty *Closed Positions* sheet~~ resolved 2026-11-16: a `Profit/loss` total row; ~~(b) summary row before positions~~ resolved 2026-11-16: yes; (c) cash operation types and comment formats for sales, withdrawals, fees and FX conversion, and the *Closed Positions* value types, none of which appear in the sample; (d) on PLN/EUR accounts holding USD instruments, which currency `Amount`, `Value` and the profits are in. The mock assumes the account currency. | Open: needs a larger export or the user's answer |

---

## Ideas for later

Not part of the current plan. Pick them up after a working prototype exists, with a
`/grill-me` session and a proper decision entry.

| ID | Idea | Notes | Added |
|---|---|---|---|
| I-001 | **Customisable home page from modules.** The user builds their own start page from tiles placed on a grid, e.g. KPI, value chart, allocation, dividends or holdings, and arranges them as they like. The result is a personal dashboard with exactly what they want to see. | Every existing view would need to be packaged as a self-contained module with its own settings. The layout would be stored locally (e.g. `data/config/dashboard.yaml`), in line with D-002 and R-015. Streamlit has no built-in drag-and-drop grid: a vetted component or a custom one would be needed, and it must not load anything from the internet (D-011). | 2026-11-16 |

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
