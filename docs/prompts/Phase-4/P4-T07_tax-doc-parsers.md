# P4-T07: Tax Document Parsers (1099, 1098)

## Context

You are working on Sentry Finance, a local-first personal finance app.
The document drop system (`dal/document_drop.py`, `backend/routers/documents.py`)
already supports file upload, recognition, preview, and commit workflows.
Existing parsers handle TSP statements and myPay RAS documents.

Each year, the user receives tax documents from multiple institutions:
- **DFAS 1099-R** — Military pension distribution (gross, federal/state tax withheld)
- **Fidelity Consolidated 1099** — Investment income (dividends, capital gains, interest)
- **Acorns 1099-DIV/1099-B** — Investment dividends and capital gains
- **Affirm 1099-INT** — Interest earned on HYSA
- **NFCU 1098** — Mortgage interest paid (deductible)

These documents provide **authoritative** numbers that replace estimation-based
tracking from transaction records. They are the foundation for the "Yearly
Wrap-Up Revised" feature (P6-T03) which upgrades preliminary year-end
numbers to tax-document-verified figures.

## Starting State

- `dal/parsers/base.py` defines `BaseParser` (ABC) and `ParseResult`:
  ```python
  class ParseResult:
      parser_type: str
      fields: dict         # Key-value extracted data
      raw_data: str | None # Original text for debugging
  ```
- `dal/parsers/tsp_statement.py` and `dal/parsers/mypay_ras.py` are
  concrete parser examples
- `dal/document_drop.py` has `_PARSERS` list for auto-detection
- `document_drops` table stores uploaded documents with parser type,
  parsed fields (JSON), status, and timestamps
- All parsers implement `can_parse(filename, file_bytes) -> bool` and
  `parse(filename, file_bytes) -> ParseResult`

## Task

### 1. DFAS 1099-R Parser: `dal/parsers/dfas_1099r.py`

```python
"""DFAS 1099-R (Military Pension Distribution) PDF parser."""

class DFAS1099RParser(BaseParser):
    parser_type = "dfas_1099r"

    @classmethod
    def can_parse(cls, filename: str, file_bytes: bytes) -> bool:
        """Detect DFAS 1099-R by filename or content."""
        name = filename.lower()
        if "1099" in name and ("dfas" in name or "ras" in name):
            return True
        # Check PDF text content for DFAS 1099-R markers
        text = cls._extract_pdf_text(file_bytes)
        return "1099-R" in text and ("DFAS" in text or "Defense Finance" in text)

    @classmethod
    def parse(cls, filename: str, file_bytes: bytes) -> ParseResult:
        text = cls._extract_pdf_text(file_bytes)
        fields = {}
        # Box 1:  Gross distribution
        # Box 2a: Taxable amount
        # Box 4:  Federal income tax withheld
        # Box 12: State tax withheld
        # Box 7:  Distribution code (7 = normal for retiree)
        # Payer: DFAS-CL / Defense Finance and Accounting Service
        # ... regex extraction ...
        return ParseResult(parser_type=cls.parser_type, fields=fields, raw_data=text)
```

Key fields to extract:
| Box | Field Name | Description |
|-----|-----------|-------------|
| 1 | `gross_distribution` | Total pension paid |
| 2a | `taxable_amount` | Taxable portion |
| 4 | `federal_tax_withheld` | Federal income tax withheld |
| 12 | `state_tax_withheld` | State income tax withheld |
| 7 | `distribution_code` | Code (usually "7" for retiree) |
| - | `tax_year` | Calendar year |
| - | `recipient_ssn_last4` | Last 4 of SSN (for verification) |

### 2. Fidelity Consolidated 1099 Parser: `dal/parsers/fidelity_1099.py`

Fidelity's consolidated 1099 is a multi-page PDF covering:
- **1099-DIV**: Ordinary dividends, qualified dividends, capital gain distributions
- **1099-B**: Sales proceeds, cost basis, gain/loss
- **1099-INT**: Interest income
- **1099-OID**: Original issue discount (usually zero)

Key fields:
| Section | Field Name | Description |
|---------|-----------|-------------|
| 1099-DIV Box 1a | `ordinary_dividends` | Total ordinary dividends |
| 1099-DIV Box 1b | `qualified_dividends` | Qualified dividends (lower tax rate) |
| 1099-DIV Box 2a | `capital_gain_distributions` | Long-term capital gain distributions |
| 1099-B | `total_proceeds` | Total sale proceeds |
| 1099-B | `total_cost_basis` | Total cost basis |
| 1099-B | `total_gain_loss` | Net gain/loss |
| 1099-INT Box 1 | `interest_income` | Interest income |
| - | `tax_year` | Calendar year |

### 3. Acorns 1099 Parser: `dal/parsers/acorns_1099.py`

Acorns issues a 1099-DIV and optionally a 1099-B.
Simpler than Fidelity — typically one page per form.

Key fields: `ordinary_dividends`, `qualified_dividends`, `total_proceeds`,
`total_cost_basis`, `tax_year`.

### 4. Affirm 1099-INT Parser: `dal/parsers/affirm_1099int.py`

Affirm issues a 1099-INT for HYSA interest earned.

Key fields:
| Box | Field Name | Description |
|-----|-----------|-------------|
| 1 | `interest_income` | Total interest earned |
| - | `tax_year` | Calendar year |
| - | `payer_name` | "Affirm" / "Cross River Bank" |

