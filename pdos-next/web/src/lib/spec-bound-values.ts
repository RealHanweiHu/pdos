type Numeric = string | number | null | undefined;

export function numericValueText(value: Numeric, lower: Numeric, upper: Numeric, format: (value: string) => string = value => value): string {
  if (value != null) return format(String(value));
  if (lower != null && upper != null) return `${format(String(lower))} ～ ${format(String(upper))}`;
  if (lower != null) return `≥${format(String(lower))}`;
  if (upper != null) return `≤${format(String(upper))}`;
  return "未知";
}

export function numericShapeProblem(type: string, value: Numeric, lower: Numeric, upper: Numeric, text?: string | null): string | null {
  const bounded = lower != null || upper != null;
  if (text != null) return "数值条目不能混填文字目标。";
  if (type === "number" && value != null && !bounded) return null;
  if (["number", "range"].includes(type) && value == null && bounded) return null;
  return type === "number" ? "请填写目标值或至少一个上下限，不能混填；零也是有效值。" : "请填写至少一个上下限，不另填单值。";
}
