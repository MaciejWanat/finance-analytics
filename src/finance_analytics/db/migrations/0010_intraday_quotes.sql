-- Intraday quotes for the "1D" range (D-070). Market cache: never dropped by a rebuild.
-- 5-minute bars from Yahoo (pre-market and post-market included) plus every live quote, at most one per
-- ticker and minute. Prices in the main currency unit (GBp -> GBP); FX pairs as 'USDPLN=X' (PLN per unit).
-- Kept for the last 10 days.
CREATE TABLE IF NOT EXISTS intraday_quotes (
    ticker TEXT NOT NULL,
    ts     TEXT NOT NULL,                  -- ISO 8601, UTC, whole minutes
    price  REAL NOT NULL,
    PRIMARY KEY (ticker, ts)
);
