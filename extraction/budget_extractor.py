"""
budget_extractor.py
===================
FiscalTrace PDF Budget Extraction Engine — MFDP National Budget Documents

WHAT THIS FILE DOES
-------------------
Extracts structured budget allocation data from the Government of Liberia's
National Budget PDFs published by the Ministry of Finance and Development
Planning (MFDP) at mfdp.gov.lr.

DOCUMENT STRUCTURE (learned from FY2025 budget — 625 pages)
------------------------------------------------------------
Pages 1-64:    Front matter, revenue tables, summary sections
Pages 57-64:   "Summary by Spending Entity" — KEY TARGET
               One row per ministry/agency with 6 years of data:
               FY2023 Bud | FY2023 Actual | FY2024 Bud | FY2024 Outturn
               | FY2025 Bud | FY2026 Proj | FY2027 Proj
Page 65+:      Individual ministry detail pages with line-item expenditure

EXTRACTION APPROACH
-------------------
Text-based extraction (not table-based) because pdfplumber finds no
structured tables in the budget pages — data is laid out as fixed-width
text columns, not PDF table objects.

We use regex pattern matching on the text content to:
1. Identify ministry/agency rows by their 3-digit entity codes (e.g. 101, 202)
2. Extract the 6 numeric values per row
3. Associate each row with its sector heading

MINISTRY CODE STRUCTURE
-----------------------
Codes 100-199: Public Administration & Municipal Government
Codes 200-299: Security and Rule of Law
Codes 300-399: Social Services (Health, Gender, Education)
Codes 400-499: Economic Sectors (Agriculture, Infrastructure, Commerce)

OUTPUT
------
List of dicts, one per spending entity:
{
    "entity_code": "202",
    "entity_name": "MINISTRY OF JUSTICE",
    "sector": "Security and Rule of Law",
    "fy2023_budget": 42064487,
    "fy2023_actual": 41432064,
    "fy2024_budget": 42434190,
    "fy2024_outturn": None,
    "fy2025_budget": 51367558,
    "fy2026_projection": 45793870,
    "fy2027_projection": 45590648,
    "fiscal_year": 2025,
    "source_document": "Approved National Budget FY2025",
    "source_url": "https://www.mfdp.gov.lr/...",
    "extracted_at": "2026-06-18T12:00:00Z",
    "extraction_confidence": "high"
}

RELATED FILES
-------------
ingestion/document_crawler.py    Downloads PDFs from MFDP website
models/schema.sql                PostgreSQL schema for extracted data
api/main_api.py                  FastAPI endpoints serving this data
"""

import re
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pdfplumber

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SpendingEntity:
    """One row of budget data — one ministry or agency for one fiscal year."""
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
    fiscal_year: int
    source_document: str
    source_url: str
    source_page: int
    extracted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    extraction_confidence: str = "high"

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Regex to match a spending entity row:
# e.g. "101 NATIONAL LEGISLATURE 67,963,832 59,805,145 63,877,136 44,344,706 ..."
# or   "202 MINISTRY OF JUSTICE 42,064,487 41,432,064 42,434,190 51,367,558 ..."
ENTITY_ROW_PATTERN = re.compile(
    r"^(\d{3})\s+"           # 3-digit entity code
    r"([A-Z][A-Z\s,\-\(\)&/'\.]+?)\s+"  # Entity name (all caps)
    r"([\d,]+(?:\.\d+)?)"    # First number (FY2023 Budget)
    r"(?:\s+([\d,]+(?:\.\d+)?))?"  # FY2023 Actual
    r"(?:\s+([\d,]+(?:\.\d+)?))?"  # FY2024 Budget
    r"(?:\s+([\d,]+(?:\.\d+)?))?"  # FY2024 Outturn
    r"(?:\s+([\d,]+(?:\.\d+)?))?"  # FY2025 Budget
    r"(?:\s+([\d,]+(?:\.\d+)?))?"  # FY2026 Projection
    r"(?:\s+([\d,]+(?:\.\d+)?))?"  # FY2027 Projection
)

# Sector heading pattern — e.g. "01 Public Administration Sector"
SECTOR_PATTERN = re.compile(
    r"^(\d{2})\s+([\w\s]+Sector)\s*$",
    re.IGNORECASE
)

