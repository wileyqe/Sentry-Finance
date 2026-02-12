# Code Quality Issues - Project Antigravity

This document tracks identified code quality issues and technical debt in the dashboard codebase.

---

## **1. Data Loading Performance**
- **Issue**: All CSVs are loaded at module level (lines 138-148), forcing a full reload on every code change during development
- **Fix**: Move data loading into a cached function or lazy-load on first dashboard render

---

## **2. Inefficient Category Application**
- **Issue**: Line 153-154 uses `apply(lambda x: ..., axis=1)` which iterates row-by-row (extremely slow on large datasets)
- **Fix**: Use vectorized `.map()` directly on the `description` column: `ALL["category"] = ALL["description"].map(CAT_MAP).fillna(ALL["category"])`

---

## **3. Global State Mutation in Callbacks**
- **Issue**: Lines 454 and 484 directly mutate the global `ALL` DataFrame from within callbacks
- **Fix**: Callbacks should be pure functions. Either reload data from disk after category changes, or use a proper state management pattern (e.g., storing category overrides separately and joining on demand)

---

## **4. Hardcoded File Paths**
- **Issue**: CSV_MANIFEST (lines 129-135) has hardcoded relative paths like `BASE / "NavyFed" / "checking" / ...`
- **Fix**: Move to a configuration file (YAML/JSON) that defines data sources with flexible path patterns

---

## **5. Duplicate Categorization Logic**
- **Issue**: `_chase_categorize()` has its own hardcoded keyword mapping (lines 112-123), separate from NFCU's CSV categories and `category_map.json`
- **Fix**: Use a single unified categorization system. Apply `category_map.json` to all institutions after initial load, with a fallback hierarchy: manual override → CSV category → keyword matching → "Uncategorized"

---

## **6. Hardcoded Business Logic in Callbacks**
- **Issue**: 
  - Officiating income regex (lines 586-588) contains a massive hardcoded pattern
  - Subscription keywords (lines 608-612) are hardcoded in the callback
  - Excluded categories for transfers (line 419) are hardcoded
- **Fix**: Move all of these to a `config.json` file with sections like `"officiating_keywords"`, `"subscription_keywords"`, `"excluded_categories"`

---

## **7. Silent Error Handling**
- **Issue**: Try/except blocks (lines 23-27, 142-146, 664-667) catch all exceptions without logging
- **Fix**: Use proper logging with `import logging` and log errors before returning fallbacks. At minimum, use `traceback.print_exc()` (which you do in one place but not others)

---

## **8. Missing Data Validation**
- **Issue**: CSV loading assumes columns exist without validation. If a column is missing, it silently assigns hardcoded defaults (e.g., line 71: `"debit"`, line 100: `"sale"`)
- **Fix**: Validate that required columns exist before processing. Raise informative errors if critical columns are missing, or log warnings for optional ones

---

## **9. Unused Color Definitions**
- **Issue**: `CATEGORY_COLORS` is defined (line 168) but the pie chart uses `marker=dict(colors=CATEGORY_COLORS)` which may not map correctly to your category order
- **Fix**: Either create a category→color mapping dictionary or remove the unused definition

---

## **10. Inefficient Table Data Preparation**
- **Issue**: Lines 642-643 create `date_str` and `amount_str` display columns every time the callback runs
- **Fix**: Pre-compute these columns once during data loading, not on every filter change

---

## **11. Category Filter Timing**
- **Issue**: Line 639-640 filters the table by category *after* creating the full `table_df`, which means pagination/sorting happens on the filtered subset
- **Fix**: Apply category filter earlier in the `filter_data()` function for consistency

---

## **12. Inconsistent Excluded Categories**
- **Issue**: The excluded categories list (line 419) includes `"Credit Card Payment"` (singular) but your category_map.json saves `"Credit Card Payments"` (plural)
- **Fix**: Standardize category names across the codebase, or use case-insensitive matching with normalization

---

## **13. Complex Modal State Management**
- **Issue**: The callback for category editing (lines 444-491) tracks state across multiple inputs/outputs and has complex conditional logic
- **Fix**: Consider using `dcc.Store` more explicitly to track "pending edit" state, or simplify by auto-refreshing the page after category changes

---

## **14. No Environment Configuration**
- **Issue**: No way to switch between dev/prod data sources or customize settings without editing code
- **Fix**: Use environment variables or a `config.yaml` file with sections for paths, colors, filters, etc.

---

## **15. Single Monolithic File**
- **Issue**: Everything is in one 691-line file
- **Fix**: Split into modules:
  - `loaders.py`: Data loading functions
  - `categorization.py`: Category mapping logic
  - `filters.py`: Data filtering functions
  - `layouts.py`: Dash layout components
  - `callbacks.py`: Callback functions
  - `config.py`: Configuration loading
  - `app.py`: Main app runner

---

## Priority Recommendations

**Quick Wins (Low Effort, High Impact):**
- Issue #2: Inefficient Category Application
- Issue #7: Silent Error Handling
- Issue #9: Unused Color Definitions
- Issue #12: Inconsistent Excluded Categories

**Medium Priority (Improves Maintainability):**
- Issue #4: Hardcoded File Paths
- Issue #5: Duplicate Categorization Logic
- Issue #6: Hardcoded Business Logic
- Issue #14: No Environment Configuration

**Long-term Refactors (High Effort, High Value):**
- Issue #15: Single Monolithic File
- Issue #3: Global State Mutation
- Issue #1: Data Loading Performance

**Nice to Have:**
- Issue #8: Missing Data Validation
- Issue #10: Inefficient Table Data Preparation
- Issue #11: Category Filter Timing
- Issue #13: Complex Modal State Management
