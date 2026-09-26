import { describe, expect, it } from "vitest";

import { decimalText, isZeroDecimal } from "./decimal";

describe("decimalText", () => {
  it("drops the fixed scale the server sends", () => {
    expect(decimalText("5.00000000")).toBe("5");
    expect(decimalText("1.50000000")).toBe("1.5");
    expect(decimalText("6.000000")).toBe("6");
    expect(decimalText("0.00012300")).toBe("0.000123");
  });

  it("renders Python exponent zeros and exponents as plain numbers", () => {
    expect(decimalText("0E-8")).toBe("0");
    expect(decimalText("-0E-8")).toBe("0");
    expect(decimalText("1.2E+3")).toBe("1200");
    expect(decimalText("5E-7")).toBe("0.0000005");
  });

  it("keeps precision beyond floating point", () => {
    expect(decimalText("12345678901234567890.12345678")).toBe("12345678901234567890.12345678");
    expect(decimalText("-3.10")).toBe("-3.1");
  });

  it("marks missing values and leaves unparseable text unchanged", () => {
    expect(decimalText(null)).toBe("未知");
    expect(decimalText(undefined, "—")).toBe("—");
    expect(decimalText("")).toBe("未知");
    expect(decimalText("待核对")).toBe("待核对");
    expect(decimalText("1E+99999")).toBe("1E+99999");
  });
});

describe("isZeroDecimal", () => {
  it("recognises every zero form", () => {
    for (const value of ["0", "0.00000000", "0E-8", "-0E-8", "0.0", ".0"]) expect(isZeroDecimal(value)).toBe(true);
  });

  it("rejects non-zero, missing and unparseable values", () => {
    for (const value of ["1", "0.00000001", "1E-8", null, undefined, "", "abc"]) expect(isZeroDecimal(value)).toBe(false);
  });
});
