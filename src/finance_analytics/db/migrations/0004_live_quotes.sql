-- Latest intraday quotes for online mode (D-021). Market cache: never dropped by a rebuild.
-- Holds the last price of every held ticker and market FX rates such as 'USDPLN=X'
-- (PLN per unit). Used only to value the current day; history stays in `prices`/`fx_rates`.
CREATE TABLE live_quotes (
    ticker     TEXT PRIMARY KEY,
    price      REAL NOT NULL,
    currency   TEXT,
    fetched_at TEXT NOT NULL               -- ISO 8601, UTC
);
