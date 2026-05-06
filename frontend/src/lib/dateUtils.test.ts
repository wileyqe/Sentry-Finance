import { describe, expect, it } from "vitest";

import {
  MONTH_ABBR,
  MONTH_FULL,
  formatIsoDate,
  formatMonthYearFull,
  monthKeyFromDate,
  monthWindowFromIso,
  parseIsoDateLocal,
} from "./dateUtils";

describe("dateUtils", () => {
  it("formats local Date values as YYYY-MM-DD", () => {
    expect(formatIsoDate(new Date(2026, 4, 6))).toBe("2026-05-06");
  });

  it("parses ISO dates into local calendar components", () => {
    const parsed = parseIsoDateLocal("2026-05-06");

    expect(parsed.getFullYear()).toBe(2026);
    expect(parsed.getMonth()).toBe(4);
    expect(parsed.getDate()).toBe(6);
  });

  it("exposes stable month abbreviations and full names", () => {
    expect(MONTH_ABBR[0]).toBe("Jan");
    expect(MONTH_ABBR[11]).toBe("Dec");
    expect(MONTH_FULL[0]).toBe("January");
    expect(MONTH_FULL[11]).toBe("December");
  });

  it("derives month keys and month windows from local dates", () => {
    expect(monthKeyFromDate(new Date(2026, 1, 14))).toBe("2026-02");
    expect(monthWindowFromIso("2026-02-14")).toEqual({
      start: "2026-02-01",
      end: "2026-02-28",
    });
  });

  it("formats month-year labels and rejects malformed input", () => {
    expect(formatMonthYearFull("2026-06")).toBe("June 2026");
    expect(formatMonthYearFull("2026-13")).toBe("");
    expect(formatMonthYearFull("not-a-month")).toBe("");
  });
});
