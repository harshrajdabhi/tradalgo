import { describe, it, expect } from "vitest";
import { formatRupees, formatR, formatPercent, gateVerdictText } from "./format";

describe("formatRupees", () => {
  it("formats positive values with the rupee sign", () => {
    expect(formatRupees(4200)).toBe("₹4,200");
  });
  it("formats negative values with a leading minus", () => {
    expect(formatRupees(-2100)).toBe("-₹2,100");
  });
});

describe("formatR", () => {
  it("prefixes a plus for positive R", () => {
    expect(formatR(1.2)).toBe("+1.2R");
  });
  it("does not prefix a plus for negative R", () => {
    expect(formatR(-1)).toBe("-1.0R");
  });
});

describe("formatPercent", () => {
  it("converts a fraction to a whole percent by default", () => {
    expect(formatPercent(0.54)).toBe("54%");
  });
});

describe("gateVerdictText", () => {
  it("states the reason when the gate did not pass", () => {
    expect(gateVerdictText(false, "62 trades (need 100)")).toBe(
      "Gate not passed — 62 trades (need 100)"
    );
  });
  it("is a plain pass statement otherwise", () => {
    expect(gateVerdictText(true, "")).toBe("Gate passed");
  });
});
