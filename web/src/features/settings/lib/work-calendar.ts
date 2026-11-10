/** Tenant working calendar (D221): page-side shapes, labels and draft checks. The API decides. */

export type EntryKind = "holiday" | "makeup_workday" | "shutdown";
export type CalendarEntry = { kind: EntryKind; start: string; end: string; label: string; kind_label?: string; days?: number };
export type Basis = { basis: "tenant_calendar" | "weekdays_estimate"; basis_label: string; timezone: string; calendar_id?: string; calendar_name?: string; calendar_revision?: number };
export type WorkCalendar = {
  calendar_id: string; kind: "factory" | "supplier"; name: string; label: string; revision: number;
  timezone: string; working_weekdays: number[]; entries: CalendarEntry[]; reason: string;
  updated_at: string; updated_by: { id: string; name: string | null };
};
export type CalendarListing = { can_manage: boolean; basis: Basis; calendars: WorkCalendar[] };
export type Draft = { timezone: string; working_weekdays: number[]; entries: CalendarEntry[] };

export const KIND_LABELS: Record<EntryKind, string> = { holiday: "法定假日", makeup_workday: "调休上班", shutdown: "停线" };
export const WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
export const DEFAULT_DRAFT: Draft = { timezone: "Asia/Shanghai", working_weekdays: [1, 2, 3, 4, 5], entries: [] };
const DAY = 86_400_000;

const parse = (value: string) => Date.UTC(Number(value.slice(0, 4)), Number(value.slice(5, 7)) - 1, Number(value.slice(8, 10)));
export const isDay = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value) && new Date(parse(value)).toISOString().slice(0, 10) === value;
/** ISO weekday 1–7 of a YYYY-MM-DD local date. */
export const isoWeekday = (value: string) => ((new Date(parse(value)).getUTCDay() + 6) % 7) + 1;
export const spanDays = (entry: Pick<CalendarEntry, "start" | "end">) => Math.round((parse(entry.end) - parse(entry.start)) / DAY) + 1;

/** [1,2,3,4,5] → 周一至周五; gaps are listed one by one. */
export function weekdayText(days: number[]): string {
  const sorted = [...new Set(days)].sort((a, b) => a - b);
  if (!sorted.length) return "无";
  const contiguous = sorted.every((day, index) => index === 0 || day === sorted[index - 1] + 1);
  if (contiguous && sorted.length > 2) return `${WEEKDAYS[sorted[0] - 1]}至${WEEKDAYS[sorted.at(-1)! - 1]}`;
  return sorted.map(day => WEEKDAYS[day - 1]).join("、");
}

export function rangeText(entry: Pick<CalendarEntry, "start" | "end">): string {
  const days = spanDays(entry);
  return days === 1 ? entry.start : `${entry.start} 至 ${entry.end}（${days} 天）`;
}

export function sortEntries(entries: CalendarEntry[]): CalendarEntry[] {
  return [...entries].sort((a, b) => a.start.localeCompare(b.start) || a.end.localeCompare(b.end) || a.kind.localeCompare(b.kind) || a.label.localeCompare(b.label));
}

/** Plain-language problems with a draft; the server repeats every check. */
export function draftProblems(draft: Draft): string[] {
  const problems: string[] = [];
  if (!draft.working_weekdays.length) problems.push("至少选一个工作日。");
  const seen = new Set<string>();
  for (const entry of draft.entries) {
    const name = entry.label.trim() || "未写说明的登记";
    if (!entry.label.trim()) problems.push("每条登记都要写说明。");
    if (!isDay(entry.start) || !isDay(entry.end)) { problems.push(`${name}：日期不完整。`); continue; }
    if (entry.end < entry.start) problems.push(`${name}：结束日期早于开始日期。`);
    else if (spanDays(entry) > 366) problems.push(`${name}：单条登记不能超过 366 天。`);
    const key = `${entry.kind}|${entry.start}|${entry.end}|${entry.label.trim()}`;
    if (seen.has(key)) problems.push(`${name}：重复登记。`);
    seen.add(key);
    if (entry.kind === "makeup_workday" && entry.end >= entry.start && spanDays(entry) <= 366) {
      for (let at = parse(entry.start); at <= parse(entry.end); at += DAY) {
        const day = new Date(at).toISOString().slice(0, 10);
        if (draft.working_weekdays.includes(isoWeekday(day))) { problems.push(`${day} 本来就是工作日，不能登记为调休上班。`); break; }
        if (draft.entries.some(other => other.kind === "holiday" && other.start <= day && day <= other.end)) { problems.push(`${day} 同时登记了法定假日和调休上班。`); break; }
      }
    }
  }
  return [...new Set(problems)];
}

export function draftOf(calendar: WorkCalendar | null): Draft {
  if (!calendar) return { ...DEFAULT_DRAFT, entries: [] };
  return { timezone: calendar.timezone, working_weekdays: [...calendar.working_weekdays], entries: calendar.entries.map(({ kind, start, end, label }) => ({ kind, start, end, label })) };
}

export function definitionBody(draft: Draft, reason: string, requestKey: string) {
  return {
    timezone: draft.timezone,
    working_weekdays: [...draft.working_weekdays].sort((a, b) => a - b),
    entries: sortEntries(draft.entries).map(({ kind, start, end, label }) => ({ kind, start, end, label: label.trim() })),
    reason: reason.trim(),
    request_key: requestKey,
  };
}

/** Days off this calendar adds on usual working days within one year (for the summary line). */
export function yearSummary(calendar: Pick<WorkCalendar, "working_weekdays" | "entries">, year: number) {
  let off = 0, makeup = 0;
  for (let at = Date.UTC(year, 0, 1); at < Date.UTC(year + 1, 0, 1); at += DAY) {
    const day = new Date(at).toISOString().slice(0, 10), usual = calendar.working_weekdays.includes(isoWeekday(day));
    const covering = calendar.entries.filter(entry => entry.start <= day && day <= entry.end).map(entry => entry.kind);
    const closed = covering.includes("shutdown") || covering.includes("holiday");
    if (usual && closed) off += 1;
    if (!usual && !closed && covering.includes("makeup_workday")) makeup += 1;
  }
  return { off, makeup };
}

export function formatInstant(iso: string, timezone: string): string {
  return new Intl.DateTimeFormat("zh-CN", { timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit", weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(iso));
}

/** "YYYY-MM-DDTHH:mm" read as wall time in `timezone` (not the browser's), as an ISO instant. */
export function zonedInstant(local: string, timezone: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(local);
  if (!match) throw new Error("请填写完整的日期和时间。");
  const [year, month, day, hour, minute] = match.slice(1).map(Number);
  const wall = Date.UTC(year, month - 1, day, hour, minute);
  const format = new Intl.DateTimeFormat("en-US", { timeZone: timezone, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric" });
  const offset = (instant: number) => {
    const part = Object.fromEntries(format.formatToParts(new Date(instant)).map(item => [item.type, Number(item.value)]));
    return Date.UTC(part.year, part.month - 1, part.day, part.hour, part.minute) - instant;
  };
  const first = wall - offset(wall);
  return new Date(wall - offset(first)).toISOString();
}
