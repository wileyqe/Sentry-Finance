/**
 * Centralized institution display-name map.
 *
 * Converts raw backend keys (lowercase slugs) into human-readable
 * names with correct casing for acronyms.  Falls back to the raw
 * value if no entry is found.
 */

const INSTITUTION_DISPLAY_NAMES: Record<string, string> = {
  nfcu:           "NFCU",
  amex:           "AMEX",
  usaa:           "USAA",
  chase:          "Chase",
  fidelity:       "Fidelity",
  acorns:         "Acorns",
  acorns_synthetic: "Acorns Synthetic",
  tsp:            "TSP",
  affirm:         "Affirm",
  dfas:           "DFAS",
  brighton:       "Brighton",
  coastal:        "Coastal",
  greenleaf:      "Greenleaf",
  payflex:        "PayFlex",
  rocket:         "Rocket",
  summit:         "Summit",
  vanguard_prime: "Vanguard",
  mypay:          "myPay",
};

/**
 * Look up the display name for an institution key.
 * Falls back to the raw key if not mapped.
 */
export function institutionDisplayName(raw: string): string {
  return INSTITUTION_DISPLAY_NAMES[raw.toLowerCase()] ?? raw;
}
