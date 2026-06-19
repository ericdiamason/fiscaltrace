"""
main_api.py
===========
FiscalTrace FastAPI Gateway — Public Expenditure Intelligence API

WHAT THIS FILE DOES
-------------------
Exposes structured Liberian government budget data through a documented
REST API. Three audience tiers:

  Public endpoints (no auth):
    GET /                                    System health
    GET /api/v1/overview                     National budget summary
    GET /api/v1/sectors                      Budget by sector
    GET /api/v1/entities                     All spending entities
    GET /api/v1/entities/{code}              Single entity detail
    GET /api/v1/search?q=                    Search entities by name
    GET /api/v1/anomalies                    Budget anomalies (increases/cuts)

  Authenticated endpoints (X-API-Key):
    GET /api/v1/variance                     Full variance analysis
    GET /api/v1/export                       Full dataset export

ENVIRONMENT VARIABLES
---------------------
    FISCALTRACE_DB_HOST    (default: 127.0.0.1)
    FISCALTRACE_DB_NAME    (default: postgres)
    FISCALTRACE_DB_USER    (default: fiscaltrace_user)
    FISCALTRACE_DB_PASS    (required)
    FISCALTRACE_API_KEY    (required for authenticated endpoints)
"""

import os
import logging
from datetime import datetime
from typing import List, Optional

import asyncpg
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_HOST = os.getenv("FISCALTRACE_DB_HOST", "127.0.0.1")
DB_NAME = os.getenv("FISCALTRACE_DB_NAME", "postgres")
DB_USER = os.getenv("FISCALTRACE_DB_USER", "fiscaltrace_user")


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is not set in /etc/fiscaltrace.env")
    return value


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="FiscalTrace — Public Expenditure Intelligence API",
    description=(
        "Structured Liberian government budget data extracted from public "
        "financial documents.\n\n"
        "**Data source:** Ministry of Finance and Development Planning (mfdp.gov.lr)\n\n"
        "**Coverage:** Government of Liberia · FY2023–FY2027 projections · "
        "117 spending entities · 11 sectors · $818M FY2025 budget\n\n"
        "**Built by:** [Eric Dia Mason](https://ericdiamason.tech)"
    ),
    version="1.0.0",
    contact={
        "name": "Eric Dia Mason",
        "url": "https://ericdiamason.tech",
        "email": "admin@ericdiamason.tech",
    },
    license_info={"name": "MIT"},
)

ALLOWED_ORIGINS = [
    "https://ericdiamason.tech",
    "https://www.ericdiamason.tech",
    "https://fiscaltrace.ericdiamason.tech",
    "https://omnisight.ericdiamason.tech",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["X-API-Key", "Content-Type"],
)

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(api_key: Optional[str] = Security(API_KEY_HEADER)):
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required. Include X-API-Key header.",
        )
    valid_key = os.getenv("FISCALTRACE_API_KEY")
    if not valid_key or api_key != valid_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )
    return api_key


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup():
    try:
        db_password = _require_env("FISCALTRACE_DB_PASS")
        app.state.db_pool = await asyncpg.create_pool(
            host=DB_HOST, database=DB_NAME,
            user=DB_USER, password=db_password,
            min_size=3, max_size=10,
        )
        log.info("[STARTUP] PostgreSQL pool established.")
    except Exception as exc:
        log.critical("[STARTUP] DB pool failed: %s", exc)
        raise


@app.on_event("shutdown")
async def shutdown():
    await app.state.db_pool.close()
    log.info("[SHUTDOWN] DB pool closed.")


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    version: str
    entities: int
    total_fy2025_budget_usd: float
    data_source: str
    timestamp: datetime


class SectorSummary(BaseModel):
    sector: str
    sector_code: str
    entity_count: int
    fy2025_budget: Optional[float]
    fy2023_actual: Optional[float]
    budget_growth_pct: Optional[float]


class SpendingEntitySummary(BaseModel):
    entity_code: str
    entity_name: str
    sector: str
    fy2023_actual: Optional[float]
    fy2024_budget: Optional[float]
    fy2024_outturn: Optional[float]
    fy2025_budget: Optional[float]
    fy2026_projection: Optional[float]
    fy2025_vs_fy2023_pct: Optional[float]
    source_document: str


