const dayFormatter = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" });
export function workDate(value: string) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : dayFormatter.format(new Date(value));
}
