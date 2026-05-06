import { describe, expect, it } from "vitest";

import { formatCurrency } from "./formatCurrency";

describe("formatCurrency", () => {
  it("formats nullish and NaN values as zero dollars", () => {
    expect(formatCurrency(null)).toBe("$0.00");
    expect(formatCurrency(undefined)).toBe("$0.00");
    expect(formatCurrency(Number.NaN)).toBe("$0.00");
  });

  it("formats zero with two decimal places", () => {
    expect(formatCurrency(0)).toBe("$0.00");
  });

  it("places the negative sign before the dollar sign", () => {
    expect(formatCurrency(-1234.5)).toBe("-$1,234.50");
  });

  it("formats large values with thousands separators", () => {
    expect(formatCurrency(1234567.89)).toBe("$1,234,567.89");
  });

  it("rounds to cents using the browser currency display convention", () => {
    expect(formatCurrency(43.5)).toBe("$43.50");
    expect(formatCurrency(43.567)).toBe("$43.57");
  });
});
