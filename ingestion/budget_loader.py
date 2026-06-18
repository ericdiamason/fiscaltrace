"""
budget_loader.py
================
FiscalTrace Database Loader — Writes extracted budget data to PostgreSQL

WHAT THIS FILE DOES
-------------------
Takes the list of SpendingEntity objects produced by BudgetPDFExtractor
and writes them to the fiscaltrace PostgreSQL schema.

Handles:
- Creating a budget_documents record first (document registry)
- Upserting spending_entities with ON CONFLICT DO NOTHING (idempotent)
- Computing variance fields before insert
- Full audit trail — every record linked to its source document

USAGE
-----
    python3 ingestion/budget_loader.py

ENVIRONMENT VARIABLES REQUIRED
-------------------------------
    FISCALTRACE_DB_HOST   (default: 127.0.0.1)
    FISCALTRACE_DB_NAME   (default: postgres)
    FISCALTRACE_DB_USER   (default: postgres)
    FISCALTRACE_DB_PASS   (required)
"""

import os
import sys
import logging
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_batch

sys.path.insert(0, str(Path(__file__).parent.parent))
from extraction.budget_extractor import BudgetPDFExtractor, SpendingEntity

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

def _get_db_connection():
    """
    Opens a psycopg2 connection from environment variables.
    Falls back to peer authentication via postgres user for local dev.
    """
    password = os.getenv("FISCALTRACE_DB_PASS")
    host = os.getenv("FISCALTRACE_DB_HOST", "127.0.0.1")
    dbname = os.getenv("FISCALTRACE_DB_NAME", "postgres")
    user = os.getenv("FISCALTRACE_DB_USER", "postgres")

    try:
        if password:
            return psycopg2.connect(
                host=host, database=dbname, user=user, password=password
            )
        else:
            # Local dev: peer auth via postgres unix socket
            return psycopg2.connect(database=dbname, user=user)
    except Exception as exc:
        log.error("[DB] Connection failed: %s", exc)
        raise


# ---------------------------------------------------------------------------
# Variance computation
# ---------------------------------------------------------------------------

def _compute_variances(entity: SpendingEntity) -> dict:
    """
    Computes variance and execution rate fields for a spending entity.

    fy2024_variance_pct:  How much FY2024 outturn deviated from FY2024 budget
    fy2025_vs_fy2023_pct: Budget growth from FY2023 actual to FY2025 budget
    """
    fy2024_variance_pct = None
    fy2025_vs_fy2023_pct = None

    if entity.fy2024_budget and entity.fy2024_outturn and entity.fy2024_budget > 0:
        fy2024_variance_pct = round(
            ((entity.fy2024_outturn - entity.fy2024_budget) / entity.fy2024_budget) * 100,
            2
        )

    if entity.fy2023_actual and entity.fy2025_budget and entity.fy2023_actual > 0:
        fy2025_vs_fy2023_pct = round(
            ((entity.fy2025_budget - entity.fy2023_actual) / entity.fy2023_actual) * 100,
            2
        )

    return {
        "fy2024_variance_pct": fy2024_variance_pct,
        "fy2025_vs_fy2023_pct": fy2025_vs_fy2023_pct,
    }


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

class BudgetLoader:
    """
    Loads extracted SpendingEntity objects into PostgreSQL.

    Two-phase load:
    1. Register the source document in budget_documents
    2. Upsert all spending entities linked to that document
    """

    def __init__(self, conn):
        self.conn = conn
        self.cursor = conn.cursor()

    def register_document(
        self,
        fiscal_year: int,
        document_type: str,
        document_title: str,
        source_url: str,
        file_size_bytes: int,
        total_pages: int,
        entities_count: int,
    ) -> int:
        """
        Inserts or updates a budget_documents record.

        Returns:
            document_id: The ID of the registered document.
        """
        self.cursor.execute(
            """
            INSERT INTO fiscaltrace.budget_documents
                (fiscal_year, document_type, document_title, source_url,
                 file_size_bytes, total_pages, entities_count, ingestion_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'complete')
            ON CONFLICT (fiscal_year, document_type)
            DO UPDATE SET
                document_title   = EXCLUDED.document_title,
                source_url       = EXCLUDED.source_url,
                file_size_bytes  = EXCLUDED.file_size_bytes,
                total_pages      = EXCLUDED.total_pages,
                entities_count   = EXCLUDED.entities_count,
                ingestion_status = 'complete',
                ingested_at      = NOW()
            RETURNING document_id;
            """,
            (fiscal_year, document_type, document_title, source_url,
             file_size_bytes, total_pages, entities_count)
        )
        document_id = self.cursor.fetchone()[0]
        self.conn.commit()
        log.info("[LOADER] Document registered — ID: %s", document_id)
        return document_id

    def load_entities(
        self,
        entities: list[SpendingEntity],
        document_id: int,
    ) -> int:
        """
        Bulk inserts spending entities.

        Uses ON CONFLICT DO NOTHING for idempotency — safe to re-run.
        Links each entity to its source document via document_id.

        Returns:
            Number of rows actually inserted (excluding conflicts).
        """
        rows = []
        for e in entities:
            variances = _compute_variances(e)
            rows.append((
                e.entity_code,
                e.entity_name,
                e.sector,
                e.sector_code,
                e.fy2023_budget,
                e.fy2023_actual,
                e.fy2024_budget,
                e.fy2024_outturn,
                e.fy2025_budget,
                e.fy2026_projection,
                e.fy2027_projection,
                variances["fy2024_variance_pct"],
                variances["fy2025_vs_fy2023_pct"],
                e.fiscal_year,
                e.source_document,
                e.source_url,
                e.source_page,
                document_id,
                e.extraction_confidence,
            ))

        insert_sql = """
            INSERT INTO fiscaltrace.spending_entities (
                entity_code, entity_name, sector, sector_code,
                fy2023_budget, fy2023_actual, fy2024_budget, fy2024_outturn,
                fy2025_budget, fy2026_projection, fy2027_projection,
                fy2024_variance_pct, fy2025_vs_fy2023_pct,
                fiscal_year, source_document, source_url, source_page,
                document_id, extraction_confidence
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s, %s, %s,
                %s, %s
            )
            ON CONFLICT (entity_code, fiscal_year, source_document)
            DO NOTHING;
        """

        execute_batch(self.cursor, insert_sql, rows, page_size=50)
        inserted = self.cursor.rowcount
        self.conn.commit()
        log.info("[LOADER] %s entities inserted (%s skipped as duplicates)",
                 inserted, len(rows) - inserted)
        return inserted

    def close(self):
        self.cursor.close()


