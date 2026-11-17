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
- **Date:** 2026-11-16 · **Status:** Accepted; offline semantics refined by D-031
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
