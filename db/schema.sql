-- Postgres schema for data-driven-leads.
--
-- Shape of the data:
--   regions -> zones -> pincodes      geography, synced from config/regions.json
--   projects                          one row per RERA project (latest known state)
--   project_snapshots                 one row per project per day we saw it (history for MoM / QoQ / YoY)
--   units                             one row per apartment (size bands and price bands come from here)
--
-- Rule of thumb: anything we filter, group or sort by is a real column; everything else
-- the source gives us lives in a jsonb column (details / extra) so new source fields never
-- need a migration.
--
-- Safe to run repeatedly.

-- ---------------------------------------------------------------- geography
CREATE TABLE IF NOT EXISTS regions (
    region_id       TEXT PRIMARY KEY,              -- 'pune-city', 'pmrda', 'mumbai-city', ...
    name            TEXT NOT NULL,
    state           TEXT,
    rera_authority  TEXT,                          -- 'MahaRERA', 'K-RERA'
    rera_website    TEXT,
    apify_actor     TEXT,
    apify_status    TEXT,                          -- 'in-use' | 'untested'
    extra           JSONB NOT NULL DEFAULT '{}',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS zones (
    region_id       TEXT NOT NULL REFERENCES regions ON DELETE CASCADE,
    zone_id         TEXT NOT NULL,                 -- 'central' | 'east' | 'west' | 'north' | 'south'
    name            TEXT NOT NULL,
    PRIMARY KEY (region_id, zone_id)
);

CREATE TABLE IF NOT EXISTS pincodes (
    pincode         TEXT PRIMARY KEY,              -- a pincode belongs to exactly one region + zone
    region_id       TEXT NOT NULL,
    zone_id         TEXT NOT NULL,
    district_id     TEXT,
    district_name   TEXT,
    areas           JSONB NOT NULL DEFAULT '[]',   -- ["Kothrud", ...]
    latitude        DOUBLE PRECISION,              -- optional fixed map centre; the API falls back to
    longitude       DOUBLE PRECISION,              -- the median position of the pincode's projects
    FOREIGN KEY (region_id, zone_id) REFERENCES zones ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_pincodes_zone ON pincodes(region_id, zone_id);

-- Real postal outlines, loaded from India Post's boundary GeoJSON by src/backend/boundaries.py.
-- Simplified to ~40 m so the map stays light. A pincode without a row keeps a small hexagon on the map.
CREATE TABLE IF NOT EXISTS pincode_boundaries (
    pincode         TEXT PRIMARY KEY REFERENCES pincodes ON DELETE CASCADE,
    geometry        JSONB NOT NULL,                -- GeoJSON Polygon or MultiPolygon, WGS84
    source          TEXT,                          -- file it came from
    loaded_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- A zone's outline: its pincodes' outlines merged into one shape.
CREATE TABLE IF NOT EXISTS zone_boundaries (
    region_id       TEXT NOT NULL,
    zone_id         TEXT NOT NULL,
    geometry        JSONB NOT NULL,
    loaded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (region_id, zone_id),
    FOREIGN KEY (region_id, zone_id) REFERENCES zones ON DELETE CASCADE
);
-- 'estimated' = drawn from pincode centres until real outlines are loaded; otherwise the outline file's name
ALTER TABLE zone_boundaries ADD COLUMN IF NOT EXISTS source TEXT;

-- ---------------------------------------------------------------- projects
CREATE TABLE IF NOT EXISTS projects (
    project_id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rera_authority           TEXT NOT NULL,        -- 'MahaRERA'
    rera_id                  TEXT NOT NULL,        -- 'P52100055666'
    project_name             TEXT,
    developer_name           TEXT,
    developer_id             TEXT,
    property_type            TEXT,                 -- Residential / Commercial / Mixed / Plotted
    project_status           TEXT,                 -- New / Ongoing
    registration_status      TEXT,                 -- Active / Completed / Lapsed ...
    state                    TEXT,
    district                 TEXT,
    taluka                   TEXT,
    locality                 TEXT,
    address                  TEXT,
    pincode                  TEXT,                 -- joins to pincodes; not a foreign key on purpose,
                                                   -- so projects in pincodes we have not mapped yet are kept
    latitude                 DOUBLE PRECISION,
    longitude                DOUBLE PRECISION,
    application_date         DATE,
    registration_date        DATE,
    certificate_date         DATE,                 -- latest certificate signed; used as "last filing"
    original_completion_date DATE,
    revised_completion_date  DATE,
    completion_delay_days    INTEGER,
    schedule_status          TEXT,                 -- on_time | late | overdue | early | completed
    total_units              INTEGER,
    sold_units               INTEGER,
    booked_units             INTEGER,
    unsold_units             INTEGER,
    work_done_percent        NUMERIC(6,2),
    total_cost               NUMERIC(18,2),        -- INR
    price_min                NUMERIC(18,2),        -- INR, lowest agreement price
    price_max                NUMERIC(18,2),
    price_per_sqft           NUMERIC(12,2),        -- INR, average sold price per sq ft
    complaint_count          INTEGER,
    litigation_count         INTEGER,
    pending_litigation_count INTEGER,
    has_unit_data            BOOLEAN NOT NULL DEFAULT false,
    detail_level             TEXT NOT NULL DEFAULT 'list',   -- 'list' (registry row) | 'details' (full file)
    source                   TEXT,                 -- 'apify'
    source_url               TEXT,
    details                  JSONB NOT NULL DEFAULT '{}',    -- everything else from the source
    first_seen_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_scraped_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (rera_authority, rera_id)
);
CREATE INDEX IF NOT EXISTS idx_projects_pincode      ON projects(pincode);
CREATE INDEX IF NOT EXISTS idx_projects_registration ON projects(registration_date);
CREATE INDEX IF NOT EXISTS idx_projects_completion   ON projects(revised_completion_date);
CREATE INDEX IF NOT EXISTS idx_projects_developer    ON projects(developer_name);

-- One row per project per day it was loaded. Only the numbers that move.
CREATE TABLE IF NOT EXISTS project_snapshots (
    project_id              BIGINT NOT NULL REFERENCES projects ON DELETE CASCADE,
    snapshot_date           DATE NOT NULL,
    registration_status     TEXT,
    revised_completion_date DATE,
    completion_delay_days   INTEGER,
    total_units             INTEGER,
    sold_units              INTEGER,
    booked_units            INTEGER,
    unsold_units            INTEGER,
    work_done_percent       NUMERIC(6,2),
    price_per_sqft          NUMERIC(12,2),
    complaint_count         INTEGER,
    litigation_count        INTEGER,
    extra                   JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (project_id, snapshot_date)
);

-- One row per apartment as declared by the developer. A unit keeps its row as it moves
-- unsold -> booked -> sold; status_changed_at is when we last saw the status change.
CREATE TABLE IF NOT EXISTS units (
    project_id        BIGINT NOT NULL REFERENCES projects ON DELETE CASCADE,
    building          TEXT NOT NULL,
    wing              TEXT NOT NULL DEFAULT '',
    unit_no           TEXT NOT NULL,
    floor             TEXT,
    status            TEXT NOT NULL,               -- 'sold' | 'booked' | 'unsold'
    carpet_area_sqft  NUMERIC(10,2),
    price_inr         NUMERIC(18,2),               -- agreement price (sold / booked only)
    price_per_sqft    NUMERIC(12,2),               -- price_inr / carpet_area_sqft
    size_band         TEXT GENERATED ALWAYS AS (
        CASE
            WHEN carpet_area_sqft IS NULL THEN 'unknown'
            WHEN carpet_area_sqft <  500 THEN 'lt_500'
            WHEN carpet_area_sqft < 1000 THEN '500_1000'
            WHEN carpet_area_sqft < 1500 THEN '1000_1500'
            WHEN carpet_area_sqft < 2000 THEN '1500_2000'
            WHEN carpet_area_sqft < 2500 THEN '2000_2500'
            WHEN carpet_area_sqft < 3000 THEN '2500_3000'
            ELSE 'gte_3000'
        END) STORED,
    extra             JSONB NOT NULL DEFAULT '{}', -- carpetAreaSqm, receivedAmount, balanceAmount, reckonerValue
    first_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    status_changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, building, wing, unit_no)
);
CREATE INDEX IF NOT EXISTS idx_units_band ON units(project_id, size_band, status);

-- ---------------------------------------------------------------- housekeeping
-- Audit of every load: what was asked for, how many rows, what it cost.
CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source         TEXT NOT NULL,                  -- 'apify' | 'file'
    step           TEXT,                           -- 'scan' | 'details' | 'load-file'
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at    TIMESTAMPTZ,
    input          JSONB,
    rows_in        INTEGER,
    rows_upserted  INTEGER,
    unit_rows      INTEGER,
    cost_usd       NUMERIC(10,4),
    notes          TEXT
);
-- Fire-and-forget runs (driver.py start / collect): the Apify run is tracked until it is collected.
ALTER TABLE ingest_runs ADD COLUMN IF NOT EXISTS status           TEXT;  -- started | downloaded | collected
ALTER TABLE ingest_runs ADD COLUMN IF NOT EXISTS apify_actor      TEXT;
ALTER TABLE ingest_runs ADD COLUMN IF NOT EXISTS apify_run_id     TEXT;
ALTER TABLE ingest_runs ADD COLUMN IF NOT EXISTS apify_dataset_id TEXT;
ALTER TABLE ingest_runs ADD COLUMN IF NOT EXISTS dataset_name     TEXT;  -- named, so Apify keeps it until deleted
ALTER TABLE ingest_runs ADD COLUMN IF NOT EXISTS max_cost_usd     NUMERIC(10,2);
ALTER TABLE ingest_runs ADD COLUMN IF NOT EXISTS raw_file         TEXT;  -- offline copy in data/raw/

-- Currency conversion for the API (prices are stored in INR).
CREATE TABLE IF NOT EXISTS fx_rates (
    currency       TEXT PRIMARY KEY,               -- 'USD'
    inr_per_unit   NUMERIC(12,4) NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- API keys for the FastAPI server. Only the SHA-256 hash of a key is stored.
CREATE TABLE IF NOT EXISTS api_keys (
    key_id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key_hash       TEXT NOT NULL UNIQUE,
    key_prefix     TEXT NOT NULL,                  -- first 8 characters, to recognise a key in listings
    label          TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at   TIMESTAMPTZ,
    revoked_at     TIMESTAMPTZ
);

-- Future: satellite change signals per project (filled by the Sentinel script).
CREATE TABLE IF NOT EXISTS site_signals (
    project_id     BIGINT NOT NULL REFERENCES projects ON DELETE CASCADE,
    month          DATE NOT NULL,                  -- first day of the month
    ndvi_mean      REAL,
    ndbi_mean      REAL,
    cloud_pct      REAL,
    scene_date     DATE,
    PRIMARY KEY (project_id, month)
);

-- People who asked to join the waitlist on the landing page. They typed these details in
-- themselves; this is the only table that holds contact details.
CREATE TABLE IF NOT EXISTS waitlist (
    waitlist_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name           TEXT NOT NULL,
    profession     TEXT NOT NULL,
    categories     JSONB NOT NULL DEFAULT '[]',    -- business categories, for construction businesses
    whatsapp       TEXT NOT NULL UNIQUE,           -- '+91XXXXXXXXXX'
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
