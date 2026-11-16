-- Polish retail treasury bonds (R-008, D-026). All projection tables: rebuilt by `fa sync` from
-- data/manual/bonds.csv, data/config/bond_series.yaml and the public files shipped in
-- src/finance_analytics/resources/.

-- Parameters of every series: shipped from the issue letters, merged with the user's YAML.
CREATE TABLE bond_series (
    series     TEXT PRIMARY KEY,            -- e.g. 'EDO0736' (type, month and year of redemption)
    type       TEXT NOT NULL CHECK (type IN ('OTS', 'ROR', 'DOR', 'TOS', 'COI', 'ROS', 'EDO', 'ROD')),
    first_rate REAL NOT NULL,               -- % a year in the first interest period
    margin     REAL,                        -- p.p. over CPI or the NBP reference rate; NULL when fixed
    early_fee  REAL NOT NULL,               -- zł per bond
    origin     TEXT NOT NULL CHECK (origin IN ('shipped', 'user'))
);

-- Official rate of each later interest period, as published by the Ministry of Finance.
CREATE TABLE bond_rates (
    series TEXT NOT NULL,
    period INTEGER NOT NULL CHECK (period >= 1),
    rate   REAL NOT NULL,                   -- % a year
    origin TEXT NOT NULL CHECK (origin IN ('shipped', 'user')),
    PRIMARY KEY (series, period)
);

-- NBP reference rate history, for ROR and DOR.
CREATE TABLE bond_reference_rate (
    date_from TEXT PRIMARY KEY,             -- YYYY-MM-DD, in force from
    rate      REAL NOT NULL                 -- % a year
);

-- One row per purchase from data/manual/bonds.csv.
CREATE TABLE bond_lots (
    id             INTEGER PRIMARY KEY,
    account_id     TEXT NOT NULL REFERENCES accounts (id),
    series         TEXT NOT NULL,
    purchase_date  TEXT NOT NULL,           -- YYYY-MM-DD
    quantity       INTEGER NOT NULL CHECK (quantity > 0),
    note           TEXT,                    -- the user's own note; stays local
    row_no         INTEGER NOT NULL,        -- data row in bonds.csv, for deleting it from the UI
    source_file_id INTEGER REFERENCES source_files (id)
);

CREATE INDEX bond_lots_account ON bond_lots (account_id, series);