class SpendingEntityDetail(BaseModel):
    entity_code: str
    entity_name: str
    sector: str
    sector_code: str
    fy2023_budget: Optional[float]
    fy2023_actual: Optional[float]
    fy2024_budget: Optional[float]
    fy2024_outturn: Optional[float]
    fy2025_budget: Optional[float]
    fy2026_projection: Optional[float]
    fy2027_projection: Optional[float]
    fy2024_variance_pct: Optional[float]
    fy2025_vs_fy2023_pct: Optional[float]
    fiscal_year: int
    source_document: str
    source_url: str
    source_page: Optional[int]
    extracted_at: datetime


class AnomalyAlert(BaseModel):
    entity_code: str
    entity_name: str
    sector: str
    fy2023_actual: Optional[float]
    fy2025_budget: Optional[float]
    change_pct: float
    alert_type: str
    alert_severity: str


class OverviewResponse(BaseModel):
    fiscal_year: int
    total_entities: int
    total_sectors: int
    total_fy2025_budget: float
    total_fy2023_actual: float
    avg_budget_growth_pct: float
    entities_with_large_increases: int
    entities_with_large_cuts: int
    largest_ministry: str
    largest_ministry_budget: float
    data_source: str
    last_updated: datetime


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_model=HealthResponse, tags=["System"])
async def health():
    """System health check. No authentication required."""
    async with app.state.db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT COUNT(*) as entities,
                   COALESCE(SUM(fy2025_budget), 0) as total_budget
            FROM fiscaltrace.spending_entities
        """)
    return HealthResponse(
        status="ONLINE",
        version="1.0.0",
        entities=row["entities"],
        total_fy2025_budget_usd=float(row["total_budget"]),
        data_source="Ministry of Finance and Development Planning — mfdp.gov.lr",
        timestamp=datetime.utcnow(),
    )


@app.get("/api/v1/overview", response_model=OverviewResponse, tags=["Intelligence"])
async def overview():
    """
    National budget overview — key metrics for the current fiscal year.
    No authentication required.
    """
    async with app.state.db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT
                COUNT(*) as total_entities,
                COUNT(DISTINCT sector) as total_sectors,
                COALESCE(SUM(fy2025_budget), 0) as total_fy2025_budget,
                COALESCE(SUM(fy2023_actual), 0) as total_fy2023_actual,
                COALESCE(AVG(CASE WHEN fy2023_actual > 0 AND fy2025_budget > 0
                    THEN ((fy2025_budget - fy2023_actual) / fy2023_actual) * 100
                    END), 0) as avg_growth,
                COUNT(CASE WHEN fy2025_vs_fy2023_pct > 20 THEN 1 END) as large_increases,
                COUNT(CASE WHEN fy2025_vs_fy2023_pct < -10 THEN 1 END) as large_cuts,
                MAX(extracted_at) as last_updated
            FROM fiscaltrace.spending_entities
        """)
        top = await conn.fetchrow("""
            SELECT entity_name, fy2025_budget
            FROM fiscaltrace.spending_entities
            WHERE fy2025_budget IS NOT NULL
            ORDER BY fy2025_budget DESC LIMIT 1
        """)

    return OverviewResponse(
        fiscal_year=2025,
        total_entities=row["total_entities"],
        total_sectors=row["total_sectors"],
        total_fy2025_budget=float(row["total_fy2025_budget"]),
        total_fy2023_actual=float(row["total_fy2023_actual"]),
        avg_budget_growth_pct=round(float(row["avg_growth"]), 1),
        entities_with_large_increases=row["large_increases"],
        entities_with_large_cuts=row["large_cuts"],
        largest_ministry=top["entity_name"] if top else "N/A",
        largest_ministry_budget=float(top["fy2025_budget"]) if top else 0,
        data_source="Approved National Budget FY2025 — mfdp.gov.lr",
        last_updated=row["last_updated"],
    )


