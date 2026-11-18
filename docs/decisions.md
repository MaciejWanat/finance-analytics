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
- **Date:** 2026-11-16 · **Status:** Accepted; offline semantics refined by D-031; live prices (polling in the sidebar, `refresh_minutes`, no stream) superseded by D-069
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

### D-023 Splitting the PLN return into prices, currencies and the rest
- **Date:** 2026-11-16 · **Status:** Accepted (R-002)
- **Decision:** `portfolio/attribution.py`.
  - **Daily gains per instrument**, with the quantity held overnight q, price P in the instrument's currency and NBP rate X:
    - price effect `q·(P_t − P_{t−1})·X_{t−1}`;
    - currency effect `q·P_t·(X_t − X_{t−1})`.

    The two add up exactly to the PLN gain. Foreign cash adds only a currency effect.
  - **"Other"** is the residual: dividends, interest, taxes, fees, and the gap between a purchase price and that day's close.
  - **Daily returns:**
    - `r_price = price gains / base`;
    - `(1 + r_fx) = (1 + r_price + fx gains / base) / (1 + r_price)`;
    - `r_other` closes the identity `(1 + r_PLN) = (1 + r_price)(1 + r_fx)(1 + r_other)`, using the same base as TWR (D-022).

    Chained over a window, the three cumulative parts multiply exactly into the window's TWR. Without "other" this is the requested `(1 + r_PLN) = (1 + r_local)(1 + r_FX)`.
  - **Per-instrument table:** gains in zł from price and from currency, plus the price and NBP rate change over the part of the window the instrument was held.
  - **Per-currency table:** currency gains on positions and cash.
  - **UI:** section "Akcje czy waluty?" on "Zwroty", with the identity written out, a cumulative chart of the three parts plus TWR, and both tables.
- **Consequences:**
  - A currency's gain can have the opposite sign to its rate change over the window, because it depends on how much was held when the rate moved. The UI explains this.
  - The valuation now exposes its price and rate tables (`Valuation.prices`, `.fx`). The UI cache is keyed by `MODEL_VERSION`.

### D-024 Dividends and the PIT-38 estimate
- **Date:** 2026-11-16 · **Status:** Accepted (R-003)
- **Decision:** `portfolio/dividends.py`.
  - **Source:** the broker's cash operations. DIVIDEND and WHT rows are grouped into one payment per (account, instrument, day), with gross, withheld tax and net in the account currency.
  - **PLN conversion:** the NBP mid rate of the last business day before the payment day (D-1, D-008), as the Polish tax rules require. PLN accounts are taken as credited (rate 1).
  - **Estimated tax due in Poland:** `max(0, 19% × gross PLN − WHT PLN)` on regular accounts and 0 on IKE/IKZE. It is labelled as an estimate, not tax advice.
  - **"Dywidendy" page:**
    - KPIs: net, withholding tax with its rate, tax due, and the last 12 months with the yield on today's portfolio value;
    - monthly net dividends stacked by company;
    - a per-company table and a per-tax-year table;
    - a list of all payments with the D-1 rate used.
- **Consequences:**
  - On PLN accounts the amount was converted by the broker at its own rate, not NBP D-1. Exact tax figures for those payments should be checked against the broker's yearly statement.
  - yfinance dividends (in the market cache) are not used for received amounts.

### D-025 Inflation-adjusted returns from GUS CPI
- **Date:** 2026-11-16 · **Status:** Accepted (R-004); the rule for unpublished months superseded by D-041
- **Decision:**
  - **Source:** `market/gus.py` scrapes the GUS page "Miesięczne wskaźniki cen towarów i usług konsumpcyjnych od 1982 roku" for the `.csv` link (the file name changes with every release) and downloads it. Checked against the real file (2026-11):
    - `;` separator, decimal comma, **cp1250** (UTF-8 is tried first), a trailing `;;` on every line;
    - columns `Nazwa zmiennej;Jednostka terytorialna;Sposób prezentacji;Rok;Miesiąc;Wartość;Flaga`;
    - a single variable (the all-items CPI) and a single territory (Polska), in five presentations; we keep "Poprzedni miesiąc = 100" (m/m) and "Analogiczny miesiąc poprzedniego roku = 100" (y/y);
    - months not published yet are present with an empty value and are skipped.
  - **Storage:** `cpi_monthly(year, month, mom, yoy)` (migration 0005), index points as published. It is market cache: persistent, not a projection table.
  - **Network:** the fetch sits behind `require_online` inside `update_market`, so the "Pobierz brakujące dane" button, `fa update-market` and the online auto-refresh all pick it up. It runs at most once a day (`fetch_log`, source `gus`, key `CPI`); a failure is recorded, reported as `GUS CPI` and retried on the next update.
  - **Maths** (`portfolio/inflation.py`):
    - price level chained from m/m, 100 at the first month (a gap in the months would break the chain, so only the latest unbroken run is used);
    - the level is a monthly step: all days of a month share its level;
    - months after the last published one carry the last known level, which means zero inflation is assumed for them, and are flagged as estimated;
    - window inflation `π = level(end) / level(start) − 1`, real return `(1 + nominal) / (1 + π) − 1`, annualized (only from a year, like TWR);
    - value in today's złoty `value_t × level_latest / level_t`.
  - **UI:** "Po inflacji" on "Zwroty" (inflation, nominal and real TWR, and a chart of the three cumulative curves); a toggle "W dzisiejszych złotych" on "Portfel"; CPI coverage on "Dane rynkowe". Without CPI the pages say so and link to the settings (offline) or to the market data page (online).
- **Consequences:**
  - Chaining m/m values rounded to 0.1 point drifts slightly from the published y/y index (about 0.05 point over a year), and more over decades. Windows of a few years, the normal case here, are unaffected in practice.
  - GUS publishes a month around the 15th of the next one, so the newest weeks are always estimated; the UI says so.
  - The flash estimate and the revisions of earlier months are picked up by the daily refetch (`INSERT OR REPLACE`).
  - Bonds (R-008) will reuse this table for their indexation (y/y).

