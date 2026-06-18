-- =============================================================================
-- schema.sql
-- FiscalTrace PostgreSQL Schema
-- =============================================================================
--
-- WHAT THIS FILE DOES
-- -------------------
-- Creates the fiscaltrace schema, tables, indexes, and constraints.
--
-- HOW TO RUN
-- ----------
--   psql -U postgres -d postgres -f models/schema.sql
--
-- DESIGN DECISIONS
-- ----------------
-- 1. Separate schema "fiscaltrace" — isolated from omnisight schema
-- 2. spending_entities: one row per entity per fiscal_year document
--    Unique constraint on (entity_code, fiscal_year, source_document)
--    allows re-ingestion without duplicates
-- 3. budget_documents: tracks every PDF ingested — full audit trail
-- 4. All amounts stored as NUMERIC(20,2) — no float precision loss
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS fiscaltrace;

-- ---------------------------------------------------------------------------
-- Table: budget_documents
-- One row per PDF ingested — source of truth for document tracking
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fiscaltrace.budget_documents (
    document_id     BIGSERIAL       PRIMARY KEY,
    fiscal_year     INTEGER         NOT NULL,
    document_type   VARCHAR(50)     NOT NULL, -- 'approved_budget', 'draft_budget', 'supplementary'
    document_title  VARCHAR(255)    NOT NULL,
    source_url      VARCHAR(500)    NOT NULL,
    file_size_bytes BIGINT,
    total_pages     INTEGER,
    entities_count  INTEGER,
    ingested_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    ingestion_status VARCHAR(20)    NOT NULL DEFAULT 'pending',
    CONSTRAINT uq_budget_document UNIQUE (fiscal_year, document_type)
);

COMMENT ON TABLE fiscaltrace.budget_documents IS
    'Tracks every budget PDF downloaded and processed by FiscalTrace.';

-- ---------------------------------------------------------------------------
-- Table: spending_entities
-- Core fact table — one row per ministry/agency per fiscal year document
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fiscaltrace.spending_entities (
    entity_id           BIGSERIAL       PRIMARY KEY,

    -- Entity identity
    entity_code         VARCHAR(10)     NOT NULL,
    entity_name         VARCHAR(255)    NOT NULL,
    sector              VARCHAR(100)    NOT NULL,
    sector_code         VARCHAR(10)     NOT NULL,

    -- Budget amounts — all in USD
    -- Naming: fy{year}_{type} where type is budget/actual/outturn/projection
    fy2023_budget       NUMERIC(20,2),
    fy2023_actual       NUMERIC(20,2),
    fy2024_budget       NUMERIC(20,2),
    fy2024_outturn      NUMERIC(20,2),
    fy2025_budget       NUMERIC(20,2),
    fy2026_projection   NUMERIC(20,2),
    fy2027_projection   NUMERIC(20,2),

    -- Computed variance fields (populated by pipeline)
    fy2024_variance_pct NUMERIC(10,2),  -- (fy2024_outturn - fy2024_budget) / fy2024_budget * 100
    fy2025_vs_fy2023_pct NUMERIC(10,2), -- (fy2025_budget - fy2023_actual) / fy2023_actual * 100

    -- Source tracking
    fiscal_year         INTEGER         NOT NULL,
    source_document     VARCHAR(255)    NOT NULL,
    source_url          VARCHAR(500)    NOT NULL,
    source_page         INTEGER,
    document_id         BIGINT          REFERENCES fiscaltrace.budget_documents(document_id),

    -- Extraction metadata
    extracted_at        TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    extraction_confidence VARCHAR(20)   NOT NULL DEFAULT 'high',

    -- Idempotency constraint
    CONSTRAINT uq_entity_per_document UNIQUE (entity_code, fiscal_year, source_document)
);

COMMENT ON TABLE fiscaltrace.spending_entities IS
    'Budget allocations per spending entity (ministry/agency) per fiscal year. '
    'One row per entity per document ingested.';

COMMENT ON COLUMN fiscaltrace.spending_entities.fy2025_budget IS
    'FY2025 approved budget allocation in USD.';

COMMENT ON COLUMN fiscaltrace.spending_entities.fy2023_actual IS
    'FY2023 actual expenditure in USD — from the budget document comparison column.';

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

-- Primary query patterns
CREATE INDEX IF NOT EXISTS idx_se_entity_code
    ON fiscaltrace.spending_entities (entity_code);

CREATE INDEX IF NOT EXISTS idx_se_fiscal_year
    ON fiscaltrace.spending_entities (fiscal_year DESC);

CREATE INDEX IF NOT EXISTS idx_se_sector
    ON fiscaltrace.spending_entities (sector);

CREATE INDEX IF NOT EXISTS idx_se_fy2025_budget
    ON fiscaltrace.spending_entities (fy2025_budget DESC NULLS LAST);

-- Full text search on entity name
CREATE INDEX IF NOT EXISTS idx_se_entity_name_trgm
    ON fiscaltrace.spending_entities
    USING gin (to_tsvector('english', entity_name));

-- ---------------------------------------------------------------------------
-- View: budget_variance
-- Pre-computed variance analysis for the dashboard
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW fiscaltrace.budget_variance AS
SELECT
    entity_code,
    entity_name,
    sector,
    fiscal_year,
    fy2023_actual,
    fy2024_budget,
    fy2024_outturn,
    fy2025_budget,
    -- Execution rate: what fraction of budget was actually spent
    CASE
        WHEN fy2024_budget > 0
        THEN ROUND((fy2024_outturn / fy2024_budget) * 100, 1)
        ELSE NULL
    END AS fy2024_execution_rate_pct,
    -- Budget growth: how much did allocation grow vs prior actual
    CASE
        WHEN fy2023_actual > 0
        THEN ROUND(((fy2025_budget - fy2023_actual) / fy2023_actual) * 100, 1)
        ELSE NULL
    END AS budget_growth_pct,
    -- Risk flag: execution below 50% is critical
    CASE
        WHEN fy2024_budget > 0 AND (fy2024_outturn / fy2024_budget) < 0.5
        THEN 'critical'
        WHEN fy2024_budget > 0 AND (fy2024_outturn / fy2024_budget) < 0.7
        THEN 'at_risk'
        ELSE 'on_track'
    END AS execution_status,
    source_document,
    extracted_at
FROM fiscaltrace.spending_entities;

COMMENT ON VIEW fiscaltrace.budget_variance IS
    'Pre-computed budget variance and execution rate analysis per spending entity.';

-- ---------------------------------------------------------------------------
-- Verification
-- ---------------------------------------------------------------------------
\echo ''
\echo '=== FiscalTrace schema initialised ==='
SELECT schemaname, tablename,
       pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'fiscaltrace'
ORDER BY tablename;