@app.get("/api/v1/sectors", response_model=List[SectorSummary], tags=["Intelligence"])
async def sectors():
    """
    Budget allocation by sector — all 11 government sectors.
    No authentication required.
    """
    async with app.state.db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                sector,
                sector_code,
                COUNT(*) as entity_count,
                SUM(fy2025_budget) as fy2025_budget,
                SUM(fy2023_actual) as fy2023_actual,
                ROUND(AVG(fy2025_vs_fy2023_pct)::numeric, 1) as budget_growth_pct
            FROM fiscaltrace.spending_entities
            GROUP BY sector, sector_code
            ORDER BY fy2025_budget DESC NULLS LAST
        """)
    return [
        SectorSummary(
            sector=r["sector"],
            sector_code=r["sector_code"],
            entity_count=r["entity_count"],
            fy2025_budget=float(r["fy2025_budget"]) if r["fy2025_budget"] else None,
            fy2023_actual=float(r["fy2023_actual"]) if r["fy2023_actual"] else None,
            budget_growth_pct=float(r["budget_growth_pct"]) if r["budget_growth_pct"] else None,
        )
        for r in rows
    ]


@app.get("/api/v1/entities", response_model=List[SpendingEntitySummary], tags=["Intelligence"])
async def entities(
    sector: Optional[str] = Query(None, description="Filter by sector name"),
    order_by: str = Query("fy2025_budget", description="Sort field: fy2025_budget, fy2023_actual, entity_name"),
    limit: int = Query(50, le=200, description="Number of results (max 200)"),
):
    """
    All spending entities with budget allocations.
    Optionally filter by sector. No authentication required.
    """
    allowed_order = {
        "fy2025_budget": "fy2025_budget DESC NULLS LAST",
        "fy2023_actual": "fy2023_actual DESC NULLS LAST",
        "entity_name": "entity_name ASC",
        "growth": "fy2025_vs_fy2023_pct DESC NULLS LAST",
    }
    order_clause = allowed_order.get(order_by, "fy2025_budget DESC NULLS LAST")

    async with app.state.db_pool.acquire() as conn:
        if sector:
            rows = await conn.fetch(f"""
                SELECT entity_code, entity_name, sector,
                       fy2023_actual, fy2024_budget, fy2024_outturn,
                       fy2025_budget, fy2026_projection,
                       fy2025_vs_fy2023_pct, source_document
                FROM fiscaltrace.spending_entities
                WHERE LOWER(sector) LIKE LOWER($1)
                ORDER BY {order_clause}
                LIMIT $2
            """, f"%{sector}%", limit)
        else:
            rows = await conn.fetch(f"""
                SELECT entity_code, entity_name, sector,
                       fy2023_actual, fy2024_budget, fy2024_outturn,
                       fy2025_budget, fy2026_projection,
                       fy2025_vs_fy2023_pct, source_document
                FROM fiscaltrace.spending_entities
                ORDER BY {order_clause}
                LIMIT $1
            """, limit)

    return [
        SpendingEntitySummary(
            entity_code=r["entity_code"],
            entity_name=r["entity_name"],
            sector=r["sector"],
            fy2023_actual=float(r["fy2023_actual"]) if r["fy2023_actual"] else None,
            fy2024_budget=float(r["fy2024_budget"]) if r["fy2024_budget"] else None,
            fy2024_outturn=float(r["fy2024_outturn"]) if r["fy2024_outturn"] else None,
            fy2025_budget=float(r["fy2025_budget"]) if r["fy2025_budget"] else None,
            fy2026_projection=float(r["fy2026_projection"]) if r["fy2026_projection"] else None,
            fy2025_vs_fy2023_pct=float(r["fy2025_vs_fy2023_pct"]) if r["fy2025_vs_fy2023_pct"] else None,
            source_document=r["source_document"],
        )
        for r in rows
    ]


@app.get("/api/v1/entities/{entity_code}", response_model=SpendingEntityDetail, tags=["Intelligence"])
async def entity_detail(entity_code: str):
    """
    Full detail for a single spending entity by its 3-digit code.
    No authentication required.

    Example codes: 310 (Ministry of Health), 301 (Ministry of Education),
    409 (Ministry of Public Works), 130 (Ministry of Finance)
    """
    async with app.state.db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT * FROM fiscaltrace.spending_entities
            WHERE entity_code = $1
            ORDER BY extracted_at DESC LIMIT 1
        """, entity_code)

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Entity {entity_code} not found. Use /api/v1/entities to browse all entities."
        )

    return SpendingEntityDetail(
        entity_code=row["entity_code"],
        entity_name=row["entity_name"],
        sector=row["sector"],
        sector_code=row["sector_code"],
        fy2023_budget=float(row["fy2023_budget"]) if row["fy2023_budget"] else None,
        fy2023_actual=float(row["fy2023_actual"]) if row["fy2023_actual"] else None,
        fy2024_budget=float(row["fy2024_budget"]) if row["fy2024_budget"] else None,
        fy2024_outturn=float(row["fy2024_outturn"]) if row["fy2024_outturn"] else None,
        fy2025_budget=float(row["fy2025_budget"]) if row["fy2025_budget"] else None,
        fy2026_projection=float(row["fy2026_projection"]) if row["fy2026_projection"] else None,
        fy2027_projection=float(row["fy2027_projection"]) if row["fy2027_projection"] else None,
        fy2024_variance_pct=float(row["fy2024_variance_pct"]) if row["fy2024_variance_pct"] else None,
        fy2025_vs_fy2023_pct=float(row["fy2025_vs_fy2023_pct"]) if row["fy2025_vs_fy2023_pct"] else None,
        fiscal_year=row["fiscal_year"],
        source_document=row["source_document"],
        source_url=row["source_url"],
        source_page=row["source_page"],
        extracted_at=row["extracted_at"],
    )


