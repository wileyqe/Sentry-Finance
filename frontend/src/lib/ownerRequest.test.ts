import { describe, expect, it } from "vitest";

import { withOwnerQuery } from "./ownerRequest";

describe("withOwnerQuery", () => {
  it("leaves a bare path unchanged without an owner or query", () => {
    expect(withOwnerQuery("/api/review/yearly", null)).toBe("/api/review/yearly");
  });

  it("treats an undefined runtime owner as absent", () => {
    expect(withOwnerQuery("/api/review/yearly", undefined as unknown as string | null)).toBe(
      "/api/review/yearly"
    );
  });

  it("adds query-only parameters", () => {
    expect(withOwnerQuery("/api/metrics/dti", null, { months: 12 })).toBe(
      "/api/metrics/dti?months=12"
    );
  });

  it("adds owner and query parameters together", () => {
    expect(withOwnerQuery("/api/review/monthly", "quintin", { month: "2026-04" })).toBe(
      "/api/review/monthly?month=2026-04&owner_id=quintin"
    );
  });

  it("skips null and undefined query values", () => {
    expect(
      withOwnerQuery("/api/cash-flow/period", "household", {
        account_id: undefined,
        category: null,
        period: "2026-04",
      })
    ).toBe("/api/cash-flow/period?period=2026-04&owner_id=household");
  });

  it("preserves existing query parameters", () => {
    expect(withOwnerQuery("/api/review/yearly?year=2026", null)).toBe(
      "/api/review/yearly?year=2026"
    );
  });

  it("appends an owner to an existing query string", () => {
    expect(withOwnerQuery("/api/review/yearly?year=2026", "amy")).toBe(
      "/api/review/yearly?year=2026&owner_id=amy"
    );
  });

  it("URL-encodes owner ids through URLSearchParams", () => {
    expect(withOwnerQuery("/api/accounts", "Quintin & Amy")).toBe(
      "/api/accounts?owner_id=Quintin+%26+Amy"
    );
  });

  it("stringifies numeric zero query values", () => {
    expect(withOwnerQuery("/api/recurring", null, { limit: 0 })).toBe("/api/recurring?limit=0");
  });

  it("stringifies false query values", () => {
    expect(withOwnerQuery("/api/transactions", null, { include_pending: false })).toBe(
      "/api/transactions?include_pending=false"
    );
  });
});