### D-026 Polish retail treasury bonds (R-008)
- **Date:** 2026-11-16 · **Status:** Accepted (resolves Q-002)
- **Context:** the user enters only the series, purchase date and quantity (R-011); the app must value the bonds itself, including inflation indexation, without network access.
- **Decision:**
  - **Input:** `data/manual/bonds.csv` (`account_id,series,purchase_date,quantity,note`), edited by hand or through the form on the "Obligacje" page, which appends a row and runs the sync; a mistaken row can be deleted there (with a confirmation). Dates `RRRR-MM-DD` (also `DD.MM.RRRR`), `,` or `;` separators. Every row is validated: known series, positive whole quantity, no future date, and the series code must match purchase date + term (EDO0736 bought in July 2026). Bad rows become `import_issues` errors, never a crash.
  - **Accounts:** an `account_id` missing from `accounts.yaml` is added automatically (`institution: pko`, `kind: bonds`, PLN, alias "Obligacje skarbowe", `tax_wrapper: null`). Setting `tax_wrapper: IKE`/`IKZE` by hand removes the tax. A row pointing to a non-bonds account is rejected.
  - **Public data shipped in `src/finance_analytics/resources/`** (public, committed, allowlisted):
    - `bond_series.csv`: series, type, sale window, first-period rate, margin, early-redemption fee, OTS interest at maturity, issue-letter number. 633 series: every OTS, ROR, DOR, TOS, COI, EDO, ROS and ROD series sold from 01.2019 to 11.2026.
    - `bond_rates.csv`: the official rate of every later interest period already set (2 650 rates).
    - `nbp_reference_rate.csv`: NBP reference rate from 2015-03-05 on.
  - **Sources and how they were checked (2026-11-16):**
    - Ministry of Finance file "Dane dotyczące obligacji detalicznych" (xls on gov.pl/web/finanse/obligacje-detaliczne1): sale dates, first rate, margin, the rate of every elapsed period and the interest paid.
    - The issue letter of every series (obligacjeskarbowe.pl, "Listy emisyjne" and "Archiwum"), 633 PDFs parsed: first rate and margin agree with the MF file for every series; the fee, the fee cap and the OTS interest come from the letters. (The letter of EDO0134 has a typo, "wynos 6,90%"; checked by hand.)
    - NBP XML `static.nbp.pl/dane/stopy/stopy_procentowe_archiwum.xml`.
    - Left out because their issue letters are not published on obligacjeskarbowe.pl: **COI0923** and **EDO0829**. Not covered: DOS and TOZ (sold until mid-2022; TOZ needs WIBOR 6M), POS, KOS, and series sold before 2019. Any of them can be added in `data/config/bond_series.yaml`.
  - **User overrides:** `data/config/bond_series.yaml`, `series: {CODE: {first_rate, margin, early_fee, maturity_interest, rates: {period: rate}}}`, merged over the shipped file (a new series or a newly announced rate). Errors there are reported and the entry is skipped.
  - **Rules** (`portfolio/bonds.py`, pure, `Decimal` arithmetic), per the issue letters:
    - Nominal 100 zł. The code holds the redemption month and year; maturity = purchase + term (OTS 3 months, ROR 1 year, DOR 2, TOS 3, COI 4, ROS 6, EDO 10, ROD 12 years).
    - Periods are anchored on the purchase date: period k starts on purchase + (k-1) years (months for ROR/DOR), clamped to a shorter month's end (30.11 → 28.02 → 30.03), as in the ROR/DOR letters' period tables.
    - Accrual is actual/actual within the period: `base × r × (months/12) × a / D`, `a` = days from the period start (inclusive) to the day (exclusive), `D` = period length. Rounded to the grosz per bond (half up). The value on day d is the one in the official interest table for d.
    - EDO, ROS, ROD, TOS capitalise yearly without intermediate rounding: `100 × Π(1 + r_j) × (1 + r_k × a/D)`. Paid at maturity.
    - COI pays `round(100 × r, 2)` every year; ROR and DOR pay `round(100 × r / 12, 2)` every month, on the last day of the period.
    - OTS pays the interest amount fixed in its letter (e.g. 0,37 zł for OTS0419 at 1.50%, not 0,375 → 0,38); it is accrued evenly for the daily value.
    - EDO, COI, ROS, ROD from period 2: CPI y/y announced by GUS in the month before the period starts (the figure for two months earlier), floored at 0, plus the margin.
    - ROR, DOR from period 2: NBP reference rate in force on the 10th working day (Saturdays, Sundays and Polish public holidays excluded) before the first day of the month in which the period starts, floored at 0, plus the margin.
    - Rate precedence: the official rate (shipped or the user's YAML) wins; otherwise it is computed from the CPI cache (`cpi_monthly`, D-025) or the shipped NBP history and labelled "wyliczona". If the CPI needed is missing, only the margin is used (the guaranteed minimum; inflation is never invented) and the period is flagged "tylko marża".
    - Early redemption: value minus the fee per bond. EDO, ROS, ROD, TOS: the fee never exceeds the accrued interest (value ≥ 100). COI, ROR, DOR: capped only in period 1, the full fee afterwards. OTS: nominal only, no interest. 19% tax on the interest left after the fee (none on IKE/IKZE), per lot, to the grosz.
  - **Verification:**
    - Every value in six official interest tables (EDO0129 period 8, TOS0127 period 3, COI0328 period 3, ROS0130 period 3, ROR0127 and DOR0127 period 1; 1 525 days) is reproduced to the grosz.
    - Every elapsed rate in the MF file is reproduced by the rules: all 1 602 ROR/DOR monthly rates from the NBP history; all CPI-indexed rates except those of periods starting in March (99 cases), because GUS revises the January CPI after the bond rate is set. That is why official rates are shipped and win.
    - Every coupon and redemption amount in the MF file (OTS, TOS, COI, ROR, DOR, ROS) is reproduced.
    - The PKO example on the EDO page (EDO0524: 4,16 zł interest − 2 zł fee − 0,41 zł tax = 101,75 zł) is reproduced.
  - **Differences between older and newer series:** the fees rose for series sold from September 2024: EDO 2,00 → 3,00 zł, COI 0,70 → 2,00 zł, ROS 0,70 → 2,00 zł, ROD 2,00 → 3,00 zł, TOS 0,70 → 1,00 zł; ROR (0,50 zł) and DOR (0,70 zł) unchanged. The fee rules, rate rules and formulas are the same in every 2019–2026 letter. ROR and DOR exist from June 2022 and TOS from August 2022. The TOS letters define the base of later periods as rounded to the grosz, but the official interest tables use the unrounded base; the app follows the tables (differences of 1 grosz).
  - **Storage:** projection tables `bond_series`, `bond_rates`, `bond_reference_rate`, `bond_lots` (migrations 0006, 0007), rebuilt by `fa sync`. `bonds.csv`, `bond_series.yaml` and the three shipped files are in the sync fingerprint, so an edit or an app update triggers a rebuild.
  - **Valuation (D-019):** `Inputs.bonds` carries the lots, parameters, rates, CPI and reference rate; `value_portfolio` stays pure and adds one row per (account, series) per day: `kind = bond`, `asset_class = bond`, PLN, `value_pln` = gross value (nominal + accrued and capitalised interest). A lot is held from its purchase day to the day before redemption. `MODEL_VERSION` = 3.
  - **Flows (D-022, resolves Q-002):** a purchase is an external deposit into the bonds account (100 zł × quantity). Coupons (COI, ROR, DOR) and redemption proceeds are external withdrawals, net of the 19% tax (gross on IKE/IKZE), because PKO pays them to a bank account outside the tracked portfolio.
  - **UI:** page "Obligacje" (group "Analiza", after "Dywidendy"): KPIs (gross value, accrued interest, payout today after fee and tax, average current rate), the value over time, one row per purchase (series, type, quantity, purchase date, maturity, current rate and its source, end of the interest period, gross value, interest, payout), the parameters of the series held, the form "Dodaj zakup obligacji", the list of saved purchases with deletion, and notes. Every term has a glossary tooltip. Bonds also appear in "Portfel", "Zwroty", the attribution and the inflation views.
  - **Demo:** `fa demo` writes mock purchases (EDO, COI, ROR from 2024–2025) to `data-demo/manual/bonds.csv`.
- **Consequences:**
  - Bonds are valued fully offline; no network code was added.
  - Bond interest lands in the "other" part of the return split (D-023), as do dividends.
  - On a coupon or redemption day the 19% tax shows as a small loss, because the value drops by the gross amount while only the net amount is withdrawn. TWR and XIRR are therefore after tax at source.
  - "Do wypłaty" is an estimate: the bank accrues interest for five more working days after the order, and the tax is computed per order.
  - Purchases through a swap ("zamiana", price 99,90 zł) are counted at 100 zł.
  - Coupons on an IKE are counted as withdrawals too, although they stay on the IKE register (see Q-003).
  - The shipped files need refreshing with each app release (new series, new official rates). Until then, newer periods are computed and labelled "wyliczona", and a new series needs a YAML entry.

### D-027 Cash at banks, entered by hand (R-007, R-011)
- **Date:** 2026-11-16 · **Status:** Accepted
- **Context:** bank cash must count in the portfolio value, but there is no bank API (D-010) and no confirmed statement format yet. The user enters balances; all manual data (bonds too) must also be editable as CSV (R-011).
- **Decision:**
  - **Accounts:** bank accounts are entries in `data/config/accounts.yaml` with `kind: bank` (fields as for any account). The "Gotówka" page adds one (name, currency from PLN/EUR/USD/GBP/CHF, optional institution). The id is `bank-<slug of the alias>` (Polish letters folded, made unique with a number), the alias must be unique, existing entries are left as they are.
  - **Balances (source of truth, D-002):** `data/manual/cash_balances.csv`, columns `account_id,date,balance,note`; the balance is in the account's currency and may be negative. Dates `RRRR-MM-DD` (also `DD.MM.RRRR`), `,` or `;` separators, decimal comma accepted. Every row is validated: the account exists and is a bank account, the date is real and not in the future, the balance is a finite number, and there is one balance per account and day (a later duplicate is rejected). Bad rows become `import_issues` errors, never a crash. The form on the page appends a row and runs the sync; a row can be deleted there (with a confirmation).
  - **Storage:** projection table `cash_snapshots` (migration 0008), rebuilt by `fa sync`; the file is in the sync fingerprint (`source_files.kind = manual_cash`).
  - **Valuation (D-019):** `Inputs.cash_snapshots`; `value_portfolio` stays pure. A balance is a step function: a snapshot holds until the next one, and before the first snapshot the account does not exist (no rows). Every calendar day up to `end` gets a row `kind = cash`, `asset_class = cash`, `symbol = Gotówka`, account = alias, `value_pln` = balance × NBP rate (PLN = 1; carried over days without a rate, live rate on the last day in online mode like XTB cash). Snapshots after `end` are ignored. `MODEL_VERSION` = 4.
  - **Flows (D-022):** every change of a bank balance, the first snapshot included, is an external flow (`type = BANK`): positive when money enters, negative when it leaves (salary in, spending out), converted at the NBP rate of the snapshot day. Bank cash therefore never shows a return from deposits or spending, and TWR/XIRR measure only the invested part.
  - **UI:** page "Gotówka" (group "Analiza", after "Obligacje"): KPIs (cash total in PLN, number of accounts, last update), the value over time, a table per account (balance, value in PLN, balance date, status "nieaktualne" when the last balance is older than 30 days, with a warning), forms "Dodaj konto bankowe" and "Zapisz saldo", the list of saved balances with deletion. Glossary tooltips for saldo, konto bankowe, snapshot salda. Bank cash appears in "Portfel" automatically (asset class "Gotówka").
  - **CSV import/export of all manual data:** a section on "Importy" (`ui/manual_data.py`) for `cash_balances.csv` and `bonds.csv`: download of the current file, download of an empty template (header only), and upload. An uploaded file is validated and previewed first: valid rows are listed, rejected rows are shown with their row number and reason; only after a click are the valid rows appended to the existing file. Nothing is overwritten: a balance for an account and day that already exists and a bond purchase identical to a saved one are skipped and reported, so uploading a file twice changes nothing. Downloads are served by the local app; no network.
  - **Demo:** `fa demo` adds the accounts "Bank PLN" (PLN) and "Konto EUR" (EUR) with a few balances from 2024–2026 to `data-demo/` only.
- **Consequences:**
  - Interest on a savings account is not counted as a return: it is a change of balance, hence a flow. Likewise a salary or spending is a flow, not a gain or a loss.
  - A transfer from a bank account to XTB cancels out (the bank side is a withdrawal, the XTB deposit a deposit), so TWR is unaffected. Until the next balance is entered the bank value stays flat, so the total value counts that money twice for a while; entering the balance soon after a transfer keeps this short.
  - Foreign-currency bank balances do show a return: the FX part (R-002), because only the balance, not the rate, is entered. It lands in the "currencies" part of the split (D-023).
  - Accuracy depends on how often balances are entered: between two snapshots the value is flat, and a salary or an expense is dated to the snapshot day.
  - A balance in a currency without NBP rates in the cache cannot be valued; the page says so.
  - No bank importer was written, and no bank export format was assumed (see the research notes).


### D-028 XTB inbox folder: automatic import of new exports
- **Date:** 2026-11-16 · **Status:** Accepted
- **Context:** the only manual step left in the XTB flow is exporting from xStation. Importing each file by hand (D-013) is easy to forget.
- **Decision:**
  - **Setting:** `inbox_dir` in `data/config/settings.yaml` (absolute path, default none = off), set on "Ustawienia" with a check that the folder exists. Old settings files load unchanged.
  - **Behaviour:** `check_inbox` (`sources/inbox.py`) runs the same import as `fa import xtb`: new `.xlsx` files are copied into `data/raw/xtb`, files already imported are skipped, and `sync` runs only when something was copied. The source folder is only read.
  - **Triggers:** the sidebar fragment checks the folder at most once a minute and not on the first run of a session. It runs before the online/offline branch, so it works offline. Each import shows a toast and reruns the app. Also `fa import inbox` (one check, prints the result) and "Sprawdź folder teraz" on "Importy".
  - **Errors:** a missing folder or an unreadable file becomes a message, never a crash.
  - **Privacy:** local only, no network code. The folder path stays in the git-ignored `data/`.
- **Consequences:**
  - A file that is still open in Excel may fail to copy; it is picked up on a later check.
  - The whole folder is read on every check (about once a minute): fine for an export folder, not for a very large one.

### D-029 Release review
- **Date:** 2026-11-16 · **Status:** Accepted
- **Context:** the features were built one after another; a final pass checked the money maths, data flow, edge cases (empty database, only bonds, only bank cash, a currency without NBP rates, a single day) and page consistency. No new features.
- **Decision:** fixed, each with a regression test:
  - **Valuation:** nothing that could be valued up to the end day (e.g. only a bank balance in a currency without NBP rates, or only unknown bond series) returned a crash instead of an empty valuation; deposits and withdrawals dated after the end day were kept in the flows. The empty valuation now has all columns, and the pages say why nothing is valued (missing NBP rates) instead of failing. `MODEL_VERSION` = 5.
  - **Market data:** the currencies of bank accounts (D-027) were not in the list of NBP rates to fetch, so a EUR bank account without a EUR broker account could never be valued. "Dane rynkowe" asked for a broker export first, so with only bonds or only bank cash the update (CPI, FX) could not be started from the UI.
  - **Attribution:** a currency with prices but no NBP rates raised in the per-currency table; its rate change is now shown as missing.
  - **Tables:** a numeric column with only empty values (e.g. XIRR for a window under a year on every row) crashed the table helper; numeric columns keep their gaps, shown as "–".
  - **Upgrades:** `fa ui` applies migrations and, when any ran, syncs right away. Migration 0007 empties `bond_series`, so an upgraded database used to show bonds without parameters until the next sync.
  - **Consistency:** one shared `require_database` guard (`ui/data.py`) instead of three copies; valuation warnings in Polish like the bond ones; Polish plurals for inbox imports; the sync warning for an unmapped ticker no longer points to a nonexistent `instruments.yaml`; the settings page, `fa settings` and the preferences header now mention GUS among online sources.
  - **Docs:** README rewritten for a finished app; CLAUDE.md commands and architecture brought up to date.
- **Consequences:** import and sync messages from the XTB parser and reconciliation are still in English on the "Importy" page; translating them is left for a later change.

### D-030 Licence: MIT
- **Date:** 2026-11-16 · **Status:** Accepted (resolves Q-005)
- **Decision:** the project is released under the MIT licence (`LICENSE`, `pyproject.toml`).
- **Consequences:** anyone may use, modify and redistribute the code, including in closed forks, as long as the copyright notice is kept. The shipped public reference data (bond series, NBP reference rates) comes from official public sources.

### D-031 Offline means "never on its own"; manual fetch is always allowed
- **Date:** 2026-11-16 · **Status:** Accepted (refines D-021)
- **Context:** with a hard offline gate, a fresh install (offline by default) could never get its first prices, FX rates or CPI, so it could not value anything.
- **Decision:**
  - Offline mode stops every **automatic** network call: the live-quote polling, the daily auto-update and anything started without the user asking.
  - An **explicit request** works in both modes and fetches only the public market data (tickers, currency codes, dates):
    - the "Pobierz brakujące dane" button on *Dane rynkowe*;
    - `fa update-market`.

    In code, `update_market(..., manual=True)` skips `require_online`; automatic callers keep the gate.
- **Consequences:**
  - The app can start from scratch while offline.
  - The privacy promise is unchanged: nothing leaves the machine unless the user clicks or types it, and never anything about the accounts.
  - The UI explains that an offline fetch is a one-off.

### D-032 Robust timestamps and pairing of purchases with positions
- **Date:** 2026-11-16 · **Status:** Accepted
- **Context:** a real export showed two things:
  - timestamps with milliseconds next to whole seconds, which crashed date parsing;
  - purchases in Cash Operations whose position ID differs from the one in the position sheets, so their cost was missing.
- **Decision:**
  - Timestamps are stored without fractions of a second and read with an ISO 8601 parser that accepts both forms.
  - Purchases and sales are paired with positions first by ID and then by account, ticker, volume (from the `OPEN BUY` comment) and the nearest time within 10 minutes.
  - Only unpaired ones are reported.
  - `PARSER_VERSION` is now 2, so the next sync rebuilds the projection.

### D-033 Sub-accounts: the file name identifies the account, B1 names the main account
- **Date:** 2026-11-16 · **Status:** Accepted (refines D-015)
- **Context:** in a real export, IKE and IKZE (and the PLN account of the same login) are sub-accounts.
  - Their files sit in the folder of the main account and carry their own number in the file name.
  - Cell B1 holds the main account's number.
  - The parser rejected these files because B1 did not match the file name.
- **Decision:**
  - The number in the file name is the account (as in D-015). Each sub-account stays a separate account with its own tax wrapper.
  - A different number in B1 is not an error. It is stored as `parent_no` in accounts.yaml.
  - A1 must still read "Account number".
  - `PARSER_VERSION` 3 re-parses previously rejected files.
- **Also:** after "Importuj" the upload picker is emptied. Files that failed stay listed as errors with their reason, so they can be picked again.

### D-034 A sheet with only its header block means "nothing of this kind"
- **Date:** 2026-11-16 · **Status:** Accepted
- **Context:** a real export contained a sheet with the header block (account number, title) but no table. It belongs to a sub-account with no operations in the exported range, and the parser rejected the whole file.
- **Decision:**
  - A sheet that does not reach its header row, or whose header row is empty, is skipped as "no data of this kind". The other sheets of the file are still read.
  - A Cash Operations table with a header but no rows needs no "Total" row.
  - A header that is present but different still fails the file (D-006).
  - `PARSER_VERSION` 4.

### D-035 XTB export variants: worksheet dimensions, product summaries and traded categories
- **Date:** 2026-11-17 · **Status:** Accepted
- **Context:** a fresh masked inspector report of five real exports showed that some files declare an empty worksheet range even though Excel displays data. It also confirmed that the Open Positions summary has a variable number of rows, and that current holdings include categories `ETC` and `ETN` and ticker suffixes `.DE` and `.PL`.
- **Decision:**
  - The XTB parser and masked inspector reset a worksheet's declared dimensions before reading it, so they scan actual cells rather than stale XLSX metadata.
  - Open Positions finds its table by the complete header, after the variable-length product summary. `Product` remains informational; its value is not restricted.
  - `ETC` and `ETN` are accepted and use the existing `other` asset class (shown as "Inne") until a future dedicated classification is requested.
  - XTB `.DE` maps to Yahoo `.DE`; XTB `.PL` maps to Yahoo `.WA`. Existing `.US` and `.UK` mappings remain unchanged.
  - `PARSER_VERSION` 8 rebuilds projections on the next sync.
- **Consequences:** accounts containing ETC or ETN positions are imported instead of being rejected as a whole. They appear in the portfolio and receive market-price updates where Yahoo recognises the mapped ticker; an unmapped or unavailable quote remains visible as an import/valuation warning rather than silently using a fabricated price.

### D-036 Blank Cash Operations total means no cash activity
- **Date:** 2026-11-17 · **Status:** Accepted
- **Context:** a fresh masked inspector report showed accounts whose Cash Operations sheet contains only the `Total` row, with an empty amount.
- **Decision:** treat that exact shape as an empty cash-operations table. A blank amount remains invalid when actual operations precede the total. `PARSER_VERSION` 9 re-parses exports on the next sync.
- **Consequences:** an account that only has open positions is imported instead of being rejected because it has no cash history in the selected export range.

### D-037 Unknown purchase cost is visible, never estimated
- **Date:** 2026-11-17 · **Status:** Accepted
- **Context:** an export range can contain an open position but not its `Stock purchase` cash operation. The Open Positions sheet exposes the opening price and volume, but not a verified total cost in the account currency after conversion and fees.
- **Decision:** preserve the missing purchase value rather than infer it. The importer emits a warning for every open position without a matching purchase value, explaining that an export covering its purchase is needed. The UI renders the cost as `unknown` rather than `None`.
- **Consequences:** portfolio value can still use market prices, while cost, unrealised profit and return based on that cost remain unavailable until the earlier history is imported.

### D-038 Resetting data from the app
- **Date:** 2026-11-17 · **Status:** Accepted
- **Context:** the user asked for a button that resets the database by deleting all source files, for example to start over after a test import.
- **Decision:**
  - A "Resetowanie danych" section on Ustawienia and `fa reset` delete chosen groups of source files: archived exports (`raw/`), manual entries (`manual/bonds.csv`, `manual/cash_balances.csv`) and account configuration (`config/accounts.yaml`, `config/bond_series.yaml`). The cached public market data is cleared only when asked.
  - Only known files inside the data directory are deleted. `settings.yaml` and the inbox folder are never touched.
  - The page offers a zip backup of exports, manual files and configuration first, and the delete button stays disabled until the user types `USUŃ`. The CLI asks for confirmation unless `--yes` is given and writes a backup with `--backup`.
  - After deleting, the projection is rebuilt from the remaining files (D-002), so the database never shows data whose source is gone.
- **Consequences:** the user can start over without hunting for files; nothing outside the data directory can be removed.

### D-039 Yahoo ticker exceptions and "no quotes" warning
- **Date:** 2026-11-17 · **Status:** Accepted
- **Context:** some XTB symbols map by the suffix rule to a Yahoo ticker that Yahoo does not carry (for example an ETP Yahoo only lists on another exchange). The fetch failed with a raw yfinance message and was retried on every update.
- **Decision:**
  - `.DE` maps to `.DE` in `YAHOO_SUFFIX`. Exceptions are not built in: a list of symbols in a public repository would reveal which instruments the author holds.
  - The user maps such symbols in `config/yahoo_tickers.yaml` (`XTB_SYMBOL: YAHOO_TICKER`). It wins over the suffix rule and is part of the sync fingerprint. A broken file is ignored.
  - A ticker Yahoo does not know gives a Polish warning ("Brak notowań w Yahoo dla X — ..."). It is stored in `fetch_log.last_error` and the ticker is not requested again for 7 days (`NO_QUOTES_RETRY_DAYS`), unless it already has cached prices.
- **Consequence:** the price currency comes from Yahoo (`ticker_info`), so a USD or CHF listing is converted at NBP rates like any other foreign price.

### D-040 Precious metals asset class and per-symbol overrides
- **Date:** 2026-11-17 · **Status:** Accepted (refines D-035)
- **Context:** the user wants gold, silver and other precious metals as their own asset class. Until now every `ETC` and `ETN` fell into `other` ("Inne"), together with crypto and oil notes (for example a bitcoin ETP), and nothing in the UI said which instruments that class held. For the user what matters is the metal that drives the price, so a fund holding gold counts as gold whatever its wrapper.
- **Decision:**
  - New asset class `precious_metals` ("Metale szlachetne"). Migration `0009_precious_metals.sql` recreates the `instruments` projection table with the wider CHECK (SQLite cannot alter it in place), empties `positions` and `cash_ledger` that reference it, and forgets the shipped files' fingerprint so the next sync rebuilds (as in 0007). `PARSER_VERSION` = 11.
  - Rule (`sources/instruments.py`): an instrument of XTB category `ETC`, `ETN` or `ETF` whose name contains a precious metal as a whole word (gold, silver, platinum, palladium, precious, bullion, XAU, XAG, złoto, srebro, platyna, pallad) is `precious_metals`, unless the name says it is a fund of mining companies (miner, mining, producer, explorer, górnicz…), which stays `etf`. Single stocks are never classified by name. Everything else keeps the category mapping of D-035 (`ETC`/`ETN` without a metal name stay `other`).
  - Overrides: optional `data/config/instruments.yaml` (private), `instruments: {SYMBOL: {asset_class: stock | etf | precious_metals | other}}`. An override wins over the rule. The file is part of the sync fingerprint, so editing it rebuilds; a malformed file is reported as an import error and ignored, the rest of the import still works.
  - UI: the class colour follows a fixed class order (Akcje, ETF, Obligacje, Metale szlachetne, Gotówka → palette slots 1–5; "Inne" keeps the neutral colour), so adding a class never repaints the others. "Bieżące pozycje" on Portfel gains a "Klasa" column, and a tooltip (`G["asset_class"]`) explains what each class holds, what "Inne" means and where to override it.
  - The synthetic XTB export holds a gold ETC (`SGLN.UK`, "Physical Gold ETC") on the PLN account.
- **Consequences:** gold and silver ETCs and gold ETFs show as their own slice of the portfolio; crypto and commodity notes still show as "Inne" and are now listed with their class in the holdings table. A wrong guess is fixed by one line in `instruments.yaml`; editing it from the UI is I-002.

### D-041 Profit after inflation ("na czysto") next to the nominal figures
- **Date:** 2026-11-17 · **Status:** Accepted (extends D-025 and supersedes its rule for unpublished months)
- **Context:** the user wants to know how much they earned "na czysto", after inflation. D-025 already gave the real TWR on "Zwroty" and a "today's złoty" toggle for the value chart on "Portfel", but no amount in złoty and nothing money-weighted.
- **Decision:**
  - **Definition:** real profit = value at the end − every deposit and withdrawal restated in the złoty of the end day (`amount × level(end) / level(day of the flow)`). Example: 10 000 zł paid in when prices were 8% lower is 10 800 zł today; at a value of 11 500 zł the nominal profit is 1 500 zł and the real profit 700 zł. Bank cash is included like everywhere else (D-027), so idle cash shows its real loss.
  - **Maths** (`portfolio/inflation.py`, pure, tested on synthetic data): `real_profit` (whole history, or a D-022 window where the start value counts as money put in), `real_xirr` (XIRR of the cash flows and values restated in end-day złoty; shown, like XIRR, for windows of a year or more), `real_return_with_payouts` (holdings that pay out, for bonds), `in_todays_zloty`, `daily_from_cpi`. `portfolio/bonds.paid_out` lists the payments already made on a lot.
  - **Unpublished CPI months (supersedes the D-025 rule):** instead of carrying the last level (zero inflation), the last published y/y index is spread evenly over months, `(yoy/100)^(1/12)`, and the months are still flagged as estimated. This applies everywhere the price level is used (Portfel, Zwroty, Obligacje).
  - **UI: real figures always next to the nominal ones; no new global or per-page toggle.** The existing "W dzisiejszych złotych" chart toggle on "Portfel" stays.
    - "Portfel": the "Zysk całkowity" tile keeps the nominal amount and shows "realnie ±X zł" as its delta (a fifth tile would break the four-tile rule); the tooltip explains it and gives the percentage of deposits in today's złoty.
    - "Zwroty", section "Po inflacji": real profit in złoty for the window (all deposits for "Maks.", so it matches the tile) and the real XIRR next to the nominal one; a "TWR realnie" column in the per-account table, using the inflation from the later of the window start and the account's first day with money.
    - "Obligacje": a "Realnie od zakupu" column per purchase, `(gross value + coupons paid) / purchase − 1` in today's złoty (before tax and the early-redemption fee), and a nominal-weighted average above the table.
    - Glossary: `real_profit`, `real_xirr`, `twr_real`, `bond_real`; `cpi_estimated` updated.
  - Not built: dividends in today's złoty (small amounts spread over time, and PIT-38 is nominal anyway).
- **Consequences:**
  - Without saved CPI the tile says "realnie: brak CPI", the bond column is hidden with a hint, and "Zwroty" keeps its existing empty state. Everything works offline on the saved CPI (R-015).
  - The extrapolation is a forecast for the newest one or two months; it changes slightly when GUS publishes the month. The UI still says the result is approximate.
  - The average on "Obligacje" weights lots by nominal, not by money in today's złoty, so it is exact only for lots bought in the same month.

### D-042 Faster market updates: closed tickers stop, a rate limit stops the run, progress is shown
- **Date:** 2026-11-17 · **Status:** Accepted (extends D-017)
- **Context:** measured on the demo portfolio (12 tickers, 2 currencies, about 2 years): the first update took 7 s (Yahoo 2.3 s, NBP 3.7 s in 20 requests of ≤93 days, GUS 0.9 s), each later one 2.5 s (one Yahoo request per ticker for the last 5 days, about 1 s of it the yfinance cold start, plus one NBP request per currency for today). Three things grew with a real portfolio:
  - every ticker ever held was asked for again on each run, including sold ones; a ticker Yahoo does not know ("possibly delisted") costs about 1 s per run;
  - after a Yahoo rate limit each remaining ticker backed off again (5 + 10 + 20 s) before failing;
  - the button gave no sign of progress.
- **Decision:**
  - A ticker with no open position is needed only up to its last close or cash event (a dividend after the sale counts). Once that range is cached, no request is sent for it. The 5-day correction window applies only while the range still grows.
  - When Yahoo gives up on a ticker with a rate limit, the remaining tickers of that run are skipped with an error ("try again later") instead of each waiting 35 s.
  - `update_market` takes a `progress` callback; the button on "Dane rynkowe" shows a progress bar (Yahoo ticker by ticker, then NBP, then GUS).
  - Not done: parallel Yahoo requests and the NBP whole-table endpoint. Tables are 0.3 s and 130 kB each against 0.17 s per currency, so they pay off only from three currencies, and only on the first fetch.
- **Consequences:** a later update costs about 1 s plus 0.1-0.2 s per ticker still held, plus 0.2 s per currency (GUS once a day). Prices of a sold instrument are not refreshed after the sale, so a later split of it is not re-read; nothing values it after the sale.

### D-043 Sales, withdrawals and sub-account transfers in Cash Operations
- **Date:** 2026-11-17 · **Status:** Accepted
- **Context:** importing a real EUR export failed: `unknown cash operation types ['Stock sell', 'Subaccount transfer', 'Withdrawal']`. The file was rejected as a whole.
- **Decision:**
  - `Stock sell` is a sale (`SELL`), paired with closed positions by the same rules as purchases (D-032). The mock export now uses this label instead of the guessed `Stock sale`, so `CASH_TYPES_ASSUMED` is empty.
  - `Withdrawal` is an external outflow (`WITHDRAWAL`).
  - `Subaccount transfer` moves money between the user's own XTB accounts. It becomes `DEPOSIT` or `WITHDRAWAL` by its sign, so every account keeps correct flows for its own TWR. At portfolio level both sides cancel once both accounts are imported; the remainder is the currency conversion. The export's own label stays in `broker_type`.
  - `PARSER_VERSION` 12.
- **Consequences:** the comment formats of these types are still unconfirmed (Q-006). If only one side of a transfer is imported, the portfolio sees it as a real deposit or withdrawal until the other account is imported.

### D-044 Import a folder or the zip xStation saves
- **Date:** 2026-11-17 · **Status:** Accepted
- **Context:** the user wants to point at a folder, or better at the zip xStation produces, instead of picking files one by one.
- **Decision:**
  - `import_xtb` accepts a folder, a `.zip` or a single `.xlsx`; a folder may contain zips. The zip is read in memory and never extracted to disk; `__MACOSX`, `._*` and `~$*` entries are ignored, and an entry over 100 MB is refused.
  - "Importy": two pickers side by side at the top, feeding one "Importuj" button: "Folder eksportu" (the default, a folder picker: `.xlsx` and `.zip` inside it, subfolders included) and "Pojedyncze pliki" (`.zip` or `.xlsx`). A browser's file dialog picks either a folder or files, never both at once, hence two pickers. `fa import xtb` takes a folder, a zip or a file path. The inbox folder (D-028) picks up zips too.
  - A broken zip is reported and skipped; the other files are still imported.
- **Consequences:** the inbox reads every zip in the folder once a minute; exports are small, so this stays cheap.

### D-045 Transfers, IKE/IKZE deposits and the SEC fee
- **Date:** 2026-11-17 · **Status:** Accepted
- **Context:** the next real exports failed on `Transfer`, `IKE deposit`, `IKZE deposit` and `SEC fee`.
- **Decision:**
  - `Transfer`, `IKE deposit` and `IKZE deposit` follow the D-043 rule for `Subaccount transfer`: `DEPOSIT` when positive, `WITHDRAWAL` when negative. A payment into IKE/IKZE is then a deposit of that account, and if the same money leaves another imported XTB account, the two cancel at portfolio level.
  - `SEC fee` (the US regulatory fee on sales of US shares) is a `FEE`: it lowers cash and returns, it is not an external flow.
  - `PARSER_VERSION` 13. Unknown types still reject the file (D-007).
- **Consequences:** an `IKE deposit` funded from a bank account outside XTB is a real deposit, as it should be.

### D-046 A symbol Yahoo has no history for is reported once, in Polish
- **Date:** 2026-11-17 · **Status:** Accepted
- **Context:** a share sold years ago has no Yahoo history for its holding period (the company left the exchange and the symbol now belongs to another one). The update showed a raw English message (`no prices between …`) and asked Yahoo again on every run. Two Warsaw-listed ETFs had XTB symbols that Yahoo knows under different names.
- **Decision:**
  - An empty Yahoo answer for a ticker with no cached prices gives a Polish message that names the period, says the position is valued at purchase cost on those days (the existing fallback in `valuation.py`), and points to `config/yahoo_tickers.yaml`. It starts with the D-039 prefix, so the ticker is not asked again for 7 days.
  - Symbols that differ between XTB and Yahoo stay in the user's own `config/yahoo_tickers.yaml` (D-039), not in the code.
- **Consequences:** a delisted holding shows flat at cost between purchase and sale; its result appears on the sale day.

### D-047 "Maks. pod wodą" on Portfel; asset class first
- **Date:** 2026-11-17 · **Status:** Accepted; the tile's measure superseded by D-049
- **Context:** the user wants the portfolio's deepest fall on the start page, and the asset-class breakdown first and selected by default.
- **Decision:**
  - A fifth KPI tile "Maks. pod wodą": the maximum drawdown in the selected period, on the TWR index (as on "Zwroty", D-022), so deposits do not hide a fall. The delta shows the peak and trough months; the help adds the exact dates, whether it was recovered and today's distance from the peak. "Pełny wykres" opens the daily drawdown curve.
  - Five tiles fit at common desktop widths once the value tile's delta drops "w okresie" (the help already says it is for the period). The KPI row may hold up to five tiles.
  - The breakdown control lists "Klasa aktywów" first, and it is the default.
- **Consequences:** the tile and "Największy spadek" on "Zwroty" agree for the same period.

### D-048 Orders filled in parts: a position's cost is the sum of its purchases
- **Date:** 2026-11-17 · **Status:** Accepted
- **Context:** an account showed an absurd position result (hundreds of thousands of percent) and a strongly negative TWR on its first day. A masked diagnosis (counts and ratios only) showed more purchases than positions: XTB fills an order for fractional shares in parts (the whole shares and the fraction), with comments `OPEN BUY <part>/<order> @ <price>` and no ticker. The parts may share the position's ID or carry another one. The sync paired one purchase per position, so a position's cost was often just its fraction; with no price on a day, the value at cost was too low as well.
- **Decision:**
  - The comment format is `OPEN BUY [<ticker>] <volume>[/<order volume>] @ <price>`; the ticker is optional.
  - Purchases and sales are grouped per position: all operations with the position's ID, then each remaining part by account, ticker, order volume equal to the position's volume and time within 10 minutes, while the parts' volumes still fit the position. The purchase value is the sum of the parts.
  - A position whose paired parts do not add up to its volume gets an import warning.
  - `PARSER_VERSION` 14: `fa rebuild` recomputes all positions.
- **Consequences:** position results, cost-based values and the account's TWR use the full cost. Q-006 (c) gains a confirmed purchase comment format.

### D-049 "Maks. pod wodą" means below the money put in
- **Date:** 2026-11-17 · **Status:** Accepted (supersedes the tile's measure in D-047)
- **Context:** the user meant "pod wodą" as being below the deposits, not a fall from a peak: "if I deposited 1000 PLN, have 1200 today and had 800 at the lowest, I want to see -20 %". The peak-to-trough drawdown (D-022) stays on "Zwroty" as "Największy spadek".
- **Decision:**
  - `portfolio.returns.underwater(values, contributed, start)`: daily `(value - deposits) / deposits`, with deposits = running deposits minus withdrawals in PLN (the same as "Wpłacony kapitał"), and its minimum from the period's start. Days before the first deposit are left out.
  - The tile shows that minimum; the delta gives the amount below the deposits and the month, or "nigdy poniżej wpłat" when the minimum is positive. The help adds the date and today's ratio. "Pełny wykres" opens the daily ratio.
- **Consequences:** a new deposit raises the bar at once, so the ratio drops on the deposit day only if the value does not follow; with deposits counted at face value, inflation is not included (D-041 has the real view).

### D-050 "Zysk względem wpłat" tile; Portfel KPIs in two rows of three
- **Date:** 2026-11-17 · **Status:** Accepted
- **Context:** the user wants today's `(value - deposits) / deposits` (the "Dziś" figure from the "Maks. pod wodą" help) as a tile of its own. Six tiles do not fit one row.
- **Decision:**
  - New tile "Zysk względem wpłat": today's ratio from `underwater()` (D-049); the delta is the same after inflation (`real_profit().pct`, D-041). "Pełny wykres" opens the daily ratio.
  - The Portfel KPIs are two rows of three: value, period result, deposits; then total profit, profit vs deposits, maximum under water. The UI guideline allows up to five tiles per row; two rows are the way to show more.
- **Consequences:** "Maks. pod wodą" and the new tile share one series, so the lowest point and today's value are read off the same curve.

### D-051 A close made only for a stock split runs on until the real sale
- **Date:** 2026-11-17 · **Status:** Accepted; applies only when the reopened position is missing (D-056)
- **Context:** a masked diagnosis of a stock split showed how XTB books it: the old position is closed on the split day at its own open price, with no sale in Cash Operations, and the shares are reopened as a new position. When the reopened position is missing from the exports (here it was sold later), the shares vanished from the valuation until the sale (the holding's value collapsed overnight), and their later sale had no position to pair with.
- **Decision:**
  - In the sync, a closed position with close price equal to its open price, sale value equal to its purchase value (or none) and no paired sale is a technical split close.
  - It is moved to the first later day with sales of the same ticker on the same account that no position claims; those sales are its sale value and their comment gives the close price. The valuation keeps the old lot, split-adjusted (Q-001 rule), until then.
  - Without such sales the close stays and an import warning says the reopened position is missing.
  - A sale at exactly the purchase price that has its own cash operation is not touched. `PARSER_VERSION` 15.
- **Consequences:** the portfolio value, TWR and "Maks. pod wodą" no longer drop at a split. If the reopened position is in the exports, nothing changes: its own sale pairs with it.

### D-052 Days without a market price use the user's own trade prices
- **Date:** 2026-11-17 · **Status:** Accepted (refines the cost fallback of D-019 and D-046)
- **Context:** Yahoo has no history for a delisted share whose symbol now belongs to another company, so the position sat at purchase cost until the sale day.
- **Decision:** on days without a market price, a lot is priced from its own trades: the open price on the opening day, the close price on the closing day (both per today's share), a straight line between them and the last one carried on, in the instrument currency at that day's NBP rate. The currency comes from Yahoo or, for an unknown ticker, from the XTB suffix (`.US` USD, `.DE` EUR, `.PL` PLN, ...). Only when that is impossible the old fallback (purchase cost in the account currency) applies. The warning on "Portfel" says which method was used.
- **Consequences:** a delisted holding moves gradually from its buy to its sale price instead of jumping on the sale day. The path in between is an estimate; the real one (e.g. a short spike) is not known without market data.

### D-053 Saved balances are edited in the table; sparklines are never grey
- **Date:** 2026-11-17 · **Status:** Accepted
- **Context:** the user wants to edit bank balances like a spreadsheet (click a cell, type, save) instead of picking a row and filling a form. Grey sparklines on neutral KPI tiles looked dull.
- **Decision:**
  - "Gotówka" shows the saved balances as `st.data_editor`: account (from the bank accounts), date, balance and note are editable in place; rows can be added and deleted. "Zapisz zmiany" checks the whole table (`cash.check_table`: account, date not in the future, a number, one balance per account and day) and, only if every row is fine, rewrites `cash_balances.csv` (`cash.write_snapshots`, oldest first, the file's separator kept). "Cofnij zmiany" restores the table.
  - When the file has rows that do not parse, the table is read-only, so saving cannot drop them silently.
  - Sparklines of neutral tiles use the first palette colour instead of grey. "Maks. pod wodą" fills from the zero line: red below it, green above it.
- **Consequences:** the add form stays for a quick new balance; the row-by-row edit form is gone.

### D-054 The positions table's 90-day sparkline shows the result
- **Date:** 2026-11-17 · **Status:** Accepted
- **Context:** the "90 dni" sparkline in "Bieżące pozycje" showed the position's value, so every purchase bent it upwards.
- **Decision:** it shows the result instead: daily value minus the cost of the lots held that day (cost added on the opening day, removed on the closing day, in PLN at the opening day's rate as in the "Koszt" column). A lot without a known cost counts as zero cost.
- **Consequences:** buying more no longer moves the line; selling at a profit lowers it by the realised part, which leaves the position.

### D-055 One tile for profit vs deposits, with its lowest point
- **Date:** 2026-11-17 · **Status:** Accepted (supersedes the separate "Maks. pod wodą" tile of D-049 and the two-row layout of D-050)
- **Context:** "Zysk względem wpłat" and "Maks. pod wodą" were two points (today and the lowest) of one curve, `(value - deposits) / deposits`, with the same full chart.
- **Decision:** a single tile "Zysk do wpłat": today's ratio as the value, "min. X% (MM.YYYY)" as the delta, the inflation-adjusted ratio and the exact lowest date in the help, the zero-line (water) sparkline, and the daily curve under "Pełny wykres". The Portfel KPIs are back to one row of five.
- **Consequences:** `underwater()` (D-049) is unchanged; the peak-to-trough drawdown stays on "Zwroty".

### D-056 A position listed open after its close is still open
- **Date:** 2026-11-17 · **Status:** Accepted (narrows D-051)
- **Context:** an export lists a position opened before a stock split under Open Positions, while the app showed it closed. XTB keeps a position's ID across a stock split: the same ID is in Closed Positions (the technical close on the split day) and in Open Positions (the shares in post-split units, still dated 2022). The sync always let the closed record win, so the shares disappeared. D-051 then wrongly assumed the reopened position was missing from the exports.
- **Decision:**
  - Open and closed records are merged per position ID after all files are read (`_merge_open_and_closed`). The newest export listing it open wins among open records.
  - If an export that ends on or after the close date still lists the position open, it is open: a technical (split) close is dropped; after any other close (a partial sale) the closed record stays as the sold part and the open record becomes a separate lot `<ID>/rest`.
  - An open record from an export that ended before the close is out of date and ignored.
  - D-051 still applies to a technical close with no open record. `PARSER_VERSION` 16.
- **Consequences:** split positions keep their history from the original purchase date. Online refresh: a fetch during a full app run (e.g. a click) no longer triggers a second rerun; only the fragment's own timer run reloads the page (`app/main.py`).

### D-057 Tables filter while you type
- **Date:** 2026-11-17 · **Status:** Accepted
- **Context:** the user wants a table search that keeps only matching rows as they type ("am" -> AMD). Streamlit's own table search only highlights, and `st.text_input` sends its value on Enter or blur.
- **Decision:**
  - `table(..., search=key)` adds a search field above the table; rows stay when any text column contains the text, ignoring case (`filter_rows`). Used on "Bieżące pozycje" and on the three tables of "Importy".
  - The field is a small inline Streamlit v2 component (`app/ui/live_search.py`): plain HTML, CSS and JS in the app, styled with the theme's CSS variables, sending the text 250 ms after the last keystroke. No package, no CDN, no network (D-011).
- **Consequences:** each pause in typing reruns the page once; the field keeps its focus and text across reruns.

### D-058 One "Po inflacji" switch for the whole Portfel page; no "Zysk całkowity" tile
- **Date:** 2026-11-17 · **Status:** Accepted (supersedes the Portfel parts of D-041: the "realnie" delta on "Zysk całkowity" and the chart's own "W dzisiejszych złotych" switch)
- **Context:** with the "Maks." period, "Wynik w okresie" and "Zysk całkowity" show the same number by definition. The user does not need the latter and wants one switch that shows everything it can after inflation.
- **Decision:**
  - The "Zysk całkowity" tile is gone; Portfel has four tiles.
  - A "Po inflacji" switch next to "Okres" restates every amount on the page in the złoty of the last day: daily values, deposits and withdrawals, and each lot's cost, each times `level(last day) / level(its day)` from the GUS CPI (D-025, unpublished months extrapolated as in D-041). The page's formulas stay as they are; only their inputs change, so the result, TWR (then real TWR), deposits, profit vs deposits with its lowest point, the value and composition charts and the positions' cost and result are all real.
  - Without saved CPI the switch is disabled with a hint to "Dane rynkowe".
- **Consequences:** today's value and the allocation do not change (today's złoty are today's złoty). Other pages keep their own real figures ("Zwroty", "Obligacje").

### D-059 "Wynik na walutach" tile: what foreign holdings earned or lost on exchange rates
- **Date:** 2026-11-17 · **Status:** Accepted
- **Context:** the user holds positions in foreign currencies and wants to know whether, overall, the exchange rates put them ahead or behind, using the daily rate and the rate of the purchase day.
- **Decision:**
  - `attribution.fx_pnl(v)`: the daily currency gain in PLN per currency, from the D-023 attribution: what was held overnight, valued in its own currency, times the change of the NBP rate; shares, ETFs and foreign cash (broker and bank) together. Summed from a purchase to today it equals "today's rate vs the purchase day's rate"; after a sale the realised part stays.
  - Portfel tile "Wynik na walutach" (after "Wynik w okresie"): the sum over the selected period; the delta names the currency that mattered most, the help lists every currency; the water sparkline and "Pełny wykres" show the running total. With "Po inflacji" each day's amount is restated in today's złoty like everything else (D-058).
- **Consequences:** five tiles in the row again. The share of the period result due to prices vs currencies stays on "Zwroty" (D-023).

### D-060 Switches never move the page; a floating "Przeliczam…" pill while it recalculates
- **Date:** 2026-11-17 · **Status:** Accepted
- **Context:** flipping "Po inflacji" made the page jump. The recalculation itself takes a fraction of a second; the jump came from a note line that appeared only with the switch on (and later a caption that wrapped to a second line), plus Streamlit fading the page during the rerun.
- **Decision:**
  - Nothing appears or disappears with a switch: notes that depend on it go into its help ("?") or into text that is always there and keeps its length.
  - App-wide CSS (`ui/components.py`): while Streamlit runs the script (`data-test-script-state="running"`), a small dark pill with a spinner and "Przeliczam…" floats at the top centre, over the content. It fades in only after 0.4 s, so quick reruns (live search, the 30-second background check) do not flash it.
- **Consequences:** checked in the browser: section headings keep the same position with the switch off and on.

### D-061 Cost of the rest after a partial sale; two coloured currency badges
- **Date:** 2026-11-17 · **Status:** Accepted
- **Context:** a position showed "+∞" in "Wynik %". A masked check (yes/no facts only) showed the open lot was the rest after a partial sale (D-056): XTB keeps the ID, so the purchase paired with the sold part and the rest had no cost; pandas then summed the unknown cost as 0.
- **Decision:**
  - The rest's cost is all purchases of the position minus the sold part's purchase value (Closed Positions); without it, the purchases are split by volume. `PARSER_VERSION` 17.
  - In "Bieżące pozycje" an all-unknown cost stays unknown (`sum(min_count=1)`), and a cost of zero or less shows the result % as "–", never ±∞.
  - KPI tiles can carry several small badges instead of the one delta (`Kpi.badges`), each green or red by its own sign; "Wynik na walutach" shows its two biggest currencies this way.
- **Consequences:** none for positions without partial sales.

### D-062 Capital below a grosz is rounding noise
- **Date:** 2026-11-17 · **Status:** Accepted
- **Context:** with "Po inflacji" the TWR showed −100 % and profit vs deposits a minimum of −100 %. A masked re-run of the page maths found it on the first day: value 0 and same-day flows that cancel exactly; nominally they summed to 0 (or a hair below), so the day was skipped, but times the inflation factor the rounding left a positive 1e-13, and a zero value on that "capital" gave a −100 % day that zeroed the whole index.
- **Decision:** `daily_returns` treats capital at risk below 0.01 PLN as none (no return that day), and `underwater` ignores days with deposits below 1 PLN.
- **Consequences:** real and nominal TWR agree in shape; amounts that small never come from real money.

### D-063 "Dzisiaj" tile: the result since the previous session's close
- **Date:** 2026-11-17 · **Status:** Accepted; the grey date badge removed by D-067, which also adds counting by US sessions as an option (midnight stays the default)
- **Context:** the user wants today's gain or loss on Portfel, both as a percentage and as an amount: the percentage as the tile's number, the amount on a badge.
- **Decision:**
  - The day is the last market day: `valuation.market_days(v)` lists the days on which some price or exchange rate moved (sessions, and today with live quotes). Weekends, holidays and days whose quotes are not fetched yet carry the previous values and are skipped, so the tile shows the last session instead of a false +0,00 %; a grey badge "sesja dd.mm" names it when it is not today. A portfolio without prices or foreign currencies uses the last day.
  - `returns.change_since(values, flows, base)`: from the close of the day before that session to now. The amount is the value change minus deposits plus withdrawals (as "Wynik w okresie"); the percentage chains the daily TWR, so a deposit is not a gain.
  - Tile "Dzisiaj" (second, after "Wartość portfela"): the percentage with two decimals, the amount as a green or red badge (D-061); the water sparkline shows each session's return over the last month, "Pełny wykres" all sessions. It does not follow the period filter. With "Po inflacji" the amount is in today's złoty.
  - Six tiles in the row. Each tile is a CSS size container and its value shrinks with the tile (never below 1 rem) instead of losing digits to an ellipsis; at about 1280 px with the sidebar open the values are smaller, from about 1600 px they are full size.
- **Consequences:** none for other pages beyond the shrinking values, which only apply to tiles too narrow for them.

### D-064 Versioning and releases; first release 0.9.0
- **Date:** 2026-11-18 · **Status:** Accepted; "no wheel attached" superseded by D-065
- **Context:** the core scope works end to end and the user wants a first GitHub release, numbered 0.9 rather than 1.0.
- **Decision:**
  - Versions follow Semantic Versioning. The only place the version is written is `__version__` in `src/finance_analytics/__init__.py`; `pyproject.toml` reads it (`dynamic = ["version"]`), and `fa --version` shows it.
  - A release is an annotated tag `vX.Y.Z` on `main` and a GitHub release of that tag. Its notes are the version's section of `CHANGELOG.md` (Keep a Changelog), plus install instructions.
  - No wheel or other build is attached: the UI runs from the checkout (`app/` is not part of the package), so the app is installed from source with `pip install -e .`. GitHub's source archives are the only assets.
  - Before tagging: `pytest`, `ruff check .`, `python scripts/check_no_private_data.py --all`, the shipped bond data checked for new series and official rates (D-026), the README and `CHANGELOG.md` updated.
  - 0.9.0 (2026-11-18) is the first release. It is not marked as a pre-release: the 0.x number already says the app may still change.
- **Consequences:** changes from now on are noted in `CHANGELOG.md` under an `Unreleased` heading until the next release.

### D-065 An installable package: the UI ships inside it, data in a per-user folder
- **Date:** 2026-11-18 · **Status:** Accepted (supersedes the "no wheel" point of D-064)
- **Context:** 0.9.0 ran only from a checkout. The UI (`app/`) sat outside the package, `fa ui` started Streamlit in the repository root to pick up `.streamlit/config.toml`, and the data folder was `./data` relative to the working directory. The user wants anyone to install a chosen version without git, and asked for the option of a wheel installed with uv over a Windows `.exe` installer (bundled Python of several hundred MB, unsigned-binary warnings, a Windows build per release).
- **Decision:**
  - **UI inside the package:** `app/` moves to `src/finance_analytics/app/`, with its `.streamlit/config.toml`. It stays a folder of Streamlit scripts whose modules import each other as `ui.*`, so its files are listed in `[tool.setuptools.package-data]`; `tests/test_packaging.py` fails if a file is not covered. Streamlit may be imported only inside `app/` (a test), so the business logic stays free of UI code (D-012).
  - **`fa ui`** runs Streamlit with the app folder as the working directory, so its config (theme, the privacy settings of D-011) applies wherever the package is installed; the privacy flags stay on the command line as well.
  - **Data directory** (`config.py`), in order:
    1. `FA_DATA_DIR`;
    2. in a source checkout (`src/` layout with `pyproject.toml` next to it): `data/` in the repository, now fixed to the repository root instead of the working directory, and `data-demo/` for the demo;
    3. otherwise a per-user folder: `%LOCALAPPDATA%\finance-analytics\data` on Windows, `~/Library/Application Support/finance-analytics/data` on macOS, `$XDG_DATA_HOME` (if absolute) or `~/.local/share` + `finance-analytics/data` elsewhere, with `demo` next to `data`.

    Not Documents: on Windows it is often synced to OneDrive, which would copy financial data to the cloud (R-015). `fa init` and `fa ui` print the folder in use.
  - `fa init` enables the git hook only in a source checkout.
  - **Releases:** the wheel (`python -m pip wheel . --no-deps -w dist`) is attached to the GitHub release. Users install it with `uv tool install <wheel>`, which fetches a suitable Python if none is installed; installing a newer wheel the same way replaces the old version. `uv tool install "git+https://github.com/MaciejWanat/finance-analytics@vX.Y.Z"` is the alternative for users with git. Not published on PyPI: the repository is private, and publishing would be its own decision.
  - Released as 0.10.0.
- **Consequences:**
  - An installed release and a source checkout use different data folders by default; `FA_DATA_DIR` points both at one.
  - A running `fa ui` from a checkout must be restarted after this change, because the UI files moved.
  - Checked by hand before the release, in a clean temporary environment: the wheel contains all 20 UI files; `uv tool install` of the wheel works; `fa init` and `fa demo` write only to the per-user folder, never to the working directory; `fa ui` serves every page with the packaged theme; installing 0.10.0 over an older wheel replaces it.

### D-066 Time to the US market open in the sidebar
- **Date:** 2026-11-18 · **Status:** Accepted; the single US line and its "only with US holdings" rule superseded by D-068
- **Context:** the user wants to see how long it is until the US stock market opens. A seventh tile on Portfel was considered and rejected: the row already holds six portfolio results, a clock is not one of them, and the page redraws only on a click or new data, so a countdown on it would stand still (always offline).
- **Decision:**
  - One caption line in the sidebar, under the Online/Offline badge, on every page. Its own fragment reruns every 30 s, so the minutes stay current without reloading the page.
  - Text: "Giełda USA: otwarcie za 2 h 14 min" when the open is later today (local date); "otwarcie jutro 15:30" or "otwarcie pon. 15:30" when it is on a later day; "sesja trwa, koniec za 3 h 5 min" during the session. Durations are rounded up to a whole minute. The "?" tooltip (`G["us_session"]`) gives the hours in New York and in Poland.
  - Shown only when an open position is in a US-listed instrument (XTB symbol `*.US`, `reports.holds_us_listed`).
  - `market/hours.py` computes the session from rules, with no data and no network, so it works offline (R-015): 9:30-16:00 in `America/New_York`; the NYSE holidays (Saturday holidays on the Friday before, Sunday ones on the Monday after, except New Year's Day on a Saturday); early close at 13:00 on 3 July (Monday to Thursday), the day after Thanksgiving and 24 December. Zoneinfo covers the weeks when US and European daylight-saving time differ, when the open is at 14:30 in Poland. The Easter helper of the bonds module (`easter_sunday`) is shared for Good Friday.
- **Consequences:** unscheduled closures (a national day of mourning, a storm) are not known in advance, so on such a day the clock counts down to an open that does not happen. No new dependency: `tzdata`, which Windows needs for zoneinfo, comes with pandas.

### D-067 "Dzisiaj" can count US sessions; a setting, midnight by default
- **Date:** 2026-11-18 · **Status:** Accepted (extends D-063)
- **Context:** the biggest moves of the user's portfolio happen between the US open and close. Counted from midnight (D-063), the tile drops the evening's session result at 0:00 and spends the morning on small currency moves. The user asked for a tile that resets with the session, with the old way kept as an option; after trying both, they chose midnight as the default.
- **Decision:**
  - Preference `today_tile` in `settings.yaml`: `calendar_day` (default, D-063) or `us_session`; on Ustawienia, section "Kafelek „Dzisiaj”", options "Od północy" and "Sesjami giełdy w USA", saved with the other settings.
  - **US session:** every calendar day counts towards the US trading day on or after it (`hours.session_of`), so moves between two sessions (currencies, European exchanges, a weekend or a US holiday) go to the next session. The tile shows the session that opened last (`hours.last_opened_session`): from the open (usually 15:30) it is today's; before the open it is the previous one, whose result therefore stays after the close until the next open. Its result runs from the close of the previous trading day to the close of that session, or to now (`returns.change_since` with an `end`). As before, a session without any moved quote is skipped.
  - The sparkline and "Pełny wykres" show the chained TWR of each session (`returns.chained_returns`); the tooltip and the chart note say which way the day is counted.
  - US sessions apply only when an open position is in a US-listed instrument (`reports.holds_us_listed`, as the clock of D-066); otherwise the tile counts from midnight whatever the setting.
  - The logic lives in `portfolio/today.py` (`today_result`), a pure function of the values, flows, market days and the time.
  - No grey date badge "sesja dd.mm" (D-063) any more, in either mode: the user found it noisy. When the tile shows an earlier day than today, its tooltip says which ("Teraz widać sesję z 17.11.2026.").
  - In online mode the daily market update also runs 15 minutes after each US close (`auto.daily_update_due`), so the session's final closing prices are saved and the tile shows the right result after midnight, when the session is no longer "today" and is valued from daily closes rather than live quotes.
- **Consequences:**
  - The page recalculates only when it reruns: online, the live refresh after the open does that; offline, the tile switches to the new session on the next click or reload.
  - One more automatic update per US trading day in online mode; offline nothing changes (R-016).

### D-068 Four exchanges in the sidebar, with US pre-market and post-market
- **Date:** 2026-11-18 · **Status:** Accepted (supersedes the single US line of D-066)
- **Context:** the user wants London, Germany and Warsaw next to the US in the sidebar clock, and the US pre-market and post-market shown too.
- **Decision:**
  - The sidebar block "Giełdy" lists, in this order, USA, Londyn, Niemcy, Warszawa, always (no longer only with US holdings). Its title is a caption on its own line, so the "?" tooltip (`G["markets"]`, the hours in Polish time) sits right beside it; below, a grid in four aligned columns (`components.status_list`): a status lamp, the name, a muted italic label and the time right-aligned with tabular digits.
    - The lamp shows the current state by colour and by shape, so colour is never the only signal: full green (open), empty grey ring (closed), amber with the left half filled (pre-market, before the open) or the right half (post-market, after the close).
    - The label and the time count to the regular session only: "do zamknięcia" while open (the regular close), otherwise "do otwarcia" (the next regular open), also during the US pre-market and post-market. Those extended sessions show only in the lamp and the hover. The user wants the real open, not the start of the pre-market.
    - The time is always a countdown: "45 min", "5 h 05 min" (two-digit minutes keep the column aligned), and "2 d 15 h" from a day on (a weekend). Hovering a row names the state and the exact moments: "Zamknięta · pre-market dziś 10:00 · otwarcie dziś 15:30", "Pre-market · otwarcie dziś 15:30", "Post-market do 02:00 · otwarcie dziś 15:30".
  - `market/hours.py`: an `Exchange` (time zone, open, closing time per day, holiday calendar, optional extended hours) with `status(now)` returning the phase, the next regular open and the end of the current phase; `EXCHANGES` holds the four.
    - USA: 9:30-16:00 New York, pre-market from 4:00, post-market until 20:00 (until 17:00 on early-close days); NYSE holidays as in D-066.
    - London (LSE): 8:00-16:30 London, 12:30 on 24 and 31 December; bank holidays of England, a weekend one moved to the next weekday.
    - Germany: Xetra (Frankfurt), 9:00-17:30 Berlin, the main German market and the one Yahoo's `.DE` prices come from; closed on 1 January, Good Friday, Easter Monday, 1 May, 24-26 and 31 December. The user said "Berlin"; Börse Berlin is a small regional exchange (open 8:00-22:00), so Xetra is the useful clock.
    - Warsaw (GPW): 9:00-17:00 (continuous trading until 16:50, then the closing auction); closed on Polish public holidays (`bonds.polish_holidays`), Good Friday, 24 and 31 December.
  - Pre-market and post-market only for the US: the European exchanges have only opening and closing auctions of a few minutes, not extended sessions.
- **Consequences:** special one-off closures and changed hours (a royal funeral, a jubilee holiday) are not in the rules.

### D-069 Live prices every few seconds: polling or a stream, in a background feed
- **Date:** 2026-11-18 · **Status:** Accepted (supersedes the live-price part of D-021)
- **Context:** the user wants prices to move like in a stock app, e.g. every 5 seconds, and to choose in the settings between polling at an interval and a streaming connection, with a slowly blinking lamp showing that the app is live. US pre-market and post-market prices should count too. D-021 polled every 1-60 minutes from a sidebar fragment, one request per ticker in turn, and reran the whole app on new data; it rejected the stream as unnecessary.
- **Decision:**
  - **Preferences:** `live_source: poll | stream` (default `poll`) and one interval per source, each with its own range: `poll_seconds` (120-3600, default 300: never more often than every 2 minutes, so Yahoo does not refuse) and `stream_seconds` (5-60, default 5: how often Portfel redraws with the streamed prices). They replace `refresh_minutes`; an older file's `refresh_minutes` (or the short-lived `refresh_seconds`) becomes `poll_seconds`, raised to 2 minutes if lower. `fa settings --live poll|stream --refresh 2m|5s` sets the interval of the chosen source and checks its range (a bare number still means minutes). On Ustawienia, section "Ceny na żywo": "Odpytywanie" with "Co ile pobierać ceny" (2 min to 1 h) or "Strumień" with "Co ile odświeżać stronę" (5 to 60 s).
  - **Background feed** (`market/feed.py`, one per data directory and process): its own thread, so the network never delays a page; it writes `live_quotes`, pages only read. It runs only online (checked on every wake-up and before every connection) and only while a page is viewed: the sidebar calls `touch()` every 5 s, and after 2 minutes without it the thread ends and closes the connection.
    - **Polling:** every `poll_seconds` while some exchange is in session (US pre-market and post-market included, `hours.EXCHANGES`), at most every 5 minutes while only currencies trade (Sunday 22:00 to Friday 22:00 UTC), not at all otherwise. One request per ticker, four in parallel: the last hour of minute bars with `prepost=True`, so its last trade is the price, extended hours included. After a Yahoo rate limit it waits 2 minutes.
    - **Stream:** Yahoo's streaming service through yfinance's `WebSocket`, subscribed to the held tickers and FX pairs (`USDPLN=X`); ticks are saved at most once a second. After a drop it reconnects after 5 s, then 10, 20, 40 and 60 s. Every 5 minutes it follows the holdings (new subscriptions) and polls the tickers the stream has said nothing about for 5 minutes while some market trades. A streamed price without a currency is checked against the last close: London quotes may come in pence without "GBp", so a price about 100 times above it is divided.
  - **Today's quotes only:** a live quote counts only on the local date it arrived (`live.read_live`), instead of for 12 hours. Yesterday evening's post-market prices do not move the new day, which starts from the daily closes; the user accepted that a session's result can jump at midnight when the post-market prices give way to the official close.
  - **Pages:** on Portfel, the KPI tiles with the value chart and the positions table are live fragments (`st.fragment(run_every=...)`, online only: every `stream_seconds` with the stream, every 30 s while polling, so a new poll shows within half a minute): they redraw with the newest quotes without rerunning the rest of the page. A fragment that finds a new day reruns the whole page. Zwroty and Dywidendy rerun at most once a minute for new quotes; other pages do not. The valuation cache keeps the 6 latest entries, since live quotes change its key every few seconds. Charts keep their zoom across redraws (`uirevision`), and an open "Pełny wykres" dialog is drawn again with the new data instead of closing.
  - **"Przeliczam…" pill (D-060):** only in a full run, so it does not flash with every live redraw. The CSS keys on a marker drawn last in every full run (`components.run_end_marker`), which stays stale until the whole script has run.
  - **Sidebar line:** a lamp by "Online": green and slowly pulsing while the stream is connected (2.4 s; the phase follows the clock so redraws do not restart it; no animation with `prefers-reduced-motion`), steady green when polling, an amber ring while connecting, red on an error (it retries), a grey ring when every market is closed. With the stream the text is only the state ("na żywo"), without the time of the last price, which would change every second; the user asked for it to go. Polling shows the time of the last prices ("ceny z 12:34"). The hover explains the lamp and gives the last error. Likewise on Portfel the stream says "na żywo" without a time.
- **Consequences:**
  - More requests in online mode, but polling stays at every 2 minutes or less often, so Yahoo's limits are not reached; for prices every few seconds the stream is the way. Still only tickers and currency codes are sent (R-009).
  - Offline nothing changes: the feed never starts and no socket opens (tested).

### D-070 "1D" range: the day of the "Dzisiaj" tile, every 5 minutes
- **Date:** 2026-11-18 · **Status:** Accepted
- **Context:** the user wants a one-day period on every chart, like the "1D" of a stock app: today's movement within the day, live. Until now every chart had daily data only (session closes); composition and sparklines were weekly or monthly.
- **Decision:**
  - **Data:** migration 0010, table `intraday_quotes (ticker, ts, price)`, part of the market cache (cleared by `fa reset --market`, kept 10 days). Two sources: 5-minute bars from Yahoo for the held tickers and FX pairs over the last 5 days, pre-market and post-market included (`market/intraday.py`; the last bar of the previous session gives the price before an open), and every live quote (`live.store_quotes`), at most one per ticker and minute, so the line reaches "now". Online, the live feed (D-069) fetches the bars when it starts and every 15 minutes while some market or currencies trade. Offline, nothing is fetched on its own: the 1D view on Portfel offers "Pobierz notowania z dziś", an explicit request (D-031).
  - **Valuation** (`portfolio/intraday.py`, pure): the day's rows of the daily valuation, each moved by its instrument's price and its currency's rate relative to the end of the window: `value(t) = value at the end x price(t) / price(end) x rate(t) / rate(end)`. So the last point is the daily valuation, and the "Dzisiaj" tile, to the grosz. Before an exchange opens its instruments stay at the last price before; bonds and PLN cash stay flat; foreign cash moves with the rate. An instrument without intraday quotes stays flat and is named in the chart's caption. Simplification: the holdings at the end of the day apply all day, so a trade during the day makes no jump.
  - **Window:** the day of the "Dzisiaj" tile (`ui.data.one_day`): from midnight to midnight, or with "Sesjami giełdy w USA" (D-067) from the previous session's close to the end of the session's calendar day. The x-axis runs over the whole window, so the line grows to the right while the day lasts.
  - **"1D" in the period filter** (`RANGES`) of Portfel, Zwroty and Dywidendy. The daily figures (KPI values, TWR, attribution numbers, tables) are measured from the tile's base close (`period_start(..., day_base=)`), so they agree with "Dzisiaj"; the curves come from the 5-minute values:
    - Portfel: "Wartość portfela" as `charts.intraday_chart` (2px line, 10% wash down to the lowest point instead of zero, a dashed line at the previous close named in ink, hours on the axis, hover with the change since that close); sparklines every 15 minutes; "Wynik na walutach" from the rates alone at market rates; "Skład portfela" as hourly bars; "Pełny wykres" with hours and without the slider and range buttons.
    - Zwroty: TWR of the portfolio and of each account over its base close, the largest fall and the fall from the peak within the day (with hours), and the price / currency split since the start of the day at market rates (the numbers above it stay from the base close at NBP rates; the caption says so). "Po inflacji" shows a one-line note instead: a day's inflation is negligible.
    - Dywidendy: payments on that day; a period without any payment shows a note instead of the chart (this also fixes 1M without payments).
- **Consequences:**
  - About one request per held ticker every 15 minutes more in online mode; still only tickers (R-009).
  - The first point of the day can differ from the dashed previous close: the close is valued at NBP rates, the day at market rates, and overnight moves (post-market, currencies) count from midnight.

### D-071 Live redraws: the history valued once per data version, live quotes laid over the last day
- **Date:** 2026-11-18 · **Status:** Accepted (refines D-069)
- **Context:** the user asked whether the page reloads as a whole every 5 seconds and whether each panel should refresh on its own, perhaps as a single-page app. It does not reload: Streamlit keeps a WebSocket and Portfel reruns only two fragments (KPI tiles with the value chart, and the positions table). But every redraw valued the whole history again, because the live quotes were part of the valuation's cache key, and rebuilt every chart. The user's condition: every redraw keeps refreshing all data and charts, not only "today", done as efficiently as possible, measured before and after.
- **Decision:**
  - **Stay with Streamlit fragments; no single-page app.** Fragments already redraw panel by panel and send only their own elements. A separate frontend with its own API would add a second technology stack and its own packaging without CDNs (D-011) for little more.
  - **History once, quotes on the last day:** `ui.data._history` values the history without live quotes, cached per data version and day (`st.cache_resource`, not copied per redraw). `valuation.apply_live` lays the live prices and rates over the last day's rows only. A test checks the result equals `value_portfolio` with the quotes, number for number. Where it could differ (a live rate for a currency without NBP rates, a live price for a holding valued without a market price that day), it returns None and the whole history is valued with the quotes, as before.
  - **Cheaper per-redraw work:** `Valuation.total` computed once per valuation; the Plotly template built once per mode; a sparkline built in one constructor call (the same figure as before); `intraday_values` vectorised; the positions' 90-day trends in one as-of join (`returns.position_result_trends`).
  - **Pace follows the markets** (`ui.data.live_every`): the user's redraw interval while any tracked exchange is in session (pre- and post-market included), 60 s while only currencies trade, 5 minutes while nothing trades, nothing offline. When an exchange opens or the last one closes, the next fragment run reruns the page once so the new interval applies (not while a chart dialog is open). A fragment cannot skip a redraw when nothing changed: Streamlit removes whatever a fragment run does not draw.
  - **Zwroty and Dywidendy keep the full rerun** at most once a minute on new quotes (D-069): about 170 ms and 70 ms per run after this change, too little to justify fragments there.
  - **`docs/panels.md`:** per page, what triggers a rerun, what it reads, what is cached per data version, what is recomputed on every redraw, what goes to the browser. Updated together with any change to a page (CLAUDE.md, ui-guidelines §7–§8, `/ui-page`); a test checks every page has a complete section.
- **Measurements** (demo data: 1039 days, 26 positions, 13 tickers; stream every 5 s; period "Maks."):
  - valuation per redraw: 219 → 27 ms (profiled); `headline()` 207 → 108 ms (Maks.), 306 → 179 ms (1D); `positions()` 90 → 63 ms;
  - whole Streamlit process with Portfel open, CPU over one minute: 9.9 % → 5.8 % of a core; of that, 2.5 % is the feed and the sidebar (Ustawienia open), so Portfel itself went from about 7.4 % to 3.3 %;
  - browser: about 750 DOM changes a second and no long tasks, before and after: the browser was never the bottleneck;
  - every element of Portfel, Zwroty and Dywidendy (12 variants of period and "Po inflacji", 598 elements) is identical before and after at the same quotes, except the clock time in the 1D charts.
- **Consequences:**
  - The first fast redraw after an exchange opens can come up to a minute late (the quiet interval).
  - The live overlay assumes live quotes change only the last day, which is how D-021/D-069 already defined them; a future change to that rule must change `apply_live` too (the equivalence test will catch it).

### D-072 Live charts update in place: a Plotly component instead of `st.plotly_chart`
- **Date:** 2026-11-18 · **Status:** Accepted
- **Context:** after D-071 the user saw the tiles and the "Wartość portfela" chart blink on every live redraw: the chart disappeared for a moment and came back. Measured in the browser: on each redraw Streamlit dimmed the fragment's elements to 33 % opacity while it ran, and replaced every Plotly chart whose data changed. `st.plotly_chart` (Streamlit 1.67) computes the element ID from the whole figure, and its frontend reads the figure only on mount (`useState` per ID), so new data means a new chart drawn from scratch: about 25 ms (one or two frames) of an empty area. Keeping the ID stable (tried) made the chart stop updating at all. The replaced charts were also kept hidden in the page for a while (`data-retained`, up to ~100 before Streamlit cleaned them up).
- **Decision:**
  - **`ui/live_chart.py`:** a small Streamlit component (components v2, in the page, no iframe) that keeps one `div` per key and hands it each new figure with `Plotly.react`. Used by `show(..., live=True)` (the value chart on Portfel), `show_spark` (all KPI sparklines) and `show_detail` (the "Pełny wykres" dialog). Charts outside live fragments stay on `st.plotly_chart`.
  - **plotly.js stays local (D-011, R-015):** copied once per version from the installed `plotly` package into the app's `static/` folder (git-ignored, not shipped in the wheel) and served by Streamlit (`server.enableStaticServing`, also passed by `fa ui`). The component always uses its own copy, kept apart from the global `Plotly` that Streamlit's charts set (another version), so one chart is never drawn by one version and updated by another. If the copy fails or static serving is off, charts fall back to `st.plotly_chart`.
  - **Zoom:** `view=` (the period and "Po inflacji" on Portfel; the period start and daily or intraday in the dialog) becomes the figure's `uirevision`: the viewer's zoom survives live redraws of the same view and resets on another. Without it Plotly carried a zoom on "Maks." over to "1D" (the axis showed 2000–2001).
  - **No dimming on a live redraw:** CSS keeps elements at full opacity while a fragment runs. A full run still dims and shows "Przeliczam…" (D-060).
- **Verified in the browser** (demo data, stream every 5 s): over 20 s the value chart updated 4 times with no replaced node and no empty frame; sparklines and the open dialog update in place; zoom kept across redraws and reset on 1D → Maks. → 1R; light and dark mode unchanged.
- **Consequences:** about 4.7 MB of plotly.js is loaded once per browser session from this machine. The component relies on Streamlit's components v2 API; a Streamlit upgrade should be checked in the browser (the fallback keeps pages working).

---

## Open questions

| ID | Question | Status |
|---|---|---|
| Q-001 | How does XTB record stock splits in position history (adjusted volumes and prices, or a separate operation)? | Open: check against real data |
| Q-002 | Where do COI coupons go? If to a bank account outside the tracked portfolio, they count as a withdrawal. | Resolved 2026-11-16 by D-026: coupons and redemptions are withdrawals (net of tax) |
| Q-003 | IKE and IKZE accounts exist at XTB. Effects to model: no capital-gains tax on dividends and sales (withholding tax still applies), maybe a view of yearly contribution limits. Can bonds be held in IKE too? | Open. Bonds: yes, the issue letters allow IKE and IKZE at PKO BP; D-026 drops the tax for bonds on an account with `tax_wrapper` IKE/IKZE, but still counts their coupons as withdrawals although they stay on the IKE register. |
| Q-004 | Benchmark for comparisons (e.g. WIG, MSCI ACWI in PLN): whether and when? | Open |
| Q-005 | Open-source licence (e.g. MIT, Apache-2.0, AGPL-3.0). | Resolved 2026-11-16 by D-030 |
| Q-007 | Online mode: how to keep prices live, where the setting lives, how offline is enforced. | Resolved 2026-11-16 by D-021 |
| Q-006 | XTB export details not yet confirmed: ~~(a) the text-only row in an empty *Closed Positions* sheet~~ resolved 2026-11-16: a `Profit/loss` total row; ~~(b) summary row before positions~~ resolved 2026-11-16: yes; (c) ~~cash operation types for sales and withdrawals~~ resolved 2026-11-17 by D-043 (`Stock sell`, `Withdrawal`, `Subaccount transfer`); still open: their comment formats, types for fees and FX conversion, and the *Closed Positions* value types, none of which appear in the sample; (d) on PLN/EUR accounts holding USD instruments, which currency `Amount`, `Value` and the profits are in. The mock assumes the account currency. | Open: needs a larger export or the user's answer |

---

## Ideas for later

Not part of the current plan. Pick them up after a working prototype exists, with a
`/grill-me` session and a proper decision entry.

| ID | Idea | Notes | Added |
|---|---|---|---|
| I-001 | **Customisable home page from modules.** The user builds their own start page from tiles placed on a grid, e.g. KPI, value chart, allocation, dividends or holdings, and arranges them as they like. The result is a personal dashboard with exactly what they want to see. | Every existing view would need to be packaged as a self-contained module with its own settings. The layout would be stored locally (e.g. `data/config/dashboard.yaml`), in line with D-002 and R-015. Streamlit has no built-in drag-and-drop grid: a vetted component or a custom one would be needed, and it must not load anything from the internet (D-011). | 2026-11-16 |
| I-002 | **Edit the asset class of an instrument in the UI.** A select box per ticker (e.g. on Importy or in the holdings table) that writes `data/config/instruments.yaml` (D-040). | Today the overrides file is edited by hand. Maybe also more classes then, e.g. crypto or commodities for the other ETC/ETN. | 2026-11-17 |

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
| Statement importers (Revolut, Erste, Trade Republic, Wise) | See above | **Deferred (2026-11-16, D-027).** Cash is entered by hand until the user provides masked inspector reports of real exports. No importer is written and no export format guessed before then; the formats above come from public descriptions only. |
| Treasury bonds (PKO BP registry) | No API; no CSV/XLS export found | Manual entry (3 fields) with automatic valuation. Series parameters come from the public issue letters ("list emisyjny") and the Ministry of Finance rate file. |

Public data sources:

- **FX:** `https://api.nbp.pl/api/exchangerates/rates/a/{code}/{from}/{to}/?format=json`. At most 93 days per request; 404 means no quotes in the range. Data from 2002.
- **CPI:** the GUS CSV "Miesięczne wskaźniki cen towarów i usług konsumpcyjnych od 1982 roku".
  - The file name changes with each release, so read the link from the page.
  - `;` separator, decimal comma, likely cp1250.
  - Index types: previous month = 100, same month a year earlier = 100, December = 100.
  - The flash estimate comes out at month end, final data around the 15th of the next month.
- **Bonds (EDO, COI):** from the second period the rate is the y/y CPI announced in the month before the period starts (in practice the figure for two months earlier), floored at 0, plus the series margin. EDO capitalises interest yearly; COI pays a yearly coupon. Early-redemption fees differ per series, so they are stored per series.
- **Bonds, checked 2026-11-16 (D-026):**
  - Ministry of Finance xls "Dane dotyczące obligacji detalicznych" on gov.pl/web/finanse/obligacje-detaliczne1: one sheet per type (OTS, ROR, DOR, TOS, COI, EDO, ROS, ROD, plus older types), with sale dates, first rate, margin, the rate of every elapsed period and the interest paid. It is the best single source of official rates.
  - Issue letters: obligacjeskarbowe.pl/listy-emisyjne/?id=<series> (active series) and /archiwum-listow-emisyjnych/?id=<series> (matured), each linking one PDF. PDF text extraction sometimes splits Polish words at diacritics, so parse with whitespace removed.
  - Interest tables ("tabela odsetkowa"): obligacjeskarbowe.pl/tabela-odsetkowa/?table_id=<id>, one PDF per series and period, with the interest per bond for every day for a purchase on the first day of sale.
  - NBP reference rate history: static.nbp.pl/dane/stopy/stopy_procentowe_archiwum.xml (`obowiazuje_od`, `id="ref"`).
  - GUS revises the January CPI in March; bond rates keep the figure first announced, so a rate computed from today's GUS file can be off for periods starting in March.
- **Prices:** yfinance (unofficial; rate-limited by Yahoo). Cache everything, fetch incrementally, back off on `YFRateLimitError`. Ticker suffixes: `.WA` Warsaw, `.L` London, `.DE` Xetra, `.AS` Amsterdam.
