-- OTS bonds pay an interest amount fixed in each issue letter (e.g. 0,37 zł for OTS0419), which is not
-- always 100 zł x rate / 4 (D-026). bond_series is a projection table, so it is recreated with the new
-- column (this works whatever shape an earlier development copy of 0006 left) and the next `fa sync`
-- refills it: forgetting the shipped files' fingerprint makes the sync rebuild.
DROP TABLE IF EXISTS bond_series;
CREATE TABLE bond_series (
    series            TEXT PRIMARY KEY,     -- e.g. 'EDO0736' (type, month and year of redemption)
    type              TEXT NOT NULL CHECK (type IN ('OTS', 'ROR', 'DOR', 'TOS', 'COI', 'ROS', 'EDO', 'ROD')),
    first_rate        REAL NOT NULL,        -- % a year in the first interest period
    margin            REAL,                 -- p.p. over CPI or the NBP reference rate; NULL when fixed
    early_fee         REAL NOT NULL,        -- zł per bond
    maturity_interest REAL,                 -- OTS: interest per bond fixed by the issue letter, paid at maturity
    origin            TEXT NOT NULL CHECK (origin IN ('shipped', 'user'))
);
DELETE FROM source_files WHERE kind = 'resource';
