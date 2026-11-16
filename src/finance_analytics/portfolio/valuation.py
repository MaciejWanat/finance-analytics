"""Daily holdings and their value in PLN (D-004, D-008, D-009, D-019).

Pipeline, all on a calendar-day index from the first event to `end`:
1. quantity per (account, instrument): +volume on the day a lot opens, -volume on
   the day it closes (a lot closed on day d is not held at the end of d);
2. price per instrument: Yahoo close (split-adjusted), carried forward over days
   without trading;
3. FX: NBP mid rate, the last one published on or before the day (D-008);
4. cash per account: running sum of the cash ledger, in the account currency;
5. treasury bonds (D-026): gross value per (account, series) from `portfolio.bonds`, in PLN;
6. cash at banks (D-027): each balance snapshot holds until the next one; value = balance x NBP rate.

`load_inputs` reads SQLite; `value_portfolio` is a pure function of the inputs.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from finance_analytics.portfolio import bonds as bond_math

MODEL_VERSION = 5  # bump when Valuation's fields or rules change, so UI caches are not reused
SPLIT_TOLERANCE = 0.25  # how close open price / adjusted close must be to the split ratio
NO_RATES = "Brak kursów NBP dla"  # start of the warning for a currency without rates (the UI checks for it)


@dataclass
class BondInputs:
    lots: pd.DataFrame  # account_id, series, purchase_date (datetime), quantity
    series: pd.DataFrame  # series, type, first_rate, margin, early_fee, maturity_interest (OTS)
    rates: pd.DataFrame  # series, period, rate: official rates of later interest periods
    cpi: pd.DataFrame  # year, month, yoy (index points, same month a year earlier = 100)
    reference: pd.DataFrame  # date_from, rate: NBP reference rate

    @classmethod
    def empty(cls) -> BondInputs:
        return cls(
            lots=pd.DataFrame(columns=["account_id", "series", "purchase_date", "quantity"]).astype(
                {"purchase_date": "datetime64[ns]"}),
            series=pd.DataFrame(columns=["series", "type", "first_rate", "margin", "early_fee",
                                         "maturity_interest"]),
            rates=pd.DataFrame(columns=["series", "period", "rate"]),
            cpi=pd.DataFrame(columns=["year", "month", "yoy"]),
            reference=pd.DataFrame(columns=["date_from", "rate"]),
        )

    def params(self) -> dict[str, bond_math.SeriesParams]:
        return bond_math.params_from_frame(self.series)

    def market(self) -> bond_math.MarketData:
        return bond_math.market_data(self.rates, self.cpi, self.reference)


@dataclass
class Inputs:
    lots: pd.DataFrame  # account_id, instrument_id, symbol, name, asset_class, ticker, volume, open_date,
    #                     close_date, open_price, purchase_value
    ledger: pd.DataFrame  # account_id, date, type, amount
    accounts: pd.DataFrame  # account_id, alias, currency, tax_wrapper
    prices: pd.DataFrame  # ticker, date, close
    currencies: dict[str, str]  # ticker -> price currency
    fx: pd.DataFrame  # currency, date, mid
    splits: pd.DataFrame  # ticker, date, ratio
    bonds: BondInputs = field(default_factory=BondInputs.empty)
    cash_snapshots: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame({"account_id": pd.Series(dtype=object),
                                              "date": pd.Series(dtype="datetime64[ns]"),
                                              "balance": pd.Series(dtype=float)}))  # bank balances (D-027)


@dataclass
class Valuation:
    daily: pd.DataFrame  # long: date, account_id, account, kind, symbol, name, asset_class, currency,
    #                      qty, price, fx, value_local, value_pln, priced
    flows: pd.DataFrame  # external cash flows: date, account_id, amount, amount_pln
    lots: pd.DataFrame  # lots with cost_pln (FX on the opening day) and adjusted volume
    warnings: list[str] = field(default_factory=list)
    prices: pd.DataFrame = field(default_factory=pd.DataFrame)  # calendar x ticker, price currency (carried)
    fx: pd.DataFrame = field(default_factory=pd.DataFrame)  # calendar x currency, PLN per unit used for values
    currencies: dict[str, str] = field(default_factory=dict)  # ticker -> price currency

    @property
    def total(self) -> pd.Series:
        return self.daily.groupby("date")["value_pln"].sum()


# ------------------------------------------------------------------------- load


def load_inputs(db_path: Path) -> Inputs:
    with closing(sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)) as conn:
        def q(sql: str) -> pd.DataFrame:
            return pd.read_sql_query(sql, conn)

        lots = q(
            """
            SELECT p.account_id, p.instrument_id, i.xtb_symbol AS symbol, i.name, i.asset_class,
                   i.yahoo_ticker AS ticker, p.volume, substr(p.open_time, 1, 10) AS open_date,
                   substr(p.close_time, 1, 10) AS close_date, p.open_price, p.purchase_value
            FROM positions p JOIN instruments i ON i.id = p.instrument_id
            """
        )
        ledger = q("SELECT account_id, substr(ts, 1, 10) AS date, type, amount FROM cash_ledger")
        accounts = q("SELECT id AS account_id, alias, currency, tax_wrapper FROM accounts")
        prices = q("SELECT ticker, date, close FROM prices")
        currencies = dict(conn.execute("SELECT ticker, currency FROM ticker_info").fetchall())
        fx = q("SELECT currency, date, mid FROM fx_rates")
        splits = q("SELECT ticker, date, value AS ratio FROM corporate_actions WHERE kind = 'SPLIT'")
        bonds = _load_bonds(q)
        cash_snapshots = _load_cash_snapshots(q)
    for frame, columns in ((lots, ["open_date", "close_date"]), (ledger, ["date"]), (prices, ["date"]),
                           (fx, ["date"]), (splits, ["date"]), (cash_snapshots, ["date"])):
        for column in columns:
            frame[column] = pd.to_datetime(frame[column])
    return Inputs(lots, ledger, accounts, prices, currencies, fx, splits, bonds, cash_snapshots)


def _load_bonds(q) -> BondInputs:
    """Bond tables (migration 0006) and the CPI; empty when the database predates them."""
    try:
        lots = q("SELECT account_id, series, purchase_date, quantity FROM bond_lots ORDER BY id")
        series = q("SELECT series, type, first_rate, margin, early_fee, maturity_interest FROM bond_series")
        rates = q("SELECT series, period, rate FROM bond_rates")
        reference = q("SELECT date_from, rate FROM bond_reference_rate ORDER BY date_from")
        cpi = q("SELECT year, month, yoy FROM cpi_monthly WHERE yoy IS NOT NULL")
    except (sqlite3.OperationalError, pd.errors.DatabaseError):
        return BondInputs.empty()
    lots["purchase_date"] = pd.to_datetime(lots["purchase_date"])
    return BondInputs(lots, series, rates, cpi, reference)


def _load_cash_snapshots(q) -> pd.DataFrame:
    """Bank balance snapshots (migration 0008); empty when the database predates them."""
    try:
        return q("SELECT account_id, date, balance FROM cash_snapshots ORDER BY account_id, date")
    except (sqlite3.OperationalError, pd.errors.DatabaseError):
        return pd.DataFrame({"account_id": pd.Series(dtype=object), "date": pd.Series(dtype=object),
                             "balance": pd.Series(dtype=float)})


def data_version(db_path: Path) -> tuple:
    """Cheap fingerprint of everything the valuation reads, for UI caching."""
    with closing(sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)) as conn:
        return conn.execute(
            """
            SELECT (SELECT MAX(imported_at) FROM source_files), (SELECT COUNT(*) FROM cash_ledger),
                   (SELECT COUNT(*) || '/' || COALESCE(SUM(quantity), 0) FROM bond_lots),
                   (SELECT COUNT(*) || MAX(year * 100 + month) FROM cpi_monthly),
                   (SELECT COUNT(*) || '/' || COALESCE(SUM(balance), 0) FROM cash_snapshots),
                   (SELECT COUNT(*) FROM positions), (SELECT COUNT(*) || MAX(date) FROM prices),
                   (SELECT COUNT(*) || MAX(date) FROM fx_rates), (SELECT MAX(fetched_at) FROM fetch_log),
                   (SELECT group_concat(alias) FROM accounts)
            """
        ).fetchone()


# ---------------------------------------------------------------------- compute


def _fx_table(fx: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """PLN per unit, by day and currency; last published rate carried forward."""
    wide = fx.pivot_table(index="date", columns="currency", values="mid", aggfunc="last")
    full = wide.reindex(wide.index.union(calendar)).sort_index().ffill()
    table = full.reindex(calendar).bfill()  # only fills days before the very first rate
    table["PLN"] = 1.0
    return table


def _adjust_for_splits(lots: pd.DataFrame, inputs: Inputs, warnings: list[str]) -> pd.DataFrame:
    """Express lot volumes in today's share count when a split happened after opening (Q-001).

    Yahoo prices are split-adjusted backwards. If the broker kept the pre-split volume
    (open price ~ split ratio x adjusted close on the opening day), multiply the volume
    by the ratio; if it already adjusted the lot, leave it.
    """
    lots = lots.copy()
    lots["volume_adj"] = lots["volume"]
    if inputs.splits.empty:
        return lots
    for index, lot in lots.iterrows():
        later = inputs.splits[(inputs.splits["ticker"] == lot["ticker"]) & (inputs.splits["date"] > lot["open_date"])]
        if later.empty:
            continue
        ratio = float(np.prod(later["ratio"]))
        series = inputs.prices[inputs.prices["ticker"] == lot["ticker"]].set_index("date")["close"].sort_index()
        before = series[series.index <= lot["open_date"]]
        if before.empty:
            warnings.append(f"{lot['symbol']}: split po otwarciu pozycji, ale brak ceny, żeby go sprawdzić")
            continue
        observed = lot["open_price"] / before.iloc[-1]
        if abs(observed / ratio - 1) <= SPLIT_TOLERANCE:
            lots.at[index, "volume_adj"] = lot["volume"] * ratio
            warnings.append(
                f"{lot['symbol']}: {lot['volume']:g} szt. kupione przed splitem {ratio:g}:1 liczone jako "
                f"{lot['volume'] * ratio:g} szt. (Q-001)"
            )
    return lots


def _bond_rows(inputs: Inputs, lots: pd.DataFrame, calendar: pd.DatetimeIndex, end: date, accounts: pd.DataFrame,
               warnings: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Daily rows (one per account and series) and external flows of the treasury bonds."""
    if lots.empty:
        return pd.DataFrame(), pd.DataFrame()
    wrappers = accounts["tax_wrapper"] if "tax_wrapper" in accounts.columns else pd.Series(dtype=object)
    tax_free = {account for account, wrapper in wrappers.items() if wrapper in ("IKE", "IKZE")}
    params = inputs.bonds.params()
    result = bond_math.value_lots(lots, params, inputs.bonds.market(), end, tax_free)
    warnings.extend(result.warnings)
    rows = result.daily[result.daily["date"].isin(calendar)]
    if rows.empty:
        return pd.DataFrame(), result.flows.assign(currency="PLN", amount_pln=result.flows["amount"])
    types = {code: p.type for code, p in params.items()}
    rows = rows.assign(
        kind="bond", symbol=rows["series"],
        name=[f"Obligacje {bond_math.TYPES[types[s]].name}" for s in rows["series"]],
        asset_class="bond", currency="PLN", price=rows["value"] / rows["qty"], fx=1.0,
        value_local=rows["value"], value_pln=rows["value"], priced=True,
    ).drop(columns=["series", "value"])
    flows = result.flows.assign(currency="PLN", amount_pln=result.flows["amount"])
    return rows, flows