# Summary section markers — these pages contain the spending entity summary
SUMMARY_SECTION_MARKERS = [
    "1.10 Summary by Spending Entity",
    "Summary by Spending Entity",
]

# Pages to scan for the spending entity summary (based on FY2025 analysis)
# The summary spans pages 57-64 in FY2025 — we scan a wider range for safety
SUMMARY_PAGE_RANGE = (50, 80)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _parse_amount(raw: Optional[str]) -> Optional[float]:
    """
    Converts a budget amount string to a float.

    Handles:
        "67,963,832"    → 67963832.0
        "67,963,832.50" → 67963832.5
        "-"             → None
        ""              → None
        None            → None
    """
    if not raw or raw.strip() in ("-", "", "N/A"):
        return None
    cleaned = raw.replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        log.warning("Could not parse amount: %r", raw)
        return None


def _normalise_entity_name(raw: str) -> str:
    """
    Cleans up entity names from PDF extraction.

    PDF text often has:
    - Extra whitespace from column layout
    - Hyphenated line breaks
    - Trailing spaces

    Example: "MINISTRY OF STATE FOR PRESIDENTIAL  AFFAIRS" → "MINISTRY OF STATE FOR PRESIDENTIAL AFFAIRS"
    """
    return " ".join(raw.split())


def _infer_sector(entity_code: str, current_sector: str) -> tuple[str, str]:
    """
    Returns (sector_name, sector_code) for a given entity code.

    Used as a fallback when the sector heading wasn't found in the text.
    Based on the Liberian budget's sector/entity code mapping.
    """
    code = int(entity_code)
    if 100 <= code <= 139 or code in (345, 431, 451):
        return "Public Administration Sector", "01"
    elif 140 <= code <= 159:
        return "Municipal Government Sector", "02"
    elif 160 <= code <= 179:
        return "Transparency and Accountability Sector", "03"
    elif 200 <= code <= 299 or code in (347, 448, 452):
        return "Security and Rule of Law Sector", "04"
    elif 300 <= code <= 329 or code in (340,):
        return "Health and Social Development Sector", "05-06"
    elif 330 <= code <= 339 or code in (302, 303, 304, 306, 307, 308, 309, 316, 326, 327, 328):
        return "Education Sector", "07"
    elif 400 <= code <= 420:
        return "Agriculture Sector", "09"
    elif 420 <= code <= 450:
        return "Infrastructure and Basic Services Sector", "10"
    else:
        return current_sector, "00"


# ---------------------------------------------------------------------------
# Core extractor
# ---------------------------------------------------------------------------

