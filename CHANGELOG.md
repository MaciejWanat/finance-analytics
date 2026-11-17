# Changelog

All notable changes to this project are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). Decision IDs (`D-xxx`) point to `docs/decisions.md`.

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

[0.9.0]: https://github.com/MaciejWanat/finance-analytics/releases/tag/v0.9.0
