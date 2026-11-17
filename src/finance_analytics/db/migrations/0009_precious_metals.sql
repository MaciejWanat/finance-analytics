-- New asset class 'precious_metals' (D-040). SQLite cannot change a CHECK constraint in place, so the
-- instruments projection table is recreated. positions and cash_ledger reference it and are projections
-- too, so they are emptied first; forgetting the shipped files' fingerprint makes the next `fa sync`
-- rebuild everything from data/ (same approach as 0007).
DELETE FROM cash_ledger;
DELETE FROM positions;
DROP TABLE instruments;
CREATE TABLE instruments (
    id           INTEGER PRIMARY KEY,
    xtb_symbol   TEXT NOT NULL UNIQUE,     -- e.g. 'NVDA.US', 'VUAA.UK'
    name         TEXT,
    category     TEXT,                     -- as exported: 'ETF', 'STOCK', 'ETC', 'ETN'
    asset_class  TEXT NOT NULL CHECK (asset_class IN (
                     'stock', 'etf', 'bond', 'cash', 'precious_metals', 'other')),
    yahoo_ticker TEXT,                     -- filled by suffix rules; NULL = unresolved
    currency     TEXT                      -- price currency; known after market data (step 3)
);
DELETE FROM source_files WHERE kind = 'resource';
