# FiscalTrace — Public Expenditure Intelligence Engine

**Transforms Liberia's public financial documents into structured, queryable intelligence.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.128-green)](https://fastapi.tiangolo.com)

**Live demo:** [fiscaltrace.ericdiamason.tech](https://fiscaltrace.ericdiamason.tech)
**Public API:** [fiscaltrace.ericdiamason.tech/docs](https://fiscaltrace.ericdiamason.tech/docs)
**Overview:** [fiscaltrace.ericdiamason.tech/api/v1/overview](https://fiscaltrace.ericdiamason.tech/api/v1/overview)

Part of the [Eric Dia Mason](https://ericdiamason.tech) intelligence systems portfolio — see also [OmniSight](https://github.com/ericdiamason/omnisight).

---

## What this is

FiscalTrace is an autonomous pipeline that ingests public government financial documents — national budgets, audit reports, procurement records — extracts structured data, and exposes it through a live REST API and dashboard.

**Current coverage: Government of Liberia — FY2025 budget**

- 117 spending entities (ministries, agencies, commissions)
- 11 government sectors
- $818M in FY2025 budget allocations structured and queryable
- 6 fiscal years of data per entity (FY2023 actual through FY2027 projection)
- 49+ entities automatically flagged for budget changes over 20%

These numbers are live — call `/api/v1/overview` for the current figures rather than trusting what's written here. This README will go stale; the API can't.

---

## The problem it solves

Governments publish financial data as required by law — but as PDFs, Word files, and scanned documents. A journalist investigating where $10M in education funding went spends weeks manually reading hundreds of pages. A World Bank analyst comparing procurement across 12 ministries copies numbers into spreadsheets for days.

FiscalTrace automates all of that — and surfaces the anomalies automatically, without anyone having to know what to look for first.

**What it found automatically, from one 625-page PDF, in under 4 seconds:**

- **262.6% budget increase** — Ministry of Agriculture (FY2023: $3.7M → FY2025: $13.4M)
- **74.5% budget cut** — Liberia Agency for Community Empowerment ($7.8M → $2M)
- **52.2% cut** — National Disaster Management Agency ($1.4M → $676K)
- **145.7% execution rate** — Ministry of Finance spent 45% more than its FY2024 budget allocated

---

## Who this is for

The same structured dataset serves three audiences without anyone touching a spreadsheet:

- **Analysts** — full API access, cross-year variance, sector-level aggregation. Built for World Bank and donor-side budget review.
- **Journalists** — anomalies pre-flagged with the source page cited. No 600-page PDF to read before the story starts.
- **Government & donors** — execution rates and ministry scorecards, the same numbers a Minister of Finance briefing would need.

---

## Architecture

```
MFDP / GAC / PPCC / World Bank / IATI
        │
        ▼
  PDF Extraction Engine          ← pattern-matched extraction, sub-4-second runtime
  (pdfplumber)                   ← 625-page national budget → 117 structured entities
        │
        ▼
  PostgreSQL — fiscaltrace schema
  (spending_entities, budget_documents)
        │
        ├──▶  Variance computation     ← budget growth %, execution rate, anomaly threshold
        │     (SQL views, computed on ingest)
        │
        ▼
  FastAPI gateway                ← 8 endpoints, public + read-only DB user
  Nginx + Let's Encrypt          ← TLS termination, dedicated subdomain
        │
        ▼
  Live dashboard                 ← real-time KPIs, anomaly feed, ministry search
  (fiscaltrace.ericdiamason.tech)
```

FiscalTrace runs on its own subdomain with its own Nginx server block, systemd service, and database user — fully isolated from sibling projects on the same infrastructure (see [OmniSight](https://github.com/ericdiamason/omnisight)).

---

## Data sources

| Source | Type | Coverage | Status |
|---|---|---|---|
| Ministry of Finance (MFDP) | PDF budget books | FY2025 | ✅ Live |
| General Auditing Commission (GAC) | PDF audit reports | 2020–2026 | Planned |
| Public Procurement Commission (PPCC) | Web + PDF contracts | 2016–present | Planned |
| World Bank API | REST JSON | All Liberia projects | Planned |
| IATI Datastore | REST JSON | All donor flows | Planned |

---

## Repository structure

```
fiscaltrace/
├── extraction/
│   └── budget_extractor.py      # PDF extraction engine — MFDP budget PDFs
├── ingestion/
│   └── budget_loader.py         # PostgreSQL loader — extracted data to DB
├── models/
│   └── schema.sql               # PostgreSQL schema — fiscaltrace namespace
├── api/
│   └── main_api.py              # FastAPI gateway — 8 endpoints, live
├── scripts/
│   └── fiscaltrace-api.service  # systemd service unit
├── docs/
│   └── index.html               # standalone dashboard — live anomaly feed
├── .env.example                 # Environment variable template
└── README.md
```

---

## API reference

Full interactive docs at [fiscaltrace.ericdiamason.tech/docs](https://fiscaltrace.ericdiamason.tech/docs)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/` | None | System health — entity count, total budget |
| `GET` | `/api/v1/overview` | None | National budget summary, key metrics |
| `GET` | `/api/v1/sectors` | None | Budget allocation by sector (all 11) |
| `GET` | `/api/v1/entities` | None | All spending entities — sortable, filterable by sector |
| `GET` | `/api/v1/entities/{code}` | None | Full detail for a single ministry/agency |
| `GET` | `/api/v1/search?q=` | None | Full-text search by entity name |
| `GET` | `/api/v1/anomalies` | None | Automated budget anomaly detection |
| `GET` | `/api/v1/variance` | `X-API-Key` header | Full execution-rate variance analysis |

### Example: national overview

```bash
curl https://fiscaltrace.ericdiamason.tech/api/v1/overview
```

```json
{
  "fiscal_year": 2025,
  "total_entities": 117,
  "total_sectors": 11,
  "total_fy2025_budget": 818277947.0,
  "total_fy2023_actual": 728012205.0,
  "avg_budget_growth_pct": 15.8,
  "entities_with_large_increases": 27,
  "entities_with_large_cuts": 22,
  "largest_ministry": "MINISTRY OF FINANCE AND DEVELOPMENT",
  "largest_ministry_budget": 203833731.0,
  "data_source": "Approved National Budget FY2025 — mfdp.gov.lr"
}
```

### Example: automated anomaly detection

```bash
curl "https://fiscaltrace.ericdiamason.tech/api/v1/anomalies?threshold_pct=20&limit=5"
```

### Example: search a ministry

```bash
curl "https://fiscaltrace.ericdiamason.tech/api/v1/search?q=health"
```

---

## Quick start (local development)

```bash
# Clone
git clone https://github.com/ericdiamason/fiscaltrace.git
cd fiscaltrace

# Create virtual environment
python3 -m venv venv
source venv/bin/activate
pip install pdfplumber psycopg2-binary asyncpg fastapi uvicorn pandas

# Set up database
psql -U postgres -d postgres -f models/schema.sql

# Download a budget PDF from mfdp.gov.lr and extract
python3 extraction/budget_extractor.py

# Load into PostgreSQL
python3 ingestion/budget_loader.py

# Run the API
uvicorn api.main_api:app --reload --port 8002
```

---

## Production deployment

Deployed on OCI Linux (Always Free tier), sharing infrastructure with OmniSight:

- **OS:** Oracle Linux Server 9.7, `opc` service user
- **Process management:** systemd — `fiscaltrace-api.service` auto-restarts on failure
- **TLS:** Let's Encrypt via Certbot, shared certificate covering both `omnisight.ericdiamason.tech` and `fiscaltrace.ericdiamason.tech`
- **Reverse proxy:** Nginx, dedicated server block — no shared routing with sibling projects
- **Database:** Dedicated `fiscaltrace_user` with `SELECT`-only grants on the `fiscaltrace` schema
- **Secrets:** `/etc/fiscaltrace.env` with `chmod 600` — loaded via systemd `EnvironmentFile`
- **SELinux:** web root labelled `httpd_sys_content_t`, venv binaries labelled `bin_t`

### Environment variables

```bash
sudo cp .env.example /etc/fiscaltrace.env
sudo nano /etc/fiscaltrace.env
sudo chmod 600 /etc/fiscaltrace.env
```

Required variables:

```
FISCALTRACE_DB_HOST     # PostgreSQL host (default: 127.0.0.1)
FISCALTRACE_DB_NAME     # PostgreSQL database (default: postgres)
FISCALTRACE_DB_USER     # PostgreSQL user (default: fiscaltrace_user)
FISCALTRACE_DB_PASS     # PostgreSQL password
FISCALTRACE_API_KEY     # API key for the authenticated /variance endpoint
```

### Start services

```bash
sudo systemctl enable fiscaltrace-api.service
sudo systemctl start fiscaltrace-api.service
```

### Before deploying any change to `main_api.py`

Always verify the route list before and after deploying — OmniSight lost an endpoint in production this way once already:

```bash
curl -s https://fiscaltrace.ericdiamason.tech/openapi.json | python3 -c "import json,sys; d=json.load(sys.stdin); print('\n'.join(d['paths'].keys()))"
```

---

## Security

- Zero credentials in source code or git history — all secrets via environment variables
- `fiscaltrace_user` has read-only (`SELECT`) database grants — no write access from the API layer
- CORS locked to `https://ericdiamason.tech`, `https://www.ericdiamason.tech`, `https://fiscaltrace.ericdiamason.tech`, and `https://omnisight.ericdiamason.tech` — no wildcard origins
- API key authentication on the `/api/v1/variance` endpoint
- All other endpoints are intentionally public and unauthenticated — this is a transparency tool; the data is public by law

---

## Roadmap

- [x] FastAPI REST gateway with public endpoints
- [x] Live public dashboard
- [ ] GAC audit report extraction
- [ ] PPCC procurement data pipeline — single-bid and contract-splitting detection
- [ ] World Bank and IATI API integration
- [ ] Isolation Forest anomaly scoring on procurement patterns (beyond rule-based thresholds)
- [ ] Document crawler for automated PDF discovery and download
- [ ] Multi-country expansion (Sierra Leone, Ghana)

---

## About

Built by **Eric Dia Mason** — Senior Data Architect and Web3 Data Engineer with 20+ years of self-taught experience. FiscalTrace applies the same production engineering discipline as [OmniSight](https://github.com/ericdiamason/omnisight) to a different problem — public financial transparency instead of blockchain intelligence.

[ericdiamason.tech](https://ericdiamason.tech) · [fiscaltrace.ericdiamason.tech](https://fiscaltrace.ericdiamason.tech) · [LinkedIn](https://www.linkedin.com/in/eric-mason-dba/) · admin@ericdiamason.tech
