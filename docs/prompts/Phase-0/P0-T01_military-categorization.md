# P0-T01: Income Stream & Categorization Rules

## Context

You are working on Sentry Finance, a local-first personal finance app.
The transaction categorization engine uses regex rules defined in
`config/categories.yaml`. These rules are evaluated top-to-bottom,
first match wins, against transaction descriptions.

The current ruleset covers common civilian merchants but is missing
patterns for the owner's specific income streams. The owner is a
retired military member living in Bloomington, IN — not near a military
base. The focus of this task is accurate income categorization, not
military-specific shopping (which is irrelevant to the owner's daily life).

## Starting State

- `config/categories.yaml` exists with ~100 regex rules
- `dal/categorization.py` loads and applies these rules (do NOT modify this file)
- The owner receives four income streams, all depositing into NFCU:
  1. Military pension via DFAS (monthly, stable)
  2. VA disability compensation (monthly, stable)
  3. VA education benefits during enrollment (episodic)
  4. Sports officiating payments from various school districts (seasonal, Aug-Mar)
- The existing DFAS rule on line 17 catches "DFAS|DISA|DEF FIN|MILITARY PAY|RET ALT"
  and maps to "Paychecks/Salary" — this is too generic. Pension income
  should be its own category, distinct from a paycheck.

## Task

Add new regex rules to `config/categories.yaml` for the income patterns
listed below. Insert them in the Income section, BEFORE the generic
"Direct Deposit" rule so specific patterns match first.

### Rules to Add

**Income — Pension, VA, and Officiating (add to the Income section,
BEFORE the existing DFAS rule on line 17, which should then be updated
or left as a fallback):**

```yaml
# Military pension (retired pay via DFAS)
- pattern: "DFAS.*RET|RETIRED PAY|DFAS-CL.*RET"
  category: "Military Pension"

# VA disability compensation
- pattern: "VA BEN|VETERANS AFFAIRS|VA COMP|VETTEC"
  category: "VA Benefits"

# VA education benefits (GI Bill / VR&E)
- pattern: "VA CH33|VA EDU|VA CHAPTER|VRNE|VR&E|VA.*EDUCATION"
  category: "VA Education Benefits"

# Sports officiating income (multiple school districts, Eventlink)
- pattern: "OFFICIATING|ATHLETIC.*ASSOC|SCHOOL.*DIST|EVENTLINK|ARBITER"
  category: "Officiating Income"
```

**Important:** These four rules MUST appear BEFORE the existing DFAS
rule (line 17). The existing DFAS rule can remain as a catch-all fallback
for any DFAS transactions that don't match the more specific pension
pattern above. Do NOT delete the existing DFAS rule — just ensure the
new pension rule is tested first by the engine (higher in the file).

### Update Income Category Sets

Add "Military Pension", "VA Benefits", "VA Education Benefits", and
"Officiating Income" to the `_INCOME_CATEGORIES` set in TWO files:

1. `dal/reports.py` — the `_INCOME_CATEGORIES` set near line 22
2. `dal/cash_flow.py` — the `_INCOME_CATEGORIES` set near line 15

These sets control what is counted as income vs. spending in all
analytical queries. If a category is not in these sets, transactions
in that category are counted as spending — which would be wrong for
income.

## Files to Modify

1. `config/categories.yaml` — add 4 new income rules
2. `dal/reports.py` — add 4 new income categories to `_INCOME_CATEGORIES`
3. `dal/cash_flow.py` — add 4 new income categories to `_INCOME_CATEGORIES`

## Files NOT to Modify

- `dal/categorization.py` — the engine is fine, only the rules need updating
- `dal/derived.py` — it imports from `dal/reports.py`, will pick up changes
- Any frontend files
- Any connector files
- Any other DAL files

## Constraints

- Preserve existing rules exactly as they are — only ADD new rules
- Do NOT add military shopping patterns (AAFES, DECA, commissary, NEX,
  MWR, etc.) — the owner does not shop on military bases
- New income rules MUST go BEFORE the existing DFAS rule (line 17) so
  the specific pension pattern matches before the generic DFAS pattern
- Do NOT delete or modify the existing DFAS rule — it serves as a fallback
- Use the same YAML formatting style as existing rules (2-space indent,
  quoted patterns, quoted categories)
- Pattern regexes should be case-insensitive (the engine applies `re.IGNORECASE`)
- Keep patterns broad enough to catch variations but specific enough to
  avoid false positives
- The four new income categories must appear in BOTH `_INCOME_CATEGORIES`
  sets (reports.py AND cash_flow.py) or income/spending calculations will
  be wrong

## Done Checklist

- [ ] `config/categories.yaml` has 4 new income rules in the Income section
- [ ] New rules are placed BEFORE the existing DFAS rule (line 17)
- [ ] The existing DFAS rule is preserved (not deleted or modified)
- [ ] No military shopping patterns were added (AAFES, DECA, NEX, etc.)
- [ ] `dal/reports.py` `_INCOME_CATEGORIES` includes all 4 new income categories
- [ ] `dal/cash_flow.py` `_INCOME_CATEGORIES` includes all 4 new income categories
- [ ] Both `_INCOME_CATEGORIES` sets contain the same categories (identical)
- [ ] No existing rules were modified or removed
- [ ] File formatting is consistent with existing style

## Verification

After completion, Claude will:
1. Read all three modified files
2. Verify new rules are syntactically correct YAML
3. Verify income categories match between reports.py and cash_flow.py
4. Verify rule ordering (specific pension rule before generic DFAS rule)
5. Verify no military shopping patterns were added
6. Grep for any duplicate patterns that could conflict
