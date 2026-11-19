"""Polish retail treasury bonds: interest periods, rates and value per day (R-008, D-026).

Pure functions; no database, no network. The rules follow the issue letters ("list emisyjny")
of the Ministry of Finance and were checked against the official interest tables ("tabela
odsetkowa") published on obligacjeskarbowe.pl:

- Nominal 100 zł. Interest periods are anchored on the purchase date: period k starts on
  purchase + (k-1) years (or months), with the day clamped to the end of a shorter month
  (a bond bought on 30.11 starts a monthly period on 28.02, the next on 30.03).
- Accrual inside a period is actual/actual: interest = base * r * (months / 12) * a / D, where
  `a` counts the days from the period start (inclusive) to the valuation day (exclusive) and
  `D` is the length of the period in days. The value is rounded to the grosz per bond.
- Capitalising types (EDO, ROS, ROD, TOS, OTS): base = 100 * prod(1 + r_j) over the finished
  periods, without intermediate rounding (the official tables match this, also for TOS whose
  letter mentions a rounded base).
- Coupon types (COI yearly; ROR, DOR monthly): base is always 100; the coupon
  round(100 * r * months / 12, 2) is paid on the last day of every period.
- Floating rates from period 2:
  - EDO, COI, ROS, ROD: CPI y/y announced by GUS in the month before the period starts
    (the figure for two months earlier), floored at 0, plus the series margin;
  - ROR, DOR: NBP reference rate in force on the 10th working day before the first day of
    the calendar month in which the period starts (floored at 0), plus the margin.
  Official rates (shipped from the Ministry of Finance file, or entered by the user) win over
  computed ones; a computed rate is labelled as such. If the CPI needed is not known, only the
  margin is used (the inflation part is never invented) and the period is flagged.
- Early redemption: value minus the fee per bond. For EDO, ROS, ROD and TOS the fee never
  exceeds the accrued interest; for COI, ROR and DOR only in the first period; OTS pays back
  the nominal value without interest. 19% tax on the interest left after the fee, none on
  IKE/IKZE.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

NOMINAL = Decimal(100)
TAX_RATE = Decimal("0.19")
CENT = Decimal("0.01")
HUNDRED = Decimal(100)


@dataclass(frozen=True)
class BondType:
    code: str
    term_months: int
    period_months: int
    coupon: bool  # True: interest paid out every period; False: capitalised and paid at maturity
    index: str | None  # None (fixed), "cpi" or "reference" (NBP reference rate)
    fee_cap: str  # "interest": fee <= accrued interest; "first_period": only in period 1; "no_interest"
    name: str  # Polish UI label


TYPES: dict[str, BondType] = {
    "OTS": BondType("OTS", 3, 3, False, None, "no_interest", "3-miesięczne stałoprocentowe"),
    "ROR": BondType("ROR", 12, 1, True, "reference", "first_period", "roczne zmiennoprocentowe"),
    "DOR": BondType("DOR", 24, 1, True, "reference", "first_period", "2-letnie zmiennoprocentowe"),
    "TOS": BondType("TOS", 36, 12, False, None, "interest", "3-letnie stałoprocentowe"),
    "COI": BondType("COI", 48, 12, True, "cpi", "first_period", "4-letnie indeksowane inflacją"),
    "ROS": BondType("ROS", 72, 12, False, "cpi", "interest", "6-letnie rodzinne"),
    "EDO": BondType("EDO", 120, 12, False, "cpi", "interest", "10-letnie emerytalne"),
    "ROD": BondType("ROD", 144, 12, False, "cpi", "interest", "12-letnie rodzinne"),
}

# Where a period's rate came from.
RATE_FIRST = "first"  # period 1, from the issue letter
RATE_FIXED = "fixed"  # fixed-rate bond
RATE_OFFICIAL = "official"  # published by the Ministry of Finance (shipped file or the user's YAML)
RATE_CPI = "cpi"  # computed: GUS CPI y/y + margin
RATE_REFERENCE = "reference"  # computed: NBP reference rate + margin
RATE_MARGIN_ONLY = "margin_only"  # the CPI needed is not known yet: margin only, flagged
COMPUTED_SOURCES = (RATE_CPI, RATE_REFERENCE, RATE_MARGIN_ONLY)


@dataclass(frozen=True)
class SeriesParams:
    series: str
    type: str
    first_rate: Decimal  # % a year
    margin: Decimal | None  # p.p. over CPI or the NBP reference rate; None for fixed-rate bonds
    early_fee: Decimal  # zł per bond
    maturity_interest: Decimal | None = None  # OTS: interest per bond fixed in the issue letter, paid at maturity

    @property
    def kind(self) -> BondType:
        return TYPES[self.type]


@dataclass(frozen=True)
class MarketData:
    """Everything the floating rates depend on."""

    official: dict[tuple[str, int], Decimal] = field(default_factory=dict)  # (series, period) -> %
    cpi_yoy: dict[tuple[int, int], Decimal] = field(default_factory=dict)  # (year, month) -> index, 102.6
    reference: tuple[tuple[date, Decimal], ...] = ()  # (in force from, %), sorted by date


@dataclass(frozen=True)
class Period:
    number: int
    start: date
    end: date  # exclusive: the next period starts here (and the coupon is paid here)
    rate: Decimal  # % a year
    source: str
    note: str | None = None  # why a computed rate may differ from the official one

    @property
    def days(self) -> int:
        return (self.end - self.start).days


@dataclass(frozen=True)
class Payment:
    """Money paid to the holder for one bond: a coupon, or the redemption at maturity."""

    date: date
    amount: Decimal  # gross, per bond (includes the 100 zł nominal at maturity)
    interest: Decimal  # the taxable part, per bond
    final: bool


# ------------------------------------------------------------------------------- calendar


def add_months(day: date, months: int) -> date:
    """Same day `months` later; clamped to the end of a shorter month (30.11 + 3 months = 28.02)."""
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def maturity(series_type: str, purchase: date) -> date:
    return add_months(purchase, TYPES[series_type].term_months)


def series_maturity_month(series: str) -> tuple[int, int]:
    """(year, month) of redemption encoded in the code: EDO0736 -> (2036, 7)."""
    return 2000 + int(series[5:7]), int(series[3:5])


def easter_sunday(year: int) -> date:
    """Gregorian Easter Sunday (anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


def polish_holidays(year: int) -> set[date]:
    """Statutory days off in Poland (ustawa o dniach wolnych od pracy), including 24.12 from 2025."""
    easter = easter_sunday(year)
    days = {
        date(year, 1, 1), date(year, 5, 1), date(year, 5, 3), date(year, 8, 15), date(year, 11, 1),
        date(year, 11, 11), date(year, 12, 25), date(year, 12, 26),
        easter, easter + timedelta(days=1), easter + timedelta(days=49), easter + timedelta(days=60),
    }
    if year >= 2011:
        days.add(date(year, 1, 6))
    if year >= 2025:
        days.add(date(year, 12, 24))
    return days


def working_days_before(day: date, count: int) -> date:
    """The `count`-th working day before `day` (Saturdays, Sundays and holidays do not count)."""
    current, found = day, 0
    while found < count:
        current -= timedelta(days=1)
        if current.weekday() < 5 and current not in polish_holidays(current.year):
            found += 1
    return current


# ---------------------------------------------------------------------------------- rates


def _months_back(year: int, month: int, back: int) -> tuple[int, int]:
    index = year * 12 + month - 1 - back
    return index // 12, index % 12 + 1


def _reference_on(reference: tuple[tuple[date, Decimal], ...], day: date) -> Decimal | None:
    rate = None
    for since, value in reference:
        if since <= day:
            rate = value
        else:
            break
    return rate


def period_rate(params: SeriesParams, number: int, start: date, data: MarketData) -> tuple[Decimal, str, str | None]:
    """Rate (% a year) of period `number` starting on `start`, with its source and an optional note."""
    kind = params.kind
    if number == 1:
        return params.first_rate, (RATE_FIXED if kind.index is None else RATE_FIRST), None
    if kind.index is None:
        return params.first_rate, RATE_FIXED, None
    official = data.official.get((params.series, number))
    if official is not None:
        return official, RATE_OFFICIAL, None
    margin = params.margin if params.margin is not None else Decimal(0)
    if kind.index == "cpi":
        year, month = _months_back(start.year, start.month, 2)
        yoy = data.cpi_yoy.get((year, month))
        if yoy is None:
            return margin, RATE_MARGIN_ONLY, f"brak CPI za {month:02d}.{year}: przyjęto samą marżę"
        note = None
        if month == 1:
            note = "GUS koryguje CPI za styczeń po ogłoszeniu; oficjalna stopa może się nieco różnić"
        return max(Decimal(0), yoy - HUNDRED) + margin, RATE_CPI, note
    fixing = working_days_before(date(start.year, start.month, 1), 10)
    reference = _reference_on(data.reference, fixing)
    if reference is None:
        return margin, RATE_MARGIN_ONLY, f"brak stopy referencyjnej NBP na {fixing:%d.%m.%Y}: przyjęto samą marżę"
    return max(Decimal(0), reference) + margin, RATE_REFERENCE, None


def schedule(params: SeriesParams, purchase: date, data: MarketData, *, until: date | None = None) -> list[Period]:
    """Interest periods of a bond bought on `purchase`; only those starting on or before `until`."""
    kind = params.kind
    count = kind.term_months // kind.period_months
    periods = []
    for number in range(1, count + 1):
        start = add_months(purchase, (number - 1) * kind.period_months)
        if until is not None and start > until:
            break
        end = add_months(purchase, number * kind.period_months)
        rate, source, note = period_rate(params, number, start, data)
        periods.append(Period(number, start, end, rate, source, note))
    return periods


# ---------------------------------------------------------------------------------- value


def _round(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _growth(period: Period, period_months: int, days: int) -> Decimal:
    """1 + interest of `days` days of the period, as a fraction of its base."""
    return 1 + period.rate / HUNDRED * Decimal(period_months) / 12 * Decimal(days) / Decimal(period.days)


def _base(periods: list[Period], number: int, kind: BondType) -> Decimal:
    """Value per bond at the start of period `number` (before rounding)."""
    if kind.coupon:
        return NOMINAL
    base = NOMINAL
    for period in periods[: number - 1]:
        base *= _growth(period, kind.period_months, period.days)
    return base


def _value(params: SeriesParams, periods: list[Period], period: Period, days: int) -> Decimal:
    """Unrounded value per bond `days` into `period`."""
    if params.maturity_interest is not None:  # OTS: the letter fixes the interest amount; accrue it evenly
        return NOMINAL + params.maturity_interest * Decimal(days) / Decimal(period.days)
    return _base(periods, period.number, params.kind) * _growth(period, params.kind.period_months, days)


def _current(periods: list[Period], day: date) -> Period | None:
    for period in periods:
        if period.start <= day < period.end:
            return period
    return None


def gross_value(params: SeriesParams, periods: list[Period], day: date) -> Decimal | None:
    """Nominal plus accrued (and capitalised) interest per bond on `day`; None outside the bond's life."""
    period = _current(periods, day)
    if period is None:
        return None
    return _round(_value(params, periods, period, (day - period.start).days))


def early_redemption(params: SeriesParams, periods: list[Period], day: date) -> Decimal | None:
    """Value per bond after the early-redemption fee (before tax), as the issue letters define it."""
    period = _current(periods, day)
    if period is None:
        return None
    kind = params.kind
    if kind.fee_cap == "no_interest":
        return NOMINAL
    value = _round(_value(params, periods, period, (day - period.start).days) - params.early_fee)
    if kind.fee_cap == "interest" or period.number == 1:
        value = max(value, NOMINAL)  # the fee takes at most the accrued interest
    return value


def tax(interest: Decimal, quantity: int, *, tax_free: bool) -> Decimal:
    """19% flat tax on interest for a lot (rounded to the grosz); none on IKE/IKZE."""
    if tax_free or interest <= 0:
        return Decimal(0)
    return _round(interest * quantity * TAX_RATE)


def payments(params: SeriesParams, periods: list[Period]) -> list[Payment]:
    """Coupons and the redemption, per bond, for the periods given (all of them for the full life)."""
    kind = params.kind
    count = kind.term_months // kind.period_months
    paid = []
    if kind.coupon:
        for period in periods:
            coupon = _round(NOMINAL * period.rate / HUNDRED * Decimal(kind.period_months) / 12)
            final = period.number == count
            paid.append(Payment(period.end, coupon + (NOMINAL if final else 0), coupon, final))
    elif len(periods) == count:
        value = _round(_value(params, periods, periods[-1], periods[-1].days))
        paid.append(Payment(periods[-1].end, value, value - NOMINAL, True))
    return paid


def paid_out(params: SeriesParams, purchase: date, data: MarketData, day: date) -> list[Payment]:
    """Payments per bond already made on or before `day` (coupons; the redemption once it happened)."""
    return [p for p in payments(params, schedule(params, purchase, data, until=day)) if p.date <= day]


# ------------------------------------------------------------------------------- per lot


@dataclass(frozen=True)
class LotStatus:
    """A lot of bonds on one day: what it is worth and what an early redemption would pay."""

    series: str
    type: str
    quantity: int
    purchase: date
    maturity: date
    period: Period | None  # None after maturity
    gross: Decimal  # per bond
    early: Decimal  # per bond, after the fee, before tax
    payout: Decimal  # whole lot, after the fee and tax
    tax: Decimal  # whole lot

    @property
    def accrued(self) -> Decimal:
        return self.gross - NOMINAL


def lot_status(params: SeriesParams, purchase: date, quantity: int, day: date, data: MarketData, *,
               tax_free: bool = False) -> LotStatus | None:
    """Status of a lot on `day`; None before the purchase or from the redemption day on."""
    periods = schedule(params, purchase, data, until=day)
    period = _current(periods, day)
    if period is None or day < purchase:
        return None
    gross = gross_value(params, periods, day)
    early = early_redemption(params, periods, day)
    lot_tax = tax(early - NOMINAL, quantity, tax_free=tax_free)
    return LotStatus(params.series, params.type, quantity, purchase, maturity(params.type, purchase), period,
                     gross, early, early * quantity - lot_tax, lot_tax)


# --------------------------------------------------------------------------- daily values


@dataclass
class BondValuation:
    daily: pd.DataFrame  # date, account_id, series, qty, value (PLN, gross)
    flows: pd.DataFrame  # date, account_id, type (DEPOSIT | WITHDRAWAL), amount (PLN), series
    warnings: list[str]


def value_lots(lots: pd.DataFrame, params: dict[str, SeriesParams], data: MarketData, end: date,
               tax_free_accounts: set[str] | frozenset[str] = frozenset()) -> BondValuation:
    """Daily gross value per lot and the external flows of every lot up to `end`.

    `lots`: account_id, series, purchase_date (Timestamp), quantity. A purchase is a deposit
    into the bonds account; coupons and redemption proceeds (net of the 19% tax, except on
    IKE/IKZE) are withdrawals, because they are paid to a bank account outside the tracked
    portfolio. On the day of a payment the paid-out part is no longer in the value.
    """
    rows: list[tuple] = []
    flows: list[tuple] = []
    warnings: set[str] = set()
    for lot in lots.itertuples(index=False):
        series = lot.series
        p = params.get(series)
        if p is None:
            warnings.add(f"{series}: nieznana seria obligacji, pominięta w wycenie")
            continue
        purchase = pd.Timestamp(lot.purchase_date).date()
        if purchase > end:
            continue
        quantity = int(lot.quantity)
        tax_free = lot.account_id in tax_free_accounts
        periods = schedule(p, purchase, data, until=end)
        for period in periods:
            if period.source in COMPUTED_SOURCES and period.note:
                warnings.add(f"{series}, okres {period.number} od {period.start:%d.%m.%Y}: {period.note}")
        flows.append((pd.Timestamp(purchase), lot.account_id, "DEPOSIT", float(NOMINAL * quantity), series))
        for payment in payments(p, periods):
            if payment.date > end:
                continue
            net = payment.amount * quantity - tax(payment.interest, quantity, tax_free=tax_free)
            flows.append((pd.Timestamp(payment.date), lot.account_id, "WITHDRAWAL", -float(net), series))
        for period in periods:
            last = min(period.end - timedelta(days=1), end)
            day = period.start
            while day <= last:
                value = _round(_value(p, periods, period, (day - period.start).days))
                rows.append((pd.Timestamp(day), lot.account_id, series, quantity, float(value * quantity)))
                day += timedelta(days=1)
    daily = pd.DataFrame(rows, columns=["date", "account_id", "series", "qty", "value"])
    if not daily.empty:
        daily = daily.groupby(["date", "account_id", "series"], as_index=False)[["qty", "value"]].sum()
    return BondValuation(
        daily=daily,
        flows=pd.DataFrame(flows, columns=["date", "account_id", "type", "amount", "series"]),
        warnings=sorted(warnings),
    )


# ------------------------------------------------------------------------------- loading


def params_from_frame(frame: pd.DataFrame) -> dict[str, SeriesParams]:
    """`series`, `type`, `first_rate`, `margin`, `early_fee`, `maturity_interest` rows -> SeriesParams by code."""
    out = {}
    for row in frame.to_dict("records"):
        out[row["series"]] = SeriesParams(row["series"], row["type"], _dec(row["first_rate"]),
                                          _optional(row.get("margin")), _dec(row["early_fee"]),
                                          _optional(row.get("maturity_interest")))
    return out


def _optional(value) -> Decimal | None:
    return None if value is None or pd.isna(value) else _dec(value)


def market_data(rates: pd.DataFrame, cpi: pd.DataFrame, reference: pd.DataFrame) -> MarketData:
    """rates: series, period, rate; cpi: year, month, yoy; reference: date_from, rate."""
    official = {(r.series, int(r.period)): _dec(r.rate) for r in rates.itertuples(index=False)}
    cpi_yoy = {(int(r.year), int(r.month)): _dec(r.yoy) for r in cpi.itertuples(index=False) if pd.notna(r.yoy)}
    ref = tuple(sorted((pd.Timestamp(r.date_from).date(), _dec(r.rate)) for r in reference.itertuples(index=False)))
    return MarketData(official, cpi_yoy, ref)


def _dec(value) -> Decimal:
    """Exact decimal of a value read from CSV/SQLite (floats go through their shortest repr)."""
    return Decimal(str(value))
