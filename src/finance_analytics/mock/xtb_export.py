"""Write a synthetic xStation export folder with the real layout and fake values.

The layout (sheets, header rows, columns, value types, comment formats) comes from
`finance_analytics.sources.xtb.schema`, which was derived from a masked report of a
real export. Every value is invented: account numbers, IDs, prices, FX rates, the
deposit text.

The simulated saver has five accounts (USD, PLN, EUR, IKE, IKZE) and on each one:
- deposits money every month and buys index ETFs (S&P 500, MSCI World, …), and on the
  PLN account also a physically backed gold ETC (asset class "precious_metals", D-040);
- buys single stocks (NVDA, TSLA, AMD, MSFT, …) a few times a year and sells some later;
- receives quarterly dividends with 15% US withholding tax;
- earns interest on free funds; the 19% tax on it is skipped on IKE/IKZE.

Mirrors what the real export showed: one folder can hold several account files, Cash
Operations ends with a "Total" row, and Open Positions lists one summary row per
instrument followed by that instrument's positions.

Assumptions (not seen in the real sample, see Q-006 in docs/decisions.md):
- On PLN/EUR accounts, `Amount` is in the account currency (converted with a 0.5% FX
  fee) while prices and comments stay in the instrument currency.
- Open Positions `Value` and profits are in the account currency.
- Sales: a whole single-stock position is closed now and then. The cash-operation type
  ("Stock sale"), its comment ("CLOSE BUY …") and the Closed Positions values are
  guesses: the real sample had no sale (schema.CASH_TYPES_ASSUMED).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from finance_analytics.sources.xtb import schema


@dataclass(frozen=True)
class Instrument:
    ticker: str
    name: str
    category: str  # ETF | ETC | STOCK
    start_price: float  # in USD, at the start of the mock period
    drift: float  # yearly
    volatility: float  # amplitude of the deterministic price wave
    dividend_per_share: float = 0.0  # quarterly; 0 = no dividend / accumulating ETF


ETFS = {
    "VUAA.UK": Instrument("VUAA.UK", "S&P 500 UCITS ETF Acc", "ETF", 118.0, 0.11, 0.06),
    "IWDA.UK": Instrument("IWDA.UK", "Core MSCI World", "ETF", 98.0, 0.09, 0.05),
    "VWRA.UK": Instrument("VWRA.UK", "FTSE All-World", "ETF", 128.0, 0.08, 0.05),
    "EIMI.UK": Instrument("EIMI.UK", "Core MSCI EM IMI", "ETF", 33.0, 0.05, 0.07),
    "SGLN.UK": Instrument("SGLN.UK", "Physical Gold ETC", "ETC", 52.0, 0.07, 0.05),
}

STOCKS = {
    "NVDA.US": Instrument("NVDA.US", "NVIDIA", "STOCK", 140.0, 0.30, 0.20, dividend_per_share=0.01),
    "TSLA.US": Instrument("TSLA.US", "Tesla", "STOCK", 320.0, 0.15, 0.30),
    "AMD.US": Instrument("AMD.US", "Advanced Micro Devices", "STOCK", 145.0, 0.10, 0.22),
    "MSFT.US": Instrument("MSFT.US", "Microsoft", "STOCK", 420.0, 0.12, 0.08, dividend_per_share=0.83),
    "AAPL.US": Instrument("AAPL.US", "Apple", "STOCK", 225.0, 0.10, 0.09, dividend_per_share=0.26),
    "GOOGL.US": Instrument("GOOGL.US", "Alphabet A", "STOCK", 175.0, 0.14, 0.10, dividend_per_share=0.21),
    "AMZN.US": Instrument("AMZN.US", "Amazon", "STOCK", 205.0, 0.13, 0.11),
    "META.US": Instrument("META.US", "Meta Platforms", "STOCK", 580.0, 0.15, 0.12, dividend_per_share=0.53),
}

INSTRUMENTS = {**ETFS, **STOCKS}  # order of instrument groups in Open Positions


@dataclass(frozen=True)
class AccountFile:
    folder: str
    prefix: str  # schema.FILE_PREFIXES
    number: str
    currency: str
    monthly_deposit: float  # in the account currency
    etfs: tuple[str, ...]  # bought every month
    stocks_per_year: int  # single-stock purchases per year (on average)

    @property
    def tax_wrapper(self) -> bool:
        return self.prefix in schema.TAX_WRAPPER_PREFIXES


ACCOUNTS = (
    AccountFile("50000001", "USD", "1000001", "USD", 800.0, ("VUAA.UK", "VWRA.UK"), 4),
    AccountFile("50000002", "PLN", "1000002", "PLN", 3000.0, ("VUAA.UK", "IWDA.UK", "EIMI.UK", "SGLN.UK"), 5),
    AccountFile("50000002", "IKE", "20000003", "PLN", 2000.0, ("VWRA.UK", "EIMI.UK"), 3),
    AccountFile("50000002", "IKZE", "20000004", "PLN", 900.0, ("VUAA.UK",), 2),
    AccountFile("50000003", "EUR", "1000005", "EUR", 700.0, ("IWDA.UK", "VUAA.UK"), 4),
)

FX_FEE = 0.005  # currency conversion fee on non-USD accounts
USD_RATES = {"USD": (1.0, 0.0), "PLN": (3.95, 0.05), "EUR": (0.92, 0.03)}  # account ccy per 1 USD


# ------------------------------------------------------------------ market model


def _wave(key: str, day: date, amplitude: float) -> float:
    """Deterministic, smooth-ish fluctuation: same key and day give the same value."""
    t = day.toordinal()
    phase = random.Random(key).uniform(0, 2 * math.pi)
    jitter = random.Random(f"{key}{t}").uniform(-0.15, 0.15)
    return amplitude * (math.sin(t / 47 + phase) * 0.7 + math.sin(t / 13 + 2 * phase) * 0.3 + jitter)


def price_usd(instrument: Instrument, day: date, start: date) -> float:
    years = (day - start).days / 365.25
    level = instrument.start_price * (1 + instrument.drift) ** years
    return round(level * (1 + _wave(instrument.ticker, day, instrument.volatility)), 2)


def usd_to(currency: str, day: date) -> float:
    """Units of `currency` per 1 USD on `day` (fake rates)."""
    base, amplitude = USD_RATES[currency]
    return base * (1 + _wave(f"fx-{currency}", day, amplitude))


# --------------------------------------------------------------------- ledger


@dataclass
class _Position:
    instrument: Instrument
    position_id: str
    opened: datetime
    volume: float
    price: float  # instrument currency
    cost: float  # account currency, incl. FX fee
    fx_open: float  # account currency per 1 USD at opening (1.0 on USD accounts)


@dataclass
class _Ledger:
    cash_rows: list[list] = field(default_factory=list)
    positions: list[_Position] = field(default_factory=list)
    closed: list[list] = field(default_factory=list)  # Closed Positions rows
    cash: float = 0.0


class _Ids:
    """Unique 10-digit text IDs, as in the real export."""

    def __init__(self, rng: random.Random) -> None:
        self._rng, self._used = rng, set()

    def next(self) -> str:
        while True:
            value = str(self._rng.randint(1_000_000_000, 9_999_999_999))
            if value not in self._used:
                self._used.add(value)
                return value


def _moment(day: date, rng: random.Random, hours: tuple[int, int]) -> datetime:
    return datetime(day.year, day.month, day.day, rng.randint(*hours), rng.randint(0, 59), rng.randint(0, 59))


def _business_day(day: date) -> date:
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


class _Simulation:
    def __init__(self, account: AccountFile, start: date, end: date, rng: random.Random, ids: _Ids) -> None:
        self.account, self.start, self.end, self.rng, self.ids = account, start, end, rng, ids
        self.ledger = _Ledger()

    def _cash_row(self, kind, instrument, moment, amount, comment, position_id=None):
        self.ledger.cash_rows.append([
            kind,
            instrument.name if instrument else None,
            instrument.ticker if instrument else None,
            instrument.category if instrument else None,
            moment, round(amount, 2), self.ids.next(), comment, schema.PRODUCT, position_id,
        ])
        self.ledger.cash += round(amount, 2)

    def _fx(self, day: date) -> float:
        return 1.0 if self.account.currency == "USD" else usd_to(self.account.currency, day)

    def _to_account(self, usd: float, day: date, fee: bool) -> float:
        if self.account.currency == "USD":
            return usd
        return usd * self._fx(day) * ((1 + FX_FEE) if fee else (1 - FX_FEE))

    def deposit(self, day: date) -> None:
        amount = self.account.monthly_deposit * self.rng.choice([1.0, 1.0, 1.0, 1.5])
        comment = (
            f"Mock Pay deposit, Mock Pay incoming transaction id=mock-{self.ids.next()}, "
            f"Test User, id={self.ids.next()[:8]}"
        )
        self._cash_row("Deposit", None, _moment(day, self.rng, (7, 22)), amount, comment)

    def buy(self, instrument: Instrument, day: date, budget: float) -> None:
        if day > self.end:
            return
        price = price_usd(instrument, day, self.start)
        unit_cost = self._to_account(price, day, fee=True)
        budget = min(budget, self.ledger.cash)
        if instrument.category in ("ETF", "ETC"):
            volume = round(budget / unit_cost, self.rng.choice([2, 3, 4]))
            volume = math.floor(volume * 10_000) / 10_000
        else:
            volume = float(int(budget // unit_cost))
        if volume <= 0:
            return
        cost = round(volume * unit_cost, 2)
        if cost > self.ledger.cash:
            return
        position = _Position(
            instrument, self.ids.next(), _moment(day, self.rng, (14, 20)), volume, price, cost, self._fx(day)
        )
        self.ledger.positions.append(position)
        self._cash_row(
            "Stock purchase", instrument, position.opened, -cost,
            f"OPEN BUY {instrument.ticker} {volume:g} @ {price:.2f}", position.position_id,
        )

    def sell(self, day: date) -> None:
        """Close one whole single-stock position held for at least a month (ASSUMED format, Q-006)."""
        if day > self.end:
            return
        candidates = [
            p for p in self.ledger.positions
            if p.instrument.category == "STOCK" and (day - p.opened.date()).days >= 30
        ]
        if not candidates:
            return
        p = self.rng.choice(candidates)
        price = price_usd(p.instrument, day, self.start)
        sale = round(self._to_account(p.volume * price, day, fee=False), 2)
        profit = round(sale - p.cost, 2)
        closed_at = _moment(day, self.rng, (14, 20))
        self.ledger.positions.remove(p)
        self._cash_row(
            "Stock sale", p.instrument, closed_at, sale,
            f"CLOSE BUY {p.instrument.ticker} {p.volume:g} @ {price:.2f}", p.position_id,
        )
        self.ledger.closed.append([
            p.instrument.name, p.instrument.ticker, p.instrument.category, "BUY", p.volume, p.price, p.opened,
            price, closed_at, schema.PRODUCT, profit, profit, p.cost, sale, None, None, 0.0, None, None, None,
            round(p.fx_open, 4), round(self._fx(day), 4), None, p.position_id, None,
        ])

    def dividends(self, month: date) -> None:
        pay_day = _business_day(month + timedelta(days=14))
        if pay_day > self.end:
            return
        for instrument in STOCKS.values():
            moment = _moment(pay_day, self.rng, (6, 8))
            # Shares held when the dividend is booked (a simplification of the record date).
            shares = sum(p.volume for p in self.ledger.positions if p.instrument is instrument and p.opened < moment)
            if not instrument.dividend_per_share or shares <= 0:
                continue
            gross_usd = shares * instrument.dividend_per_share
            gross = round(self._to_account(gross_usd, pay_day, fee=False), 2)
            if round(gross * 0.15, 2) < 0.01:  # too small to show both rows
                continue
            dps = f"{instrument.dividend_per_share:.2f}"
            self._cash_row("Dividend", instrument, moment, gross, f"{instrument.ticker} USD {dps}/ SHR")
            self._cash_row("Withholding tax", instrument, moment, -round(gross * 0.15, 2),
                           f"{instrument.ticker} USD WHT 15%")

    def interest(self, month: date, booked: date) -> None:
        if booked > self.end or self.ledger.cash <= 0:
            return
        interest = round(self.ledger.cash * 0.025 / 12, 2)
        if interest < 0.01:
            return
        label = f"{month:%Y-%m}"
        moment = _moment(booked, self.rng, (1, 3))
        self._cash_row("Free funds interest", None, moment, interest, f"Free-funds Interest {label}")
        if not self.account.tax_wrapper:
            self._cash_row("Free funds interest tax", None, moment, -round(interest * 0.19, 2),
                           f"Free-funds Interest Tax {label}")

    def run(self) -> _Ledger:
        month = date(self.start.year, self.start.month, 1)
        while month <= self.end:
            deposit_day = _business_day(month + timedelta(days=self.rng.randint(0, 4)))
            if deposit_day <= self.end:
                self.deposit(deposit_day)
                # Monthly ETF plan: most of the deposit, split between the account's ETFs.
                etf_budget = self.account.monthly_deposit * 0.75 / len(self.account.etfs)
                for ticker in self.account.etfs:
                    self.buy(ETFS[ticker], _business_day(deposit_day + timedelta(days=self.rng.randint(1, 3))),
                             etf_budget)
            # A few single-stock buys a year, from the cash that piles up.
            if self.rng.random() < self.account.stocks_per_year / 12:
                stock = self.rng.choice(list(STOCKS.values()))
                day = _business_day(month + timedelta(days=self.rng.randint(8, 25)))
                self.buy(stock, day, self.ledger.cash * self.rng.uniform(0.5, 0.9))
            # Now and then take profit (or cut a loss) on one stock position.
            if self.rng.random() < 1.5 / 12:
                self.sell(_business_day(month + timedelta(days=self.rng.randint(10, 27))))
            if month.month in (2, 5, 8, 11):
                self.dividends(month)
            next_month = (month + timedelta(days=32)).replace(day=1)
            self.interest(month, next_month)
            month = next_month
        self.ledger.cash_rows.sort(key=lambda row: row[4])
        self.ledger.closed.sort(key=lambda row: row[8])
        return self.ledger


# --------------------------------------------------------------------- workbook


def _period_rows(start: date, end: date) -> list[list]:
    return [
        # The real export gives local (Polish) midnight expressed in UTC, e.g. 22:00 the day
        # before in summer, and the moment of the export as the end.
        [schema.DATE_FROM_LABEL, _warsaw_midnight_utc(start)],
        [schema.DATE_TO_LABEL, datetime.combine(end, datetime.min.time()).replace(hour=9, minute=30, second=0)],
    ]


def _last_sunday(year: int, month: int) -> date:
    day = date(year, month, 31)
    return day - timedelta(days=(day.weekday() + 1) % 7)


def _warsaw_midnight_utc(day: date) -> datetime:
    """Midnight in Poland as a naive UTC datetime (CEST from the last Sunday of March to that of October)."""
    summer = _last_sunday(day.year, 3) <= day < _last_sunday(day.year, 10)
    return datetime.combine(day, datetime.min.time()) - timedelta(hours=2 if summer else 1)


def _write_closed_positions(ws, account: AccountFile, start: date, end: date, ledger: _Ledger) -> None:
    ws.append([schema.ACCOUNT_NUMBER_LABEL, account.number])
    ws.append([schema.CLOSED_POSITIONS.name])
    for row in _period_rows(start, end):
        ws.append(row)
    ws.append(list(schema.CLOSED_POSITIONS.columns))
    for row in ledger.closed:
        ws.append(row)
    # Seen in the real export (with no closed positions): a row with only "Profit/loss" in A.
    # Placing the sum under Profit/Loss is an assumption.
    total = round(sum(row[10] for row in ledger.closed), 2) if ledger.closed else None
    ws.append([schema.CLOSED_TOTAL_ROW] + [None] * 9 + [total])


# Styling seen in the real export: Calibri everywhere, black header bars with white bold
# text, bold sheet title, a beige note row, bold instrument summary rows in Open
# Positions, green/red for positive/negative money figures.
_FONT = "Calibri"
_HEADER_FILL = PatternFill("solid", fgColor="000000")
_NOTE_FILL = PatternFill("solid", fgColor="FFF2CC")
_GAIN, _LOSS = "00B050", "FF0000"
_SIGNED_COLUMNS = {
    schema.CLOSED_POSITIONS.name: ("Profit/Loss", "Gross Profit"),
    schema.CASH_OPERATIONS.name: ("Amount",),
    schema.OPEN_POSITIONS.name: ("Net Profit %", "Net Profit", "Gross Profit"),
}


def _font(*, bold: bool = False, italic: bool = False, color: str | None = None) -> Font:
    return Font(name=_FONT, size=11, bold=bold, italic=italic, color=color)


def _style_bar(ws, row: int, width: int) -> None:
    for column in range(1, width + 1):
        cell = ws.cell(row=row, column=column)
        cell.fill, cell.font = _HEADER_FILL, _font(bold=True, color="FFFFFF")


def _style_sheet(ws, layout: schema.SheetLayout) -> None:
    # Calibri on every used cell first; the rules below only add weight and colour.
    for row in ws.iter_rows():
        for cell in row:
            cell.font = _font()
    if ws.max_row < layout.header_row:
        return
    ws.cell(row=2, column=1).font = _font(bold=True)
    _style_bar(ws, layout.header_row, len(layout.columns))

    summary_rows: set[int] = set()
    if layout is schema.OPEN_POSITIONS:
        _style_bar(ws, 4, 4)
        for column in range(1, 5):
            ws.cell(row=8, column=column).fill = _NOTE_FILL
        ws.cell(row=8, column=1).font = _font(bold=True)
        ws.cell(row=8, column=2).font = _font(italic=True)
        category = layout.columns.index("Category") + 1
        summary_rows = {
            row for row in range(layout.header_row + 1, ws.max_row + 1)
            if ws.cell(row=row, column=category).value is not None
        }

    signed = {layout.columns.index(name) + 1 for name in _SIGNED_COLUMNS.get(layout.name, ())}
    for row in range(layout.header_row + 1, ws.max_row + 1):
        bold = row in summary_rows  # only instrument summary rows, "My Trades" included
        for column in range(1, len(layout.columns) + 1):
            cell = ws.cell(row=row, column=column)
            color = None
            if column in signed and isinstance(cell.value, (int, float)) and cell.value:
                color = _GAIN if cell.value > 0 else _LOSS
            if bold or color:
                cell.font = _font(bold=bold, color=color)


def _format_sheet(ws) -> None:
    """Readable in Excel: full date-times and columns wide enough for their content."""
    widths: dict[int, int] = {}
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is None:
                continue
            if isinstance(cell.value, datetime):
                cell.number_format = "yyyy-mm-dd hh:mm:ss"
                length = 19
            else:
                length = len(str(cell.value))
            widths[cell.column] = max(widths.get(cell.column, 0), length)
    for column, length in widths.items():
        ws.column_dimensions[get_column_letter(column)].width = min(length + 2, 45)


def _write_cash_operations(ws, account: AccountFile, start: date, end: date, ledger: _Ledger) -> None:
    ws.append([schema.ACCOUNT_NUMBER_LABEL, account.number])
    ws.append([schema.CASH_OPERATIONS.name])
    for row in _period_rows(start, end):
        ws.append(row)
    ws.append(list(schema.CASH_OPERATIONS.columns))
    for row in ledger.cash_rows:
        ws.append(row)
    total = round(sum(row[5] for row in ledger.cash_rows), 2)
    ws.append([schema.CASH_TOTAL_ROW, None, None, None, None, total, None, None, None, None])


def _write_open_positions(ws, account: AccountFile, start: date, end: date, ledger: _Ledger) -> None:
    fx = 1.0 if account.currency == "USD" else usd_to(account.currency, end)
    rows, total_value, total_profit = [], 0.0, 0.0
    for instrument in INSTRUMENTS.values():
        held = [p for p in ledger.positions if p.instrument is instrument]
        if not held:
            continue
        price = price_usd(instrument, end, start)
        position_rows = []
        for p in held:
            p_value = round(p.volume * price * fx, 2)
            p_profit = round(p_value - p.cost, 2)
            position_rows.append([
                schema.PRODUCT, p.position_id, instrument.ticker, None, "BUY", p.volume, p_value, price, p.price,
                p.opened, None, None, round(p_profit / p.cost * 100, 2), p_profit, p_profit, None, None, None, None,
            ])
        # The summary row is the sum of its positions, to the cent.
        volume = round(sum(p.volume for p in held), 4)
        cost = round(sum(p.cost for p in held), 2)
        value = round(sum(r[6] for r in position_rows), 2)
        profit = round(sum(r[13] for r in position_rows), 2)
        avg_open = round(sum(p.volume * p.price for p in held) / volume, 2)
        rows.append([
            schema.PRODUCT, instrument.name, instrument.ticker, instrument.category, None, volume, value, None,
            avg_open, None, None, None, round(profit / cost * 100, 2), profit, profit, None, None, None, None,
        ])
        rows.extend(position_rows)
        total_value += value
        total_profit += profit

    report_time = datetime.combine(end, datetime.min.time()).replace(hour=21, minute=5, second=17)
    ws.append([schema.ACCOUNT_NUMBER_LABEL, account.number])
    ws.append([schema.OPEN_POSITIONS.name])
    # The label in row 3 was masked in the report: placeholder. Rows 4 and 8 are confirmed.
    ws.append(["Data as of report generation", report_time])
    ws.append(["Product", "Metric", "Amount", "Currency"])
    ws.append([schema.PRODUCT, "Open position value", round(total_value, 2), account.currency])
    ws.append([schema.PRODUCT, "Open position profit", round(total_profit, 2), account.currency])
    ws.append([])
    ws.append(["Note", "Summary values and open positions are shown as of the report generation time"])
    ws.append(list(schema.OPEN_POSITIONS.columns))
    for row in rows:
        ws.append(row)


def write_mock_export(
    root: Path,
    *,
    start: date = date(2024, 11, 1),
    end: date = date(2026, 11, 13),
    seed: int = 7,
) -> list[Path]:
    """Create <root>/<folder>/<PREFIX>_<number>_<from>_<to>.xlsx files. Returns their paths."""
    rng = random.Random(seed)
    ids = _Ids(rng)
    written = []
    for account in ACCOUNTS:
        ledger = _Simulation(account, start, end, rng, ids).run()
        wb = Workbook()
        sheets = [wb.active] + [wb.create_sheet() for _ in schema.SHEETS[1:]]
        for ws, layout in zip(sheets, schema.SHEETS, strict=True):
            ws.title = layout.name
        _write_closed_positions(sheets[0], account, start, end, ledger)
        _write_cash_operations(sheets[1], account, start, end, ledger)
        _write_open_positions(sheets[2], account, start, end, ledger)
        for ws, layout in zip(sheets, schema.SHEETS, strict=True):
            _format_sheet(ws)
            _style_sheet(ws, layout)

        folder = root / account.folder
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{account.prefix}_{account.number}_{start:%Y-%m-%d}_{end:%Y-%m-%d}.xlsx"
        wb.save(path)
        written.append(path)
    return written
