# Changelog

All notable changes to this project are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). Decision IDs (`D-xxx`) point to `docs/decisions.md`.

## [Unreleased]

### Changed

- **Lighter live prices on Portfel:** a live redraw no longer values the whole history again. It is valued once
  and today's prices are laid over the last day, with exactly the same numbers. With the stream every 5 seconds
  the Portfel page itself now uses less than half the processor time it did (about 3 % instead of 7 % of
  one core on the demo data). While markets are closed the page redraws less
  often: every minute while only currencies trade, every 5 minutes at weekends (D-071).

### Fixed

- **No more blinking on live redraws:** the "Wartość portfela" chart, the tile sparklines and an open "Pełny
  wykres" now change in place instead of disappearing and being drawn again every few seconds, and the tiles no
  longer fade while they refresh. Zoom on the value chart stays while prices update and resets when you pick
  another period (D-072).

## [0.11.0] - 2026-11-18

Prices that move by themselves: live every few seconds through a stream, and a "1D" period that
shows today every 5 minutes.

### Added

- **Open and closed exchanges** in the sidebar: USA, London, Germany (Xetra) and Warsaw, each
  with a lamp for its state (open, closed, pre-market, post-market) and the time to the regular
  open, or to the close while it is open. It accounts for each
  exchange's holidays and shortened sessions and for the weeks when daylight-saving time in the
  US and Europe differs, and it works offline (D-066, D-068).
- **Setting for the "Dzisiaj" tile** on Ustawienia: from midnight (default, as before) or by US
  sessions, for a portfolio with US-listed instruments: a new day starts at the US open, the result
  stays after the close until the next open, and moves between sessions (currencies, other
  exchanges, weekends) count towards the next one (D-067).
- **Live prices every few seconds** in online mode: choose on Ustawienia between polling (every
  2 min to 1 h, so Yahoo does not refuse) and a streaming connection to Yahoo, where prices arrive by
  themselves and Portfel redraws every 5 to 60 s. US
  pre-market and post-market prices count too. On Portfel the tiles, the value chart and the
  positions table redraw on their own, without reloading the page; a pulsing lamp in the sidebar
  shows the stream is live (D-069).
- **"1D" period** on Portfel, Zwroty and Dywidendy: the day of the "Dzisiaj" tile every 5 minutes,
  live, against the previous close; hourly composition bars and the day's TWR, falls and
  price / currency split. Online, 5-minute quotes from Yahoo arrive in the background; offline
  one button fetches them (D-070).

### Changed

- The "Dzisiaj" tile no longer shows the grey "sesja dd.mm" badge; when it shows an earlier
  session than today, its tooltip names the date (D-067).
- The "Wynik w okresie" tile's sparkline is red below zero and green above it, like the other
  result tiles.
- In online mode market data is also updated shortly after each US close, so the session's
  closing prices are final (D-067).
- Live prices are fetched in the background, so the network never delays a page; they count only
  on the day they arrive. The interval is set per source (`poll_seconds`, `stream_seconds`); an older
  `refresh_minutes` setting becomes the polling interval, at least 2 minutes (D-069).
- The "Przeliczam…" pill shows only when the whole page recalculates, not on live redraws (D-069).

### Fixed

- Dywidendy no longer fails for a period without any payment (e.g. 1M); it says there were none.

## [0.10.0] - 2026-11-18

Install a chosen version without git or a prepared Python: each release now has the app attached
as a wheel, installed with one `uv tool install` command (D-065).

### Added

- **Release wheel:** `uv tool install finance_analytics-<version>-py3-none-any.whl` installs the
  app with its own Python environment (uv downloads Python if needed); installing a newer wheel
  the same way upgrades it, and `uv tool uninstall finance-analytics` removes it.
- **Per-user data folder** for an installed app: `%LOCALAPPDATA%\finance-analytics\data` on
  Windows, `~/Library/Application Support/finance-analytics/data` on macOS,
  `~/.local/share/finance-analytics/data` on Linux, with `demo` next to it. Deliberately not
  Documents, which is often synced to OneDrive. `FA_DATA_DIR` still overrides it.
- `fa init` and `fa ui` print the data folder in use.

### Changed

