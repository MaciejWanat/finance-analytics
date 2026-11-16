-- Initial schema.
--
-- Two kinds of tables live in this database (docs/decisions.md, D-002):
--   * projection tables: rebuilt at any time from the files in data/ (raw exports,
--     manual CSV/YAML). Safe to drop and recreate.
--   * market cache tables (added later): persistent, never dropped by a rebuild.

-- Projection: every source file that has been parsed into the database.
CREATE TABLE source_files (
    id             INTEGER PRIMARY KEY,
    kind           TEXT NOT NULL,          -- e.g. 'xtb', 'manual_cash', 'manual_bonds'
    path           TEXT NOT NULL UNIQUE,   -- relative to the data directory
    sha256         TEXT NOT NULL,
    parser_version INTEGER NOT NULL,
    imported_at    TEXT NOT NULL,          -- ISO 8601, UTC
    rows_json      TEXT                    -- row counts per target table
);

-- Projection: accounts, from data/config/accounts.yaml.
CREATE TABLE accounts (
    id          TEXT PRIMARY KEY,          -- stable slug, e.g. 'xtb-usd'
    external_no TEXT,                      -- broker account number; stays local
    alias       TEXT NOT NULL,             -- what the UI shows
    institution TEXT NOT NULL,             -- e.g. 'xtb', 'pko', 'revolut'
    kind        TEXT NOT NULL CHECK (kind IN ('broker', 'bank', 'bonds')),
    currency    TEXT NOT NULL,             -- ISO 4217
    tax_wrapper TEXT CHECK (tax_wrapper IN ('IKE', 'IKZE'))
);
