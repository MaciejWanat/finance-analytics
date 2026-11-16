-- Market data cache (D-002): persistent, never dropped by `fa sync` / `fa rebuild`.
-- Public data only: prices by ticker, FX rates by currency. Nothing about accounts.

-- Daily close as quoted by the source, already converted from minor units
-- (e.g. GBp -> GBP). Split-adjusted, NOT dividend-adjusted (D-009).
CREATE TABLE prices (
    ticker   TEXT NOT NULL,                -- Yahoo ticker, e.g. 'NVDA', 'VUAA.L'
    date     TEXT NOT NULL,                -- YYYY-MM-DD, exchange-local trading day
    close    REAL NOT NULL,
    currency TEXT NOT NULL,
    PRIMARY KEY (ticker, date)
);

-- Splits and per-share dividends reported by the price source.
CREATE TABLE corporate_actions (
    ticker TEXT NOT NULL,
    date   TEXT NOT NULL,
    kind   TEXT NOT NULL CHECK (kind IN ('SPLIT', 'DIVIDEND')),
    value  REAL NOT NULL,                  -- split ratio (e.g. 10 for 10:1) or dividend per share
    PRIMARY KEY (ticker, date, kind)
);

CREATE TABLE ticker_info (
    ticker     TEXT PRIMARY KEY,
    currency   TEXT,                       -- price currency after minor-unit conversion
    name       TEXT,
    exchange   TEXT,
    fetched_at TEXT NOT NULL
);

-- NBP table A mid rates: PLN per 1 unit of `currency`.
CREATE TABLE fx_rates (
    currency TEXT NOT NULL,
    date     TEXT NOT NULL,                -- publication (effective) date
    mid      REAL NOT NULL,
    table_no TEXT,
    PRIMARY KEY (currency, date)
);

-- Which date ranges have already been asked for, so weekends and holidays
-- (no data) are not re-requested on every run.
CREATE TABLE fetch_log (
    source     TEXT NOT NULL,              -- 'nbp' | 'yahoo'
    key        TEXT NOT NULL,              -- currency or ticker
    date_from  TEXT NOT NULL,
    date_to    TEXT NOT NULL,              -- last day known to be final
    fetched_at TEXT NOT NULL,
    last_error TEXT,
    PRIMARY KEY (source, key)
);