### 5. NFCU 1098 Parser: `dal/parsers/nfcu_1098.py`

NFCU issues a 1098 for mortgage interest paid (tax deductible).

Key fields:
| Box | Field Name | Description |
|-----|-----------|-------------|
| 1 | `mortgage_interest_received` | Total mortgage interest paid |
| 2 | `outstanding_mortgage_principal` | Remaining principal balance |
| 5 | `mortgage_insurance_premiums` | PMI/MIP if applicable |
| 6 | `property_taxes` | Property taxes paid through escrow |
| - | `tax_year` | Calendar year |

### 6. PDF Text Extraction Utility

All tax documents are PDFs. Add a shared utility method to `BaseParser`:

```python
@staticmethod
def _extract_pdf_text(file_bytes: bytes) -> str:
    """Extract text from a PDF file using pdfplumber."""
    import io
    import pdfplumber

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n".join(pages)
```

Add `pdfplumber` to `requirements.txt` if not already present.

### 7. Register All Parsers in Document Drop Chain

Update `dal/document_drop.py`:

```python
from dal.parsers.dfas_1099r import DFAS1099RParser
from dal.parsers.fidelity_1099 import Fidelity1099Parser
from dal.parsers.acorns_1099 import Acorns1099Parser
from dal.parsers.affirm_1099int import Affirm1099IntParser
from dal.parsers.nfcu_1098 import NFCU1098Parser

_PARSERS = [
    # ... existing parsers ...
    DFAS1099RParser,
    Fidelity1099Parser,
    Acorns1099Parser,
    Affirm1099IntParser,
    NFCU1098Parser,
]
```

### 8. Tax Document Summary Endpoint

Add to `backend/routers/documents.py`:

```python
@router.get("/api/documents/tax-summary/{year}")
def tax_summary(year: int):
    """Return all parsed tax documents for a given year.

    Aggregates key figures across all 1099s and 1098s.
    """
    with get_db() as conn:
        docs = conn.execute(
            """SELECT parser_type, parsed_fields
               FROM document_drops
               WHERE status = 'committed'
                 AND json_extract(parsed_fields, '$.tax_year') = ?
               ORDER BY parser_type""",
            (str(year),),
        ).fetchall()

    summary = {
        "year": year,
        "documents": [],
        "totals": {
            "gross_income": 0,
            "investment_income": 0,
            "interest_earned": 0,
            "mortgage_interest_paid": 0,
            "federal_tax_withheld": 0,
            "state_tax_withheld": 0,
        },
    }

    for doc in docs:
        fields = json.loads(doc["parsed_fields"])
        summary["documents"].append({
            "type": doc["parser_type"],
            "fields": fields,
        })
        # Aggregate totals
        # ... (sum up relevant fields) ...

    return summary
```

## Files to Create

1. `dal/parsers/dfas_1099r.py`
2. `dal/parsers/fidelity_1099.py`
3. `dal/parsers/acorns_1099.py`
4. `dal/parsers/affirm_1099int.py`
5. `dal/parsers/nfcu_1098.py`

## Files to Modify

1. `dal/parsers/base.py` — add `_extract_pdf_text()` utility
2. `dal/document_drop.py` — register new parsers
3. `backend/routers/documents.py` — add tax summary endpoint
4. `requirements.txt` — add `pdfplumber` if needed

## Files NOT to Modify

- Migration files — no schema changes; `document_drops` already stores
  parsed fields as JSON
- Connector files — tax docs are uploaded manually, not scraped
- Frontend files

## Constraints

- All parsers must follow the `BaseParser` interface exactly
- `can_parse()` must be selective — false positives cause wrong parser routing
- PDF extraction depends on `pdfplumber` — this handles most IRS-standard
  PDF formats, but some institutions use image-based PDFs. If text extraction
  yields empty results, the parser should return a `ParseResult` with empty
  fields and a note in `raw_data` indicating OCR may be needed.
- All dollar amounts should be parsed as `float` and rounded to 2 decimal places
- Tax year extraction is **mandatory** — every parser must extract `tax_year`
- Each parser should be independently testable with sample PDF bytes
- Registration order in `_PARSERS` matters — more specific parsers
  (DFAS 1099-R) should come before generic ones to avoid misrouting

## Done Checklist

- [ ] DFAS 1099-R parser extracts pension distribution and tax withholding
- [ ] Fidelity 1099 parser extracts dividends, capital gains, interest
- [ ] Acorns 1099 parser extracts dividends and capital gains
- [ ] Affirm 1099-INT parser extracts HYSA interest earned
- [ ] NFCU 1098 parser extracts mortgage interest paid
- [ ] `_extract_pdf_text()` utility added to `BaseParser`
- [ ] All parsers registered in document drop chain
- [ ] `can_parse()` correctly differentiates between document types
- [ ] Tax summary endpoint aggregates cross-institution figures
- [ ] All parsers extract `tax_year`
- [ ] `pdfplumber` dependency added

## Verification

After completion, Claude will:
1. Verify all parsers follow `BaseParser` interface
2. Run import checks for all new parser modules
3. Verify parsers are registered in `_PARSERS` chain
4. Verify `can_parse()` detection logic differentiates document types
5. Verify `_extract_pdf_text()` is available as a shared method
6. Verify tax summary endpoint compiles
