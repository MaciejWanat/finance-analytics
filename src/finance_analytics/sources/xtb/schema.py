"""Layout of the xStation "account history" xlsx export.

Single source of truth for sheet names, header rows and column names. The mock
generator and (later) the parser both use it. Derived from a masked inspector report
of a real export (2026-11), see docs/xtb-export-format.md. Do not edit from memory:
re-run scripts/inspect_xtb_export.py on a fresh export and update from its report.
"""

from __future__ import annotations

from dataclasses import dataclass

# File name: <PREFIX>_<account number>_<date from>_<date to>.xlsx, dates as YYYY-MM-DD.
FILE_PREFIXES = ("PLN", "EUR", "USD", "IKE", "IKZE")
TAX_WRAPPER_PREFIXES = ("IKE", "IKZE")

ACCOUNT_NUMBER_LABEL = "Account number"  # cell A1; the number itself is text in B1
# A3/A4 with datetimes in B3/B4 (Closed Positions, Cash Operations). The report masked
# the 3-letter word in brackets; "UTC" is assumed from the "(UTC)" column names. The
# parser must not rely on these labels.
DATE_FROM_LABEL = "Date from (UTC)"
DATE_TO_LABEL = "Date to (UTC)"

PRODUCT = "My Trades"  # the only value seen in the Product column


@dataclass(frozen=True)
class SheetLayout:
    name: str
    header_row: int  # 1-based
    columns: tuple[str, ...]


CLOSED_POSITIONS = SheetLayout(
    name="Closed Positions",
    header_row=5,
    columns=(
        "Instrument", "Ticker", "Category", "Type", "Volume", "Open Price", "Open Time (UTC)",
        "Close Price", "Close Time (UTC)", "Product", "Profit/Loss", "Gross Profit", "Purchase Value",
        "Sale Value", "Stop Loss", "Take Profit", "Commission", "Margin", "Swap", "Rollover",
        "Open Conversion Rate", "Close Conversion Rate", "Close Origin", "Position ID", "Comment",
    ),
)

CASH_OPERATIONS = SheetLayout(
    name="Cash Operations",
    header_row=5,
    columns=("Type", "Instrument", "Ticker", "Category", "Time", "Amount", "ID", "Comment", "Product", "Position ID"),
)

# Rows 4-6 hold a small summary table (Product | metric | Amount | Currency), row 8 a note.
OPEN_POSITIONS = SheetLayout(
    name="Open Positions",
    header_row=9,
    columns=(
        "Product", "Instrument/Position", "Ticker", "Category", "Type", "Volume", "Value",
        "Current price", "Open price", "Open time (UTC)", "Stop Loss", "Take Profit", "Net Profit %",
        "Net Profit", "Gross Profit", "Margin", "Open Commission", "Swap", "Rollover",
    ),
)

SHEETS = (CLOSED_POSITIONS, CASH_OPERATIONS, OPEN_POSITIONS)  # order in the workbook

# Cash operation types seen so far. Others (sales, withdrawals, fees) exist in XTB but
# have not been observed yet; the parser must reject unknown types loudly (D-007).
CASH_TYPES_OBSERVED = (
    "Deposit",
    "Stock purchase",
    "Dividend",
    "Withholding tax",
    "Free funds interest",
    "Free funds interest tax",
)
# Used by the mock export for sales, but NOT seen in a real export yet (Q-006). The
# parser must not accept these until a real report confirms them.
CASH_TYPES_ASSUMED = ("Stock sale",)
CLOSED_TOTAL_ROW = "Profit/loss"  # last row of Closed Positions (seen with no closed positions)
CASH_TOTAL_ROW = "Total"  # last row of Cash Operations: Type="Total", only Amount filled

CATEGORIES_OBSERVED = ("ETF", "STOCK", "ETC", "ETN")
OPEN_POSITION_TYPES_OBSERVED = ("BUY",)
TICKER_SUFFIXES_OBSERVED = (".UK", ".US", ".DE", ".PL")

# Comment formats seen in Cash Operations (values here are placeholders):
#   Stock purchase:            "OPEN BUY VUAA.UK 1.2345 @ 121.34"
#   Dividend:                  "AAPL.US USD 0.26/ SHR"
#   Withholding tax:           "AAPL.US USD WHT 15%"
#   Free funds interest:       "Free-funds Interest 2026-10"
#   Free funds interest tax:   "Free-funds Interest Tax 2026-10"
#   Deposit: free text from the payment provider with a transaction id (varies)
