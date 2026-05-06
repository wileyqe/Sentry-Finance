# Number-Trust Operator Guide

## Display-Precision Comparison

Every `api_oracle` value in `ui-number-registry.yaml` declares
`display_precision`. The API audit uses that field as the comparison boundary:
both sides are rounded to the registered precision first, then compared with
ordinary exact equality.

Rounding uses half-even ties, equivalent to:

```text
round(value / display_precision) * display_precision
```

Examples:

- `0.01`: currency and cent-level values
- `0.1`: one-decimal percentages or months of runway
- `1`: integer counts, labels, and credit scores
- `100`: compact currency rendered to the nearest hundred

When a comparison fails after display rounding, the diff shows:

- `expected` and `actual`: the rounded values that were compared
- `display_precision`: the registry precision used for the comparison
- `raw_expected` and `raw_actual`: the full values before rounding

Read the rounded pair first. If those differ, the rendered number can differ
for the user and the underlying oracle/API path needs investigation. Use the
raw pair to decide whether the issue came from source math, API shaping, or
formatter precision.
