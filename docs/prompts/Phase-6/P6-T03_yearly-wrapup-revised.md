# P6-T03: Yearly Wrap-Up Revised (Tax Document Integration)

## Context

You are working on Sentry Finance, a local-first personal finance app.
The `YearlyWrapUpPage.tsx` (P6-T02) is live and shows the preliminary
annual review. Tax document parsers (P4-T07) populate the `document_drops`
table with authoritative figures from 1099-R, consolidated 1099s, and 1098.

The gap: the yearly wrap-up currently estimates income and tax figures
from transaction data. Tax documents contain the **IRS-authoritative**
numbers. Once documents arrive (typically January–February), the user
should be able to upgrade the wrap-up from "Preliminary" to "Final."

### What changes in the "Revised" state

| Section | Preliminary source | Revised source |
|---|---|---|
| Gross pension income | Transaction sum | DFAS 1099-R Box 1 |
| Federal tax withheld | myPay RAS sum | DFAS 1099-R Box 4 |
| State tax withheld | myPay RAS sum | DFAS 1099-R Box 12 |
| Investment dividends | Transaction categories | Fidelity/Acorns 1099-DIV |
| Capital gains | (not tracked) | Fidelity/Acorns 1099-B |
| Interest earned | Transaction categories | Affirm 1099-INT |
| Mortgage interest paid | Transaction categories | NFCU 1098 Box 1 |

### Expected documents checklist

For this user, the expected annual tax documents are:
- `dfas_1099r` — DFAS 1099-R (Military Pension)
- `fidelity_1099` — Fidelity Consolidated 1099
- `acorns_1099` — Acorns 1099
- `affirm_1099int` — Affirm 1099-INT
- `nfcu_1098` — NFCU 1098

The wrap-up upgrades to "Final" **only** when all 5 documents for the
target year are present in `document_drops` with `status = 'committed'`.

## Starting State

From P4-T07:
- `document_drops` table with `parser_type`, `parsed_fields` (JSON),
  `status`, and `dropped_at` columns
- `GET /api/documents/tax-summary/{year}` endpoint returns parsed fields
  aggregated by document type

From P6-T02:
- `dal/yearly_wrapup.py` with `get_yearly_wrapup(conn, year)` returning
  `{"status": "preliminary", ...}` — ready to be extended
- `GET /api/review/yearly` endpoint
- `YearlyWrapUpPage.tsx` with "Preliminary" badge already rendered

## Task

### 1. Extend `dal/yearly_wrapup.py`

Add two new functions and modify `get_yearly_wrapup()`:

#### `get_tax_doc_checklist(conn, year) -> dict`

```python
def get_tax_doc_checklist(conn: sqlite3.Connection, year: int) -> dict:
    """
    Check which expected tax documents have been received for the year.

    Returns:
    {
        "year": int,
        "all_received": bool,
        "documents": [
            {
                "parser_type": str,
                "label": str,          # human-readable name
                "received": bool,
                "committed_at": "YYYY-MM-DDTHH:MM:SS" | None,
                "key_fields": dict | None,  # parsed fields if received
            }, ...
        ],
    }
    """
```

Expected documents and labels:
```python
_EXPECTED_TAX_DOCS = [
    ("dfas_1099r",    "DFAS 1099-R (Military Pension)"),
    ("fidelity_1099", "Fidelity Consolidated 1099"),
    ("acorns_1099",   "Acorns 1099"),
    ("affirm_1099int","Affirm 1099-INT"),
    ("nfcu_1098",     "NFCU 1098"),
]
```

Query `document_drops` for each `parser_type` where
`json_extract(parsed_fields, '$.tax_year') = ?` and
`status = 'committed'`. Mark `received = True` if a row exists.
`all_received = True` only when every expected document is received.

#### `overlay_tax_documents(conn, year, wrapup) -> dict`

```python
def overlay_tax_documents(
    conn: sqlite3.Connection,
    year: int,
    wrapup: dict,
) -> dict:
    """
    Takes the preliminary wrapup dict and overlays authoritative tax
    document figures where available. Returns a modified copy.

    Sets wrapup["status"] = "final" if all expected docs are present.
    Sets wrapup["status"] = "revised" if some docs are present.
    Sets wrapup["tax_doc_checklist"] = get_tax_doc_checklist() result.
    Sets wrapup["tax_overrides"] = dict of what was overridden and by how much.
    """
```

**Overlay logic:**

1. Call `get_tax_doc_checklist(conn, year)` and attach as
   `wrapup["tax_doc_checklist"]`.

2. For each received document, pull `parsed_fields` from `document_drops`
   and apply to the wrapup:

   - **`dfas_1099r`**: Override `income_by_stream` entry for
     "Military Pension" with `gross_distribution`. Add/override
     `federal_tax_withheld` and `state_tax_withheld` top-level keys.

   - **`fidelity_1099`**: Add `investment_income` sub-dict to
     `investment_performance` row for Fidelity account with
     `ordinary_dividends`, `qualified_dividends`, `capital_gain_distributions`,
     `total_proceeds`, `total_cost_basis`.

   - **`acorns_1099`**: Same as Fidelity for Acorns account.

   - **`affirm_1099int`**: Override `interest.total_earned` with
     `interest_income`.

   - **`nfcu_1098`**: Override `interest.total_paid` (mortgage component)
     with `mortgage_interest_received`. Add `mortgage_insurance_premiums`
     and `property_taxes` to an `interest` sub-key.

