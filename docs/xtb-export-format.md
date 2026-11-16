# XTB (xStation) export format

What the "account history" xlsx export looks like, as observed in a masked inspector
report of a real export (2026-11). The report itself stays local, in
`data/samples/xtb_report.md` (git-ignored). It is masked, but still describes a real
account: how many operations, the shape of payer names. This page is its
publishable summary. The code mirror of this page is
`src/finance_analytics/sources/xtb/schema.py`; `fa mock-xtb` writes a synthetic export
with the same layout.

To update this page, run the inspector from the project root, so the report lands in
`data/samples/`:

```bash
python scripts/inspect_xtb_export.py <export folder> --out data/samples/xtb_report.md
```

Never paste real values here.

## Folder

```
<export root>/
  <subfolder>/                         # several per export; names are not account numbers
    USD_<number>_<YYYY-MM-DD>_<YYYY-MM-DD>.xlsx
  <subfolder>/
    PLN_<number>_….xlsx                # one subfolder can hold several accounts
    IKE_<number>_….xlsx
    IKZE_<number>_….xlsx
```

- Prefix: `PLN`, `EUR`, `USD` (account currency) or `IKE`, `IKZE` (tax wrapper).
- Number: 7 digits for regular accounts, 8 for IKE/IKZE in the sample.
- The dates are the export range.
- An account with no activity still gets a file, with the three sheets completely empty (no header block either).

## Sheets

Every file has three sheets in this order: `Closed Positions`, `Cash Operations`, `Open Positions`.

### Header block (all sheets with data)

| Row | A | B |
|---|---|---|
| 1 | `Account number` | account number, as text; for a sub-account (IKE, IKZE…) this is the main account's number, while the file name carries the sub-account's own number (D-033) |
| 2 | sheet title | |
| 3 | `Date from (…)` | datetime (Closed Positions, Cash Operations) |
| 4 | `Date to (…)` | datetime |

The bracket says `UTC`. `Date from` is Polish local midnight expressed in UTC (22:00 or
23:00 of the previous day), and `Date to` is the moment of the export.

### Closed Positions (header row 5)

`Instrument`, `Ticker`, `Category`, `Type`, `Volume`, `Open Price`, `Open Time (UTC)`,
`Close Price`, `Close Time (UTC)`, `Product`, `Profit/Loss`, `Gross Profit`,
`Purchase Value`, `Sale Value`, `Stop Loss`, `Take Profit`, `Commission`, `Margin`,
`Swap`, `Rollover`, `Open Conversion Rate`, `Close Conversion Rate`, `Close Origin`,
`Position ID`, `Comment`

The last row has `Profit/loss` in column A; with no closed positions it is the only
row. Value types of real closed positions are still unknown (Q-006).

### Cash Operations (header row 5)

| Column | Type | Notes |
|---|---|---|
| Type | text | seen: `Deposit`, `Stock purchase`, `Dividend`, `Withholding tax`, `Free funds interest`, `Free funds interest tax` |
| Instrument | text | instrument name; empty for deposits and interest |
| Ticker | text | `XXXX.US`, `XXXX.UK` |
| Category | text | `ETF`, `STOCK` |
| Time | datetime | with seconds |
| Amount | number | signed, in the account currency (purchases and taxes are negative) |
| ID | text, 10 digits | unique per operation, usable for de-duplication |
| Comment | text | see below |
| Product | text | `My Trades` |
| Position ID | text, 10 digits | only on `Stock purchase` |

The last row is a total: `Type` = `Total`, only `Amount` filled.

Comment formats (placeholder values):

| Type | Comment |
|---|---|
| Stock purchase | `OPEN BUY VUAA.UK 1.2345 @ 121.34` (volume may be fractional) |
| Dividend | `AAPL.US USD 0.26/ SHR` |
| Withholding tax | `AAPL.US USD WHT 15%` |
| Free funds interest | `Free-funds Interest 2026-10` |
| Free funds interest tax | `Free-funds Interest Tax 2026-10` |
| Deposit | free text from the payment provider with a transaction id; contains personal data |

### Open Positions (header row 9)

Rows 3–8 above the header:
- row 3: report timestamp (A: label, B: datetime);
- rows 4–6: a small table `Product | <metric> | Amount | Currency`, with metrics `Open position value` and `Open position profit`;
- row 7: empty;
- row 8: `Note` with the text "Summary values and open positions are shown as of the report generation time".

Columns: `Product`, `Instrument/Position`, `Ticker`, `Category`, `Type`, `Volume`,
`Value`, `Current price`, `Open price`, `Open time (UTC)`, `Stop Loss`, `Take Profit`,
`Net Profit %`, `Net Profit`, `Gross Profit`, `Margin`, `Open Commission`, `Swap`,
`Rollover`.

Two kinds of rows:
- **instrument summary:** `Instrument/Position` holds the instrument name and `Category` is set. `Type`, `Current price` and `Open time` are empty.
- **position:** `Instrument/Position` holds the position ID (text, 9–10 digits), `Type` = `BUY`, `Category` is empty.

Each summary row comes first, followed by its instrument's positions.

## Styling

The parser ignores styling; the mock reproduces it so the files look like the real thing:
- Calibri 11 everywhere;
- header rows (and the small summary table header in Open Positions) are black bars with white bold text;
- the sheet title in A2 is bold;
- the `Note` row has a light beige fill, a bold label and italic text;
- instrument summary rows in Open Positions are bold (including `My Trades`); position rows are not;
- money figures are green when positive and red when negative: Profit/Loss and Gross Profit (Closed Positions), Amount (Cash Operations), Net Profit %, Net Profit and Gross Profit (Open Positions).

`Volume` can be fractional (up to 4 decimals). Prices have 2 decimals.

## Not seen yet (Q-006)

The following have not appeared in a real export yet:
- sales and closed positions;
- withdrawals, fees and commissions, currency conversions;
- tickers other than `.US` and `.UK` (e.g. Warsaw);
- the content of IKE/IKZE/PLN/EUR accounts, including how USD instruments bought on a PLN or EUR account are reported.

The parser rejects unknown cash operation types loudly instead of guessing.

The mock export (`fa mock-xtb`) fills all five accounts and makes these assumptions:
- On PLN/EUR accounts `Amount` and Open Positions `Value` / profits are in the account currency, converted with a 0.5% FX fee.
- Prices and comments stay in the instrument currency.
- IKE/IKZE get no `Free funds interest tax`.
- Sales close a whole stock position:
  - cash operation type `Stock sale`, comment `CLOSE BUY <ticker> <volume> @ <price>`;
  - Closed Positions row with `Purchase Value`/`Sale Value`/`Profit/Loss` in the account currency and the open/close conversion rates;
  - commission 0.

Check these against a real export with activity on those accounts.