def _bank_rows(snapshots: pd.DataFrame, accounts: pd.DataFrame, calendar: pd.DatetimeIndex,
               fx_value: pd.DataFrame, fx: pd.DataFrame, warnings: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Daily rows and external flows of the bank accounts (D-027).

    A balance holds from its snapshot until the next one; before the first snapshot the account does
    not exist. Every change of the balance (the first snapshot included) is an external flow: salary in,
    spending out. Rows are valued at the day's rate (live on the last day, like XTB cash); flows at NBP.
    """
    if snapshots.empty:
        return pd.DataFrame(), pd.DataFrame()
    frames, flow_frames = [], []
    for account_id, group in snapshots.groupby("account_id"):
        if account_id not in accounts.index:
            continue
        currency = accounts.loc[account_id, "currency"]
        if currency not in fx.columns:
            warnings.append(f"{NO_RATES} {currency}: wartości w tej walucie nie są wyceniane")
            continue
        steps = group.drop_duplicates("date", keep="last").set_index("date")["balance"].sort_index()
        balance = steps.reindex(steps.index.union(calendar)).ffill().reindex(calendar)
        balance = balance[balance.index >= steps.index[0]].round(2)
        rate = fx_value.loc[balance.index, currency].to_numpy()
        frame = pd.DataFrame({"date": balance.index, "account_id": account_id, "qty": balance.to_numpy(),
                              "price": 1.0, "currency": currency, "fx": rate})
        frame["value_local"] = frame["qty"]
        frame["value_pln"] = frame["value_local"] * frame["fx"]
        frames.append(frame)
        change = balance.diff()
        change.iloc[0] = balance.iloc[0]
        change = change[change != 0]
        flow_frames.append(pd.DataFrame({
            "account_id": account_id, "date": change.index, "type": "BANK", "amount": change.to_numpy(),
            "currency": currency, "amount_pln": change.to_numpy() * fx.loc[change.index, currency].to_numpy(),
        }))
    if not frames:
        return pd.DataFrame(), pd.DataFrame()
    rows = pd.concat(frames, ignore_index=True)
    rows = rows.assign(kind="cash", symbol="Gotówka", name="Gotówka", asset_class="cash", priced=True)
    return rows, pd.concat(flow_frames, ignore_index=True)


DAILY_COLUMNS = ["date", "account_id", "account", "kind", "symbol", "name", "asset_class", "currency", "qty",
                 "price", "fx", "value_local", "value_pln", "priced"]


def _empty_valuation(lots: pd.DataFrame, warnings: list[str]) -> Valuation:
    """Nothing to value up to `end` (no data yet, or nothing that can be valued): pages show a note."""
    return Valuation(daily=pd.DataFrame(columns=DAILY_COLUMNS),
                     flows=pd.DataFrame(columns=["date", "account_id", "type", "amount", "currency", "amount_pln"]),
                     lots=lots, warnings=sorted(set(warnings)))


def value_portfolio(
    inputs: Inputs,
    end: date,
    *,
    live_prices: dict[str, float] | None = None,
    live_fx: dict[str, float] | None = None,
) -> Valuation:
    """Value every day up to `end`.

    `live_prices` (ticker -> price) and `live_fx` (currency -> PLN per unit) come from
    online mode (D-021) and replace the last day's price and rate for the *value* only.
    Costs and flows keep using NBP rates.
    """
    warnings: list[str] = []
    accounts = inputs.accounts.set_index("account_id")
    bond_lots = inputs.bonds.lots[inputs.bonds.lots["purchase_date"] <= pd.Timestamp(end)]
    snapshots = inputs.cash_snapshots[inputs.cash_snapshots["date"] <= pd.Timestamp(end)]
    starts = [frame[column].min() for frame, column in ((inputs.lots, "open_date"), (inputs.ledger, "date"),
                                                        (bond_lots, "purchase_date"), (snapshots, "date"))
              if not frame.empty]
    if not starts or min(starts) > pd.Timestamp(end):
        return _empty_valuation(inputs.lots, warnings)
    calendar = pd.date_range(min(starts), pd.Timestamp(end), freq="D")
    fx = _fx_table(inputs.fx, calendar)

    def rate(currency: str) -> pd.Series:
        if currency not in fx.columns:
            warnings.append(f"{NO_RATES} {currency}: wartości w tej walucie nie są wyceniane")
            return pd.Series(np.nan, index=calendar)
        return fx[currency]

    # --- positions -----------------------------------------------------------------------------------
    lots = _adjust_for_splits(inputs.lots, inputs, warnings)
    lots["account_currency"] = lots["account_id"].map(accounts["currency"])
    lots["cost_pln"] = [
        value * rate(ccy).asof(day) if pd.notna(value) else np.nan
        for value, ccy, day in zip(lots["purchase_value"], lots["account_currency"], lots["open_date"], strict=True)
    ]
    opening = lots[["open_date", "account_id", "instrument_id", "volume_adj"]].rename(columns={"open_date": "date"})
    closing_ = lots.dropna(subset=["close_date"])[["close_date", "account_id", "instrument_id", "volume_adj"]]
    closing_ = closing_.rename(columns={"close_date": "date"}).assign(volume_adj=lambda d: -d["volume_adj"])
    deltas = pd.concat([opening, closing_])
    qty = (
        deltas.pivot_table(index="date", columns=["account_id", "instrument_id"], values="volume_adj", aggfunc="sum")
        .reindex(calendar, fill_value=0.0)
        .fillna(0.0)
        .cumsum()
        .round(8)
    )
    qty.index.name = "date"
    held = qty.stack(["account_id", "instrument_id"]).rename("qty").reset_index()
    held = held[held["qty"] > 0]

    info = lots.drop_duplicates("instrument_id").set_index("instrument_id")[
        ["symbol", "name", "asset_class", "ticker"]
    ]
    held = held.join(info, on="instrument_id")

    prices = inputs.prices.pivot_table(index="date", columns="ticker", values="close", aggfunc="last")
    prices = prices.reindex(prices.index.union(calendar)).sort_index().ffill().reindex(calendar)
    for ticker, price in (live_prices or {}).items():
        prices.loc[calendar[-1], ticker] = price
    prices.index.name = "date"
    price_long = prices.stack().rename("price").reset_index()
    price_long.columns = ["date", "ticker", "price"]
    held = held.merge(price_long, on=["date", "ticker"], how="left")
    held["currency"] = held["ticker"].map(inputs.currencies).astype(object)  # may stay all-empty

    # Fallback for instruments without prices: value at cost (account currency).
    unit_cost = lots.groupby(["account_id", "instrument_id"]).apply(
        lambda g: g["purchase_value"].sum() / g["volume_adj"].sum(), include_groups=False
    )
    missing = held["price"].isna() | held["currency"].isna()
    if missing.any():
        for symbol in sorted(held.loc[missing, "symbol"].unique()):
            warnings.append(f"{symbol}: brak ceny rynkowej w części dni; w te dni wyceniony po koszcie zakupu")
        keys = list(zip(held.loc[missing, "account_id"], held.loc[missing, "instrument_id"], strict=True))
        held.loc[missing, "price"] = [unit_cost.get(k, np.nan) for k in keys]
        held.loc[missing, "currency"] = held.loc[missing, "account_id"].map(accounts["currency"])
    held["priced"] = ~missing

    fx_value = fx.copy()  # rates used for values; today's may be a live market rate
    for currency, mid in (live_fx or {}).items():
        fx_value.loc[calendar[-1], currency] = mid
    fx_value.index.name = "date"
    fx_long = fx_value.stack().rename("fx").reset_index()
    fx_long.columns = ["date", "currency", "fx"]
    held = held.merge(fx_long, on=["date", "currency"], how="left")
    held["value_local"] = held["qty"] * held["price"]
    held["value_pln"] = held["value_local"] * held["fx"]
    held["kind"] = "position"

    # --- cash ----------------------------------------------------------------------------------------
    cash_frames = []
    if not inputs.ledger.empty:
        per_day = inputs.ledger.pivot_table(index="date", columns="account_id", values="amount", aggfunc="sum")
        balances = per_day.reindex(calendar, fill_value=0.0).fillna(0.0).cumsum().round(2)
        for account_id in balances.columns:
            currency = accounts.loc[account_id, "currency"]
            frame = pd.DataFrame({
                "date": calendar, "account_id": account_id, "qty": balances[account_id].to_numpy(),
                "price": 1.0, "currency": currency,
                "fx": fx_value[currency].to_numpy() if currency in fx_value.columns else rate(currency).to_numpy(),
            })
            frame["value_local"] = frame["qty"]
            frame["value_pln"] = frame["value_local"] * frame["fx"]
            cash_frames.append(frame)
    cash = pd.concat(cash_frames) if cash_frames else pd.DataFrame()
    if not cash.empty:
        cash = cash.assign(kind="cash", symbol="Gotówka", name="Gotówka", asset_class="cash", priced=True)

    # --- treasury bonds (D-026): gross value in PLN; purchases in, coupons and redemptions out ------------
    bond_rows, bond_flows = _bond_rows(inputs, bond_lots, calendar, end, accounts, warnings)

    # --- cash at banks (D-027) -------------------------------------------------------------------------
    bank_rows, bank_flows = _bank_rows(snapshots, accounts, calendar, fx_value, fx, warnings)

    parts = [frame for frame in (held, cash, bond_rows, bank_rows) if not frame.empty]
    if not parts:  # e.g. only balances in a currency without NBP rates, or only unknown bond series
        return _empty_valuation(lots, warnings)
    daily = pd.concat(parts, ignore_index=True)
    daily["account"] = daily["account_id"].map(accounts["alias"])
    daily = daily[DAILY_COLUMNS].sort_values(["date", "account", "symbol"])

    # --- external flows (deposits and withdrawals), in PLN at the day's NBP rate ----------------------
    ledger_flows = inputs.ledger["type"].isin(["DEPOSIT", "WITHDRAWAL"]) & (inputs.ledger["date"] <= pd.Timestamp(end))
    flows = inputs.ledger[ledger_flows].copy()
    flows["currency"] = flows["account_id"].map(accounts["currency"])
    flows["amount_pln"] = [
        amount * rate(ccy).asof(day) for amount, ccy, day in zip(flows["amount"], flows["currency"], flows["date"],
                                                               strict=True)
    ]
    extra = [frame for frame in (bond_flows, bank_flows) if not frame.empty]
    if extra:
        frames = [frame for frame in (flows, *extra) if not frame.empty]
        flows = pd.concat(frames, ignore_index=True).sort_values("date", kind="stable")
    return Valuation(daily=daily.reset_index(drop=True), flows=flows.reset_index(drop=True), lots=lots,
                     warnings=sorted(set(warnings)), prices=prices, fx=fx_value, currencies=dict(inputs.currencies))
