-- Consumer price index for Poland (GUS), market cache (D-025): persistent, never dropped by a rebuild.
-- Public data only. Values are index points as published: 100.3 means +0.3%.
CREATE TABLE cpi_monthly (
    year  INTEGER NOT NULL,
    month INTEGER NOT NULL,                -- 1..12
    mom   REAL,                            -- previous month = 100
    yoy   REAL,                            -- same month a year earlier = 100
    PRIMARY KEY (year, month)
);
