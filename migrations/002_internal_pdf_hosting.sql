-- =============================================================================
-- Migration 002: Internal PDF hosting
-- Date: 2026-06-21
-- =============================================================================
--
-- WHY THIS MIGRATION EXISTS
-- --------------------------
-- Every anomaly finding links to its exact source page in the FY2025 budget
-- PDF — the single most credibility-bearing feature in FiscalTrace. Until
-- this migration, that link pointed directly at mfdp.gov.lr (the Liberian
-- Ministry of Finance and Development Planning's live website).
--
-- That's a real reliability risk: if mfdp.gov.lr is down, slow, or
-- restructured at the moment someone clicks "verify this", the feature
-- built specifically to prove trustworthiness fails — through no fault of
-- FiscalTrace's actual data.
--
-- The fix: FiscalTrace already downloaded this PDF once, to extract the
-- data in the first place. This migration keeps that copy, serves it
-- reliably from FiscalTrace's own infrastructure, and updates source_url
-- to point there — while preserving the original MFDP URL as the honest
-- record of where the document was first published.
--
-- The source document remains the citation. Where FiscalTrace happens to
-- serve a reliable copy of it is a hosting detail, not a different source.
--
-- WHAT THIS MIGRATION DOES
-- --------------------------
-- 1. Adds budget_documents.internal_url — FiscalTrace's own reliable copy.
--    budget_documents.source_url (the original MFDP link) is untouched.
-- 2. Updates spending_entities.source_url for all FY2025 rows to point at
--    the internal copy. This is the field /api/v1/anomalies actually reads
--    when building each row's source link, so this is the change that
--    matters for what a visitor clicks.
--
-- PREREQUISITE (manual, not part of this SQL)
-- ---------------------------------------------
-- The PDF itself must already be placed at:
--   /var/www/fiscaltrace_site/documents/budget-fy2025.pdf
-- and confirmed reachable at:
--   https://fiscaltrace.ericdiamason.tech/documents/budget-fy2025.pdf
-- (HTTP 200, verified manually before running this migration)
--
-- HOW TO RUN
-- ----------
--   sudo -u postgres psql -d <dbname> -f migrations/002_internal_pdf_hosting.sql
--
-- Run as postgres (schema owner), not fiscaltrace_user (read-only API role,
-- intentionally lacks ALTER TABLE privileges).
--
-- This migration is idempotent: ADD COLUMN IF NOT EXISTS is safe to re-run,
-- and the UPDATE only touches rows currently matching the old MFDP URL, so
-- re-running it after the first successful run is a safe no-op.
-- =============================================================================

ALTER TABLE fiscaltrace.budget_documents
    ADD COLUMN IF NOT EXISTS internal_url VARCHAR(500);

UPDATE fiscaltrace.budget_documents
SET internal_url = 'https://fiscaltrace.ericdiamason.tech/documents/budget-fy2025.pdf'
WHERE document_id = 1
  AND fiscal_year = 2025;

UPDATE fiscaltrace.spending_entities
SET source_url = 'https://fiscaltrace.ericdiamason.tech/documents/budget-fy2025.pdf'
WHERE source_url = 'https://www.mfdp.gov.lr/index.php/main-menu-reports/mm-bdp/mm-bd-nb/approved-national-budget-fy2025-2/download';

-- ---------------------------------------------------------------------------
-- Verification queries — run these after the migration and confirm:
--   - budget_documents shows BOTH source_url (original) and internal_url (new)
--   - spending_entities shows exactly 117 rows, all on the new internal URL
-- ---------------------------------------------------------------------------
SELECT document_id, fiscal_year, source_url, internal_url
FROM fiscaltrace.budget_documents;

SELECT COUNT(*), source_url
FROM fiscaltrace.spending_entities
GROUP BY source_url;
