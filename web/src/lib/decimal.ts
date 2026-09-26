// Server quantities arrive as Python Decimal strings: fixed scale ("5.00000000") and, for a
// zero at that scale, exponent form ("0E-8"). Format them as text without float conversion.
const DECIMAL = /^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d{1,4}))?$/;

function plainDecimal(value: string): string | null {
  const match = DECIMAL.exec(value.trim());
  if (!match || (!match[2] && !match[3])) return null;
  const [, sign, whole = "", fraction = "", exponent = "0"] = match;
  let digits = whole + fraction;
  let point = whole.length + Number(exponent);
  if (point < 0) {
    digits = "0".repeat(-point) + digits;
    point = 0;
  }
  if (point > digits.length) digits += "0".repeat(point - digits.length);
  const integer = digits.slice(0, point).replace(/^0+(?=\d)/, "") || "0";
  const decimals = digits.slice(point).replace(/0+$/, "");
  const text = decimals ? `${integer}.${decimals}` : integer;
  return text === "0" ? "0" : `${sign === "-" ? "-" : ""}${text}`;
}

/** "5.00000000" → "5", "0E-8" → "0", "1.50" → "1.5"; unparseable text is shown unchanged. */
export function decimalText(value: string | null | undefined, missing = "未知"): string {
  if (value === null || value === undefined || value === "") return missing;
  return plainDecimal(value) ?? value;
}

/** True only for a parseable zero, including exponent forms such as "0E-8". */
export function isZeroDecimal(value: string | null | undefined): boolean {
  return typeof value === "string" && plainDecimal(value) === "0";
}