- The UI moved into the package, to `src/finance_analytics/app/`, together with its
  `.streamlit/config.toml`; `fa ui` runs it from there. **Restart a running `fa ui` after updating
  a source checkout.**
- From source, the data folder is always `data/` in the repository (and `data-demo/` for the
  demo), no longer relative to the folder `fa` is run from.
- `fa mock-xtb` writes to the demo folder by default.
- README: installing a release with uv comes first; installing from source is for development.

## [0.9.0] - 2026-11-18

First release. The core scope works end to end: XTB accounts, treasury bonds and bank cash,
valued daily in PLN, fully offline. Version 0.9 rather than 1.0 because some details of the
XTB export are still assumptions (see *Known limitations*), so expect fixes before 1.0.

### Added

- **XTB import** of the xStation account history export: a folder, the zip xStation saves or a
  single `.xlsx`; PLN, EUR, USD accounts and IKE / IKZE sub-accounts; overlapping exports merged
  and cross-checked; partial fills, partial sales and stock splits handled (D-015, D-016, D-033,
  D-044, D-048, D-051). An inbox folder imports new exports by themselves (D-028).
- **Daily valuation in PLN** of positions, broker cash, bonds and bank cash, at NBP table A rates
  (D-008, D-019). Days without a market price use the user's own trade prices (D-052).
- **Returns:** TWR, XIRR, maximum and current drawdown, monthly returns (D-022), and the split of
  the PLN return into prices × currencies × other (D-023).
- **Dividends:** gross, withholding tax and net in PLN at the NBP rate of D-1, with a PIT-38
  estimate; none on IKE / IKZE (D-024).
- **Inflation:** GUS CPI, real returns, values in today's złoty and a "Po inflacji" switch on
  Portfel (D-025, D-041, D-058).
- **Polish retail treasury bonds** (OTS, ROR, DOR, TOS, COI, EDO, ROS, ROD) valued to the grosz
  from the issue-letter rules, with the parameters and official rates of every series sold from
  01.2019 to 11.2026 shipped with the app (data as of 2026-11-16) (D-026).
- **Cash at banks** entered by hand as balances on a date; CSV download, template and validated
  upload for all manual data (D-027).
- **Asset classes** including precious metals, with per-symbol overrides in `instruments.yaml`
  (D-040); Yahoo ticker overrides in `yahoo_tickers.yaml` (D-039).
- **Pages** (UI in Polish): Portfel with tiles for today's result, the period result, the result
  on currencies and profit vs deposits; Zwroty, Dywidendy, Obligacje, Gotówka, Importy,
  Dane rynkowe, Ustawienia. Tooltips explain every number (D-012).
- **Privacy:** offline by default; market data is fetched only on request, or automatically in
  online mode, and requests carry only tickers, currency codes and dates (D-021, D-031). Network
  code is confined to `market/`, Streamlit telemetry is off and the server binds to `localhost`
  (D-011). A pre-commit hook keeps real data out of the repository (D-014).
- **CLI** `fa`: `init`, `ui`, `demo`, `import xtb`, `import inbox`, `update-market`, `settings`,
  `sync`, `rebuild`, `reset`, `mock-xtb`. `fa demo` runs the app on synthetic data.

### Known limitations

- XTB is the only broker. Bank cash is entered by hand; statement importers wait for real exports.
- Some XTB export details have not been seen in a real export yet (Closed Positions values, fees,
  FX conversion, the currency of USD instruments on a PLN account). They are handled by
  assumptions that the import reports as warnings (Q-006). Stock splits are detected heuristically.
- Tickers map to Yahoo by suffix (`.US`, `.UK`, `.DE`, `.PL`); others need `yahoo_tickers.yaml`.
- Bond series and rates newer than the shipped data are computed and labelled, or need
  `bond_series.yaml` for a new series.
- Tax figures are estimates, not tax advice.

[0.11.0]: https://github.com/MaciejWanat/finance-analytics/releases/tag/v0.11.0
[0.10.0]: https://github.com/MaciejWanat/finance-analytics/releases/tag/v0.10.0
[0.9.0]: https://github.com/MaciejWanat/finance-analytics/releases/tag/v0.9.0