@app.get("/api/v1/search", response_model=List[SpendingEntitySummary], tags=["Intelligence"])
async def search(
    q: str = Query(..., min_length=2, description="Search term — ministry or agency name"),
    limit: int = Query(20, le=50),
):
    """
    Search spending entities by name.
    No authentication required.

    Example: ?q=health, ?q=education, ?q=justice
    """
    async with app.state.db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT entity_code, entity_name, sector,
                   fy2023_actual, fy2024_budget, fy2024_outturn,
                   fy2025_budget, fy2026_projection,
                   fy2025_vs_fy2023_pct, source_document
            FROM fiscaltrace.spending_entities
            WHERE to_tsvector('english', entity_name) @@ plainto_tsquery('english', $1)
               OR LOWER(entity_name) LIKE LOWER($2)
            ORDER BY fy2025_budget DESC NULLS LAST
            LIMIT $3
        """, q, f"%{q}%", limit)

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No entities found matching '{q}'."
        )

    return [
        SpendingEntitySummary(
            entity_code=r["entity_code"],
            entity_name=r["entity_name"],
            sector=r["sector"],
            fy2023_actual=float(r["fy2023_actual"]) if r["fy2023_actual"] else None,
            fy2024_budget=float(r["fy2024_budget"]) if r["fy2024_budget"] else None,
            fy2024_outturn=float(r["fy2024_outturn"]) if r["fy2024_outturn"] else None,
            fy2025_budget=float(r["fy2025_budget"]) if r["fy2025_budget"] else None,
            fy2026_projection=float(r["fy2026_projection"]) if r["fy2026_projection"] else None,
            fy2025_vs_fy2023_pct=float(r["fy2025_vs_fy2023_pct"]) if r["fy2025_vs_fy2023_pct"] else None,
            source_document=r["source_document"],
        )
        for r in rows
    ]


@app.get("/api/v1/anomalies", response_model=List[AnomalyAlert], tags=["Intelligence"])
async def anomalies(
    threshold_pct: float = Query(20.0, description="Minimum % change to flag as anomaly"),
    limit: int = Query(20, le=100),
):
    """
    Budget anomaly alerts — entities with significant increases or cuts.
    Compares FY2025 budget against FY2023 actual expenditure.
    No authentication required.

    Large increases may indicate new priorities or inflated estimates.
    Large cuts may indicate programme elimination or underfunding.
    """
    async with app.state.db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT entity_code, entity_name, sector,
                   fy2023_actual, fy2025_budget, fy2025_vs_fy2023_pct
            FROM fiscaltrace.spending_entities
            WHERE ABS(fy2025_vs_fy2023_pct) >= $1
            ORDER BY ABS(fy2025_vs_fy2023_pct) DESC
            LIMIT $2
        """, threshold_pct, limit)

    results = []
    for r in rows:
        pct = float(r["fy2025_vs_fy2023_pct"])
        alert_type = "large_increase" if pct > 0 else "large_cut"
        severity = "critical" if abs(pct) >= 50 else "high" if abs(pct) >= 30 else "medium"
        results.append(AnomalyAlert(
            entity_code=r["entity_code"],
            entity_name=r["entity_name"],
            sector=r["sector"],
            fy2023_actual=float(r["fy2023_actual"]) if r["fy2023_actual"] else None,
            fy2025_budget=float(r["fy2025_budget"]) if r["fy2025_budget"] else None,
            change_pct=round(pct, 1),
            alert_type=alert_type,
            alert_severity=severity,
        ))
    return results


@app.get("/api/v1/variance", tags=["Authenticated"])
async def variance(
    _: str = Depends(require_api_key),
    limit: int = Query(50, le=200),
):
    """
    Full variance analysis — budget vs actual execution rates.
    Requires X-API-Key authentication.
    """
    async with app.state.db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT entity_code, entity_name, sector,
                   fy2023_actual, fy2024_budget, fy2024_outturn,
                   fy2025_budget, fy2024_execution_rate_pct,
                   budget_growth_pct, execution_status
            FROM fiscaltrace.budget_variance
            ORDER BY fy2025_budget DESC NULLS LAST
            LIMIT $1
        """, limit)

    return [dict(r) for r in rows]
