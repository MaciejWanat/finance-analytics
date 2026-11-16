-- XTB projection tables (D-002, D-016). All rebuilt by `fa sync` from data/raw.

CREATE TABLE instruments (
    id           INTEGER PRIMARY KEY,
    xtb_symbol   TEXT NOT NULL UNIQUE,     -- e.g. 'NVDA.US', 'VUAA.UK'
    name         TEXT,
    category     TEXT,                     -- as exported: 'ETF', 'STOCK'
    asset_class  TEXT NOT NULL CHECK (asset_class IN ('stock', 'etf', 'bond', 'cash', 'other')),
    yahoo_ticker TEXT,                     -- filled by suffix rules; NULL = unresolved
    currency     TEXT                      -- price currency; known after market data (step 3)
);

-- One row per broker position (a lot): opened once, optionally closed once.
CREATE TABLE positions (
    id             INTEGER PRIMARY KEY,
    account_id     TEXT NOT NULL REFERENCES accounts (id),
    position_id    TEXT NOT NULL,          -- broker position ID
    instrument_id  INTEGER NOT NULL REFERENCES instruments (id),
    side           TEXT NOT NULL CHECK (side IN ('BUY')),
    volume         REAL NOT NULL CHECK (volume > 0),
    open_time      TEXT NOT NULL,          -- ISO 8601, UTC
    open_price     REAL NOT NULL,          -- instrument currency
    close_time     TEXT,                   -- NULL while open
    close_price    REAL,
    purchase_value REAL,                   -- account currency, from cash operations / closed positions
    sale_value     REAL,                   -- account currency
    source_file_id INTEGER REFERENCES source_files (id),
    UNIQUE (account_id, position_id)
);

-- Every cash movement on an account, in the account currency.
CREATE TABLE cash_ledger (
    id             INTEGER PRIMARY KEY,
    account_id     TEXT NOT NULL REFERENCES accounts (id),
    ts             TEXT NOT NULL,          -- ISO 8601, UTC
    type           TEXT NOT NULL CHECK (type IN (
                       'DEPOSIT', 'WITHDRAWAL', 'BUY', 'SELL', 'DIVIDEND', 'WHT',
                       'INTEREST', 'INTEREST_TAX', 'FEE', 'OTHER')),
    amount         REAL NOT NULL,          -- signed
    instrument_id  INTEGER REFERENCES instruments (id),
    position_id    TEXT,
    broker_type    TEXT NOT NULL,          -- the export's own label, e.g. 'Stock purchase'
    comment        TEXT,                   -- may hold personal data; stays local
    source_ref     TEXT NOT NULL,          -- broker operation ID, used for de-duplication
    source_file_id INTEGER REFERENCES source_files (id),
    UNIQUE (account_id, source_ref)
);

-- Problems found while parsing and reconciling; shown on the "Importy" page.
CREATE TABLE import_issues (
    id             INTEGER PRIMARY KEY,
    source_file_id INTEGER REFERENCES source_files (id),
    account_id     TEXT,
    severity       TEXT NOT NULL CHECK (severity IN ('error', 'warning', 'info')),
    message        TEXT NOT NULL
);

-- Metadata of each parsed export file (date range, account, cash total).
ALTER TABLE source_files ADD COLUMN account_id TEXT;
ALTER TABLE source_files ADD COLUMN date_from TEXT;
ALTER TABLE source_files ADD COLUMN date_to TEXT;

CREATE INDEX cash_ledger_account_ts ON cash_ledger (account_id, ts);
CREATE INDEX positions_account ON positions (account_id, instrument_id);