class BudgetPDFExtractor:
    """
    Extracts spending entity budget allocations from MFDP National Budget PDFs.

    Usage:
        extractor = BudgetPDFExtractor(
            pdf_path="/tmp/budget_fy2025.pdf",
            fiscal_year=2025,
            source_document="Approved National Budget FY2025",
            source_url="https://www.mfdp.gov.lr/..."
        )
        entities = extractor.extract()
        for e in entities:
            print(e.entity_name, e.fy2025_budget)
    """

    def __init__(
        self,
        pdf_path: str,
        fiscal_year: int,
        source_document: str,
        source_url: str,
    ):
        self.pdf_path = Path(pdf_path)
        self.fiscal_year = fiscal_year
        self.source_document = source_document
        self.source_url = source_url

    def extract(self) -> list[SpendingEntity]:
        """
        Main extraction entry point.

        Opens the PDF, locates the Summary by Spending Entity section,
        parses each row, and returns a list of SpendingEntity objects.

        Returns:
            List of SpendingEntity — one per ministry/agency found.

        Raises:
            FileNotFoundError: If the PDF path doesn't exist.
            ValueError: If no spending entities could be extracted.
        """
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {self.pdf_path}")

        log.info("[EXTRACTOR] Opening: %s", self.pdf_path.name)

        entities = []
        current_sector = "Unknown"
        current_sector_code = "00"
        in_summary_section = False

        with pdfplumber.open(str(self.pdf_path)) as pdf:
            total_pages = len(pdf.pages)
            log.info("[EXTRACTOR] Total pages: %s", total_pages)

            start, end = SUMMARY_PAGE_RANGE
            end = min(end, total_pages)

            for page_idx in range(start - 1, end):
                page = pdf.pages[page_idx]
                page_num = page_idx + 1
                text = page.extract_text() or ""

                # Detect entry into the summary section
                if not in_summary_section:
                    if any(marker in text for marker in SUMMARY_SECTION_MARKERS):
                        in_summary_section = True
                        log.info("[EXTRACTOR] Found summary section on page %s", page_num)

                if not in_summary_section:
                    continue

                # Detect exit from summary section
                # The summary ends when we hit "Summary by Component" or ministry detail pages
                if "1.11 Summary by Component" in text or (
                    page_idx > start and
                    "Mission:" in text and
                    "Achievements" in text
                ):
                    log.info("[EXTRACTOR] Summary section ends at page %s", page_num)
                    break

                # Parse each line of the page
                for line in text.split("\n"):
                    line = line.strip()

                    # Check for sector heading
                    sector_match = SECTOR_PATTERN.match(line)
                    if sector_match:
                        current_sector_code = sector_match.group(1)
                        current_sector = sector_match.group(2).strip()
                        log.debug("[SECTOR] %s %s", current_sector_code, current_sector)
                        continue

                    # Check for entity row
                    entity_match = ENTITY_ROW_PATTERN.match(line)
                    if entity_match:
                        groups = entity_match.groups()
                        entity_code = groups[0]
                        entity_name = _normalise_entity_name(groups[1])

                        # Infer sector if not yet set from text
                        if current_sector == "Unknown":
                            current_sector, current_sector_code = _infer_sector(
                                entity_code, current_sector
                            )

                        entity = SpendingEntity(
                            entity_code=entity_code,
                            entity_name=entity_name,
                            sector=current_sector,
                            sector_code=current_sector_code,
                            fy2023_budget=_parse_amount(groups[2] if len(groups) > 2 else None),
                            fy2023_actual=_parse_amount(groups[3] if len(groups) > 3 else None),
                            fy2024_budget=_parse_amount(groups[4] if len(groups) > 4 else None),
                            fy2024_outturn=_parse_amount(groups[5] if len(groups) > 5 else None),
                            fy2025_budget=_parse_amount(groups[6] if len(groups) > 6 else None),
                            fy2026_projection=_parse_amount(groups[7] if len(groups) > 7 else None),
                            fy2027_projection=_parse_amount(groups[8] if len(groups) > 8 else None),
                            fiscal_year=self.fiscal_year,
                            source_document=self.source_document,
                            source_url=self.source_url,
                            source_page=page_num,
                        )
                        entities.append(entity)
                        log.debug(
                            "[ENTITY] %s %s → FY2025: %s",
                            entity_code, entity_name,
                            f"${entity.fy2025_budget:,.0f}" if entity.fy2025_budget else "N/A"
                        )

        log.info("[EXTRACTOR] Extracted %s spending entities", len(entities))

        if not entities:
            raise ValueError(
                f"No spending entities found in {self.pdf_path.name}. "
                "The PDF structure may have changed. Review SUMMARY_PAGE_RANGE."
            )

        return entities


# ---------------------------------------------------------------------------
# Text fallback extractor
# ---------------------------------------------------------------------------