3. Record each override in `wrapup["tax_overrides"]`:
   ```python
   {
       "military_pension_gross": {
           "preliminary": <old_value>,
           "authoritative": <new_value>,
           "source": "dfas_1099r",
       },
       ...
   }
   ```

4. Set `wrapup["status"]`:
   - `"final"` — all 5 expected documents received
   - `"revised"` — 1–4 documents received
   - `"preliminary"` — 0 documents received (unchanged)

#### Modify `get_yearly_wrapup()` to call the overlay:

```python
def get_yearly_wrapup(conn, year):
    wrapup = _build_preliminary(conn, year)       # existing logic
    wrapup = overlay_tax_documents(conn, year, wrapup)
    return wrapup
```

Rename the existing `get_yearly_wrapup` logic to `_build_preliminary`
(private) so the public function always attempts the overlay.

### 2. Backend: Checklist Endpoint

Add to `backend/routers/reports.py`:

```python
@router.get("/api/review/yearly/tax-checklist")
def tax_doc_checklist(year: int | None = None):
    """
    Returns the tax document checklist for the given year.
    Used by the frontend to render the document receipt status.
    """
    if year is None:
        year = date.today().year - 1
    with get_db() as conn:
        return get_tax_doc_checklist(conn, year)
```

### 3. Frontend: Extend `YearlyWrapUpPage.tsx`

**Status badge changes:**
- "Preliminary" (amber) → "Revised" (blue) → "Final" (green)
- Badge driven by `data.status` from the API response.

**Tax document checklist toast / panel:**

Add a collapsible **"Tax Documents"** section below the header strip.

When collapsed (default): shows a compact badge — e.g.,
"Tax Documents: 3 / 5 received" with a document icon.

When expanded: a checklist table:

| Document | Status | Received |
|---|---|---|
| DFAS 1099-R | ✓ Received | Jan 28, 2026 |
| Fidelity 1099 | ✓ Received | Feb 3, 2026 |
| Acorns 1099 | ⏳ Pending | — |
| Affirm 1099-INT | ✓ Received | Jan 15, 2026 |
| NFCU 1098 | ⏳ Pending | — |

Pending documents show a "Drop File →" link that navigates to `/documents`.

**Tax overrides diff panel:**
If `data.tax_overrides` is non-empty, render a "What Changed" expandable
panel listing each override as:
> Military Pension Gross: `$42,000.00` (estimated) → `$43,816.20` (DFAS 1099-R)

Green if the authoritative value is higher, red if lower.

## Files to Modify

1. `dal/yearly_wrapup.py` — add `get_tax_doc_checklist()`,
   `overlay_tax_documents()`, rename existing logic to `_build_preliminary()`
2. `backend/routers/reports.py` — add `/api/review/yearly/tax-checklist`
3. `frontend/src/pages/YearlyWrapUpPage.tsx` — status badge, checklist,
   diff panel

## Files NOT to Modify

- `dal/parsers/*.py` — parsers are complete; read their output via SQL
- `dal/document_drop.py` — no changes needed
- Any migration files — `document_drops` schema is already correct

## Constraints

- The overlay function must NOT mutate the dict in-place — work on a
  copy (`import copy; wrapup = copy.deepcopy(wrapup)`) to keep
  `_build_preliminary` testable in isolation.
- `all_received` must be driven by `_EXPECTED_TAX_DOCS` — never hardcode
  a count. Adding a new expected doc to that list must automatically
  change the threshold.
- Status hierarchy: `preliminary < revised < final`. Never downgrade
  (e.g., if status is already `"final"` and re-run finds 4 docs, that
  shouldn't happen, but defend against it).
- The checklist endpoint must be callable independently of the full
  yearly wrap-up endpoint (it's faster and the frontend polls it).
- Do NOT show the "What Changed" panel unless at least one override exists.

## Done Checklist

- [ ] `get_tax_doc_checklist()` queries all 5 expected document types
- [ ] `overlay_tax_documents()` works on a deep copy of the wrapup dict
- [ ] Each parser type's fields are overlaid to the correct wrapup section
- [ ] `tax_overrides` dict records preliminary vs. authoritative per field
- [ ] Status: "preliminary" / "revised" / "final" based on doc count
- [ ] `get_yearly_wrapup()` always attempts the overlay
- [ ] `GET /api/review/yearly/tax-checklist` endpoint added
- [ ] Frontend badge updates color based on `data.status`
- [ ] Checklist panel (collapsed/expanded) renders correctly
- [ ] "Drop File →" link on pending documents
- [ ] "What Changed" diff panel renders overrides

## Verification

After completion, Claude will:
1. Verify `overlay_tax_documents()` operates on a deep copy
2. Verify `_EXPECTED_TAX_DOCS` drives `all_received` (no hardcoded count)
3. Run `python -c "from dal.yearly_wrapup import get_tax_doc_checklist"` — no errors
4. Write pytest tests:
   a. `get_tax_doc_checklist()` returns all 5 expected docs, all pending,
      on an empty DB
   b. After inserting a committed `dfas_1099r` doc, `received = True`
      for that entry
   c. `overlay_tax_documents()` sets `status = "revised"` with 1 doc,
      `"final"` with all 5
   d. A field override appears correctly in `tax_overrides`
   e. Original wrapup dict is not mutated by the overlay
5. All tests pass
