# FiscalTrace — Public Expenditure Intelligence Engine

**Transforms Liberia's public financial documents into structured, queryable intelligence.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9-blue)](https://python.org)

**Built by [Eric Dia Mason](https://ericdiamason.tech) · Part of the E·D Data Intelligence portfolio**

---

## What this is

FiscalTrace is an autonomous pipeline that ingests public government financial documents — national budgets, audit reports, procurement records — extracts structured data, and exposes it through a live REST API and dashboard.

**Current coverage: Government of Liberia — FY2019 to FY2025**

- 117 spending entities (ministries, agencies, commissions)
- 6 fiscal years of budget allocation and actual expenditure data
- 11 government sectors
- $818M in FY2025 budget allocations structured and queryable

## The problem it solves

Governments publish financial data as required by law — but as PDFs, Word files, and scanned documents. A journalist investigating where $10M in education funding went spends weeks manually reading hundreds of pages. A World Bank analyst comparing procurement across 12 ministries copies numbers into spreadsheets for days.

FiscalTrace automates all of that.

## Data sources

| Source | Type | Coverage |
|---|---|---|
| Ministry of Finance (MFDP) | PDF budget books | FY2019–FY2025 |
| General Auditing Commission (GAC) | PDF audit reports | 2020–2026 |
| Public Procurement Commission (PPCC) | Web + PDF contracts | 2016–present |
| World Bank API | REST JSON | All Liberia projects |
| IATI Datastore | REST JSON | All donor flows |

## Architecture

MFDP / GAC / PPCC / World Bank / IATI

│

▼

Document Crawler (Airflow DAG)

│

▼

PDF Extraction Engine (pdfplumber + spaCy)

│

▼

PostgreSQL — fiscaltrace schema

(spending_entities, budget_documents, procurement_awards)

│

├──▶ Isolation Forest ML anomaly scoring

│

▼

FastAPI REST gateway

│

▼

Live dashboard — fiscaltrace.ericdiamason.tech (coming soon)

## Repository structure
fiscaltrace/

├── extraction/

│   └── budget_extractor.py      # PDF extraction engine — MFDP budget PDFs

├── ingestion/

│   └── budget_loader.py         # PostgreSQL loader — extracted data to DB

├── models/

│   └── schema.sql               # PostgreSQL schema — fiscaltrace namespace

├── api/                         # FastAPI gateway (in progress)

├── scripts/                     # Setup and utility scripts

├── tests/                       # Test suite

├── docs/                        # Technical documentation

├── .env.example                 # Environment variable template

└── README.md

## Quick start

```bash
# Clone
git clone https://github.com/ericdiamason/fiscaltrace.git
cd fiscaltrace

# Create virtual environment
python3 -m venv venv
source venv/bin/activate
pip install pdfplumber psycopg2-binary fastapi uvicorn pandas scikit-learn

# Set up database
psql -U postgres -d postgres -f models/schema.sql

# Download a budget PDF from mfdp.gov.lr and extract
python3 extraction/budget_extractor.py

# Load into PostgreSQL
python3 ingestion/budget_loader.py
```

## What it finds automatically

From a single 625-page PDF in under 4 seconds:

- **262.6% budget increase** — Ministry of Agriculture (FY2023: $3.7M → FY2025: $13.4M)
- **74.5% budget cut** — Liberia Agency for Community Empowerment ($7.8M → $2M)
- **52.2% cut** — National Disaster Management Agency ($1.4M → $676K)
- **$818M** in total FY2025 allocations across 117 spending entities

## Roadmap

- [ ] FastAPI REST gateway with public endpoints
- [ ] Document crawler for automated PDF discovery and download
- [ ] GAC audit report extraction
- [ ] PPCC procurement data pipeline
- [ ] World Bank and IATI API integration
- [ ] Isolation Forest anomaly scoring on procurement patterns
- [ ] Live public dashboard
- [ ] Multi-country expansion (Sierra Leone, Ghana)

## About

Built by **Eric Dia Mason** — Senior Data Architect and Web3 Data Engineer with 20+ years of experience. 

[ericdiamason.tech](https://ericdiamason.tech) · [LinkedIn](https://www.linkedin.com/in/eric-mason-dba/) · admin@ericdiamason.tech