# ---------------------------------------------------------------------------
# Verification query
# ---------------------------------------------------------------------------

def verify_load(conn):
    """Prints a summary of what was loaded into the database."""
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            COUNT(*) as total_entities,
            COUNT(DISTINCT entity_code) as unique_entities,
            COUNT(DISTINCT sector) as sectors,
            SUM(fy2025_budget) as total_fy2025_budget,
            SUM(fy2023_actual) as total_fy2023_actual
        FROM fiscaltrace.spending_entities;
    """)
    row = cursor.fetchone()
    print("\n=== DATABASE VERIFICATION ===")
    print(f"Total entity records:     {row[0]}")
    print(f"Unique entity codes:      {row[1]}")
    print(f"Sectors covered:          {row[2]}")
    print(f"Total FY2025 budget:      ${row[3]:>14,.0f}" if row[3] else "Total FY2025 budget: N/A")
    print(f"Total FY2023 actual:      ${row[4]:>14,.0f}" if row[4] else "Total FY2023 actual: N/A")

    cursor.execute("""
        SELECT sector, COUNT(*) as entities,
               SUM(fy2025_budget) as sector_budget
        FROM fiscaltrace.spending_entities
        GROUP BY sector
        ORDER BY sector_budget DESC NULLS LAST;
    """)
    print("\n=== BUDGET BY SECTOR ===")
    print(f"{'Sector':<45} {'Entities':>8} {'FY2025 Budget':>16}")
    print("-" * 72)
    for r in cursor.fetchall():
        budget = f"${r[2]:>15,.0f}" if r[2] else "             N/A"
        print(f"{r[0]:<45} {r[1]:>8} {budget}")

    cursor.execute("""
        SELECT entity_name, fy2025_budget, fy2023_actual,
               fy2025_vs_fy2023_pct, execution_status
        FROM fiscaltrace.budget_variance
        WHERE fy2025_budget IS NOT NULL
        ORDER BY fy2025_budget DESC
        LIMIT 10;
    """)
    print("\n=== TOP 10 BY FY2025 BUDGET (with variance) ===")
    print(f"{'Entity':<42} {'FY2025 Budget':>15} {'Growth %':>10} {'Status':>12}")
    print("-" * 82)
    for r in cursor.fetchall():
        growth = f"{r[3]:>+.1f}%" if r[3] else "       N/A"
        print(f"{r[0][:41]:<42} ${r[1]:>14,.0f} {growth:>10} {r[4]:>12}")

    cursor.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    PDF_PATH        = "/tmp/budget_fy2025.pdf"
    FISCAL_YEAR     = 2025
    DOCUMENT_TYPE   = "approved_budget"
    SOURCE_DOC      = "Approved National Budget FY2025"
    SOURCE_URL      = ("https://www.mfdp.gov.lr/index.php/main-menu-reports"
                       "/mm-bdp/mm-bd-nb/approved-national-budget-fy2025-2/download")

    log.info("=" * 60)
    log.info("[FISCALTRACE] Starting budget load pipeline")
    log.info("=" * 60)

    # Step 1: Extract from PDF
    log.info("[STEP 1] Extracting from PDF: %s", PDF_PATH)
    extractor = BudgetPDFExtractor(
        pdf_path=PDF_PATH,
        fiscal_year=FISCAL_YEAR,
        source_document=SOURCE_DOC,
        source_url=SOURCE_URL,
    )
    entities = extractor.extract()
    log.info("[STEP 1] Extracted %s entities", len(entities))

    # Step 2: Connect to database
    log.info("[STEP 2] Connecting to PostgreSQL")
    conn = _get_db_connection()
    loader = BudgetLoader(conn)

    # Step 3: Register document
    log.info("[STEP 3] Registering source document")
    file_size = Path(PDF_PATH).stat().st_size
    document_id = loader.register_document(
        fiscal_year=FISCAL_YEAR,
        document_type=DOCUMENT_TYPE,
        document_title=SOURCE_DOC,
        source_url=SOURCE_URL,
        file_size_bytes=file_size,
        total_pages=625,
        entities_count=len(entities),
    )

    # Step 4: Load entities
    log.info("[STEP 4] Loading %s entities into PostgreSQL", len(entities))
    inserted = loader.load_entities(entities, document_id)

    # Step 5: Verify
    log.info("[STEP 5] Verifying load")
    verify_load(conn)

    loader.close()
    conn.close()
    log.info("[FISCALTRACE] Pipeline complete")
