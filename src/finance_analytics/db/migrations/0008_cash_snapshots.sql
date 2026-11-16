-- Cash at banks (R-007, D-027). A projection table: rebuilt by `fa sync` from data/manual/cash_balances.csv.
-- One row per balance snapshot; a snapshot holds until the next one.
CREATE TABLE cash_snapshots (
    id             INTEGER PRIMARY KEY,
    account_id     TEXT NOT NULL REFERENCES accounts (id),
    date           TEXT NOT NULL,           -- YYYY-MM-DD
    balance        REAL NOT NULL,           -- in the account's currency; may be negative (overdraft)
    note           TEXT,                    -- the user's own note; stays local
    row_no         INTEGER NOT NULL,        -- data row in cash_balances.csv, for deleting it from the UI
    source_file_id INTEGER REFERENCES source_files (id),
    UNIQUE (account_id, date)
);