class SummaryTextExtractor:
    """
    Fallback extractor that uses raw text parsing when the regex approach
    misses rows due to PDF layout variations.

    Targets pages 57-64 of FY2025 budget specifically.
    Parses the fixed-width text column format directly.
    """

    # Known column header pattern from page 57
    HEADER_PATTERN = re.compile(
        r"FY2023\s+FY2024\s+FY2024\s+FY2025\s+FY2026\s+FY2027"
    )

    # Number pattern — matches comma-formatted integers
    NUMBER_PATTERN = re.compile(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?")

    def __init__(self, pdf_path: str, fiscal_year: int, source_document: str, source_url: str):
        self.pdf_path = Path(pdf_path)
        self.fiscal_year = fiscal_year
        self.source_document = source_document
        self.source_url = source_url

    def extract_page(self, page_num: int) -> list[dict]:
        """Extract all entity rows from a single page."""
        results = []
        with pdfplumber.open(str(self.pdf_path)) as pdf:
            page = pdf.pages[page_num - 1]
            text = page.extract_text() or ""

        current_sector = "Unknown"
        current_sector_code = "00"

        for line in text.split("\n"):
            line = line.strip()

            # Sector heading: "01 Public Administration Sector"
            s = SECTOR_PATTERN.match(line)
            if s:
                current_sector_code = s.group(1)
                current_sector = s.group(2).strip()
                continue

            # Entity row: starts with 3-digit code
            if re.match(r"^\d{3}\s+[A-Z]", line):
                numbers = self.NUMBER_PATTERN.findall(line)
                code_match = re.match(r"^(\d{3})\s+(.+?)(?=\s+[\d,]+)", line)
                if code_match and numbers:
                    entity_code = code_match.group(1)
                    entity_name = _normalise_entity_name(code_match.group(2))
                    parsed_nums = [_parse_amount(n) for n in numbers]
                    # Pad to 7 values
                    while len(parsed_nums) < 7:
                        parsed_nums.append(None)

                    results.append({
                        "entity_code": entity_code,
                        "entity_name": entity_name,
                        "sector": current_sector,
                        "sector_code": current_sector_code,
                        "fy2023_budget": parsed_nums[0],
                        "fy2023_actual": parsed_nums[1],
                        "fy2024_budget": parsed_nums[2],
                        "fy2024_outturn": parsed_nums[3],
                        "fy2025_budget": parsed_nums[4],
                        "fy2026_projection": parsed_nums[5],
                        "fy2027_projection": parsed_nums[6],
                        "fiscal_year": self.fiscal_year,
                        "source_document": self.source_document,
                        "source_url": self.source_url,
                        "source_page": page_num,
                        "extracted_at": datetime.now(timezone.utc).isoformat(),
                        "extraction_confidence": "medium",
                    })

        return results


# ---------------------------------------------------------------------------
# Entry point — test extraction on the downloaded FY2025 PDF
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    PDF_PATH = "/tmp/budget_fy2025.pdf"
    FISCAL_YEAR = 2025
    SOURCE_DOC = "Approved National Budget FY2025"
    SOURCE_URL = "https://www.mfdp.gov.lr/index.php/main-menu-reports/mm-bdp/mm-bd-nb/approved-national-budget-fy2025-2/download"

    print("=" * 60)
    print("FiscalTrace — Budget PDF Extraction Test")
    print("=" * 60)

    # Primary extraction
    extractor = BudgetPDFExtractor(
        pdf_path=PDF_PATH,
        fiscal_year=FISCAL_YEAR,
        source_document=SOURCE_DOC,
        source_url=SOURCE_URL,
    )

    try:
        entities = extractor.extract()
        print(f"\nExtracted {len(entities)} spending entities\n")
        print(f"{'Code':<6} {'Entity Name':<45} {'FY2025 Budget':>15} {'FY2023 Actual':>15}")
        print("-" * 85)
        for e in entities:
            budget = f"${e.fy2025_budget:>14,.0f}" if e.fy2025_budget else "           N/A"
            actual = f"${e.fy2023_actual:>14,.0f}" if e.fy2023_actual else "           N/A"
            name = e.entity_name[:44]
            print(f"{e.entity_code:<6} {name:<45} {budget} {actual}")

    except ValueError:
        print("\nPrimary extractor found no entities — running fallback extractor...")
        fallback = SummaryTextExtractor(
            pdf_path=PDF_PATH,
            fiscal_year=FISCAL_YEAR,
            source_document=SOURCE_DOC,
            source_url=SOURCE_URL,
        )
        # Try pages 57-64 directly (known summary pages from FY2025)
        all_results = []
        for page_num in range(57, 65):
            rows = fallback.extract_page(page_num)
            all_results.extend(rows)
            print(f"Page {page_num}: {len(rows)} entities found")

        print(f"\nFallback extracted {len(all_results)} total entities")
        for r in all_results:
            budget = f"${r['fy2025_budget']:>14,.0f}" if r['fy2025_budget'] else "           N/A"
            name = r['entity_name'][:44]
            print(f"{r['entity_code']:<6} {name:<45} {budget}")
