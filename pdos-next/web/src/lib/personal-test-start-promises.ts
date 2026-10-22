export type TestStartMoment = { occurred_at: string; original_timezone: string; effective_at: string | null };
export type PersonalTestStartPromise = {
  id: string; recorded_at: string;
  category: { id: string; name: string }; product: { id: string; name: string }; project: { id: string; name: string }; build: { id: string; name: string };
  request: { id: string }; run: { id: string; revision: number; status: "planned" | "running" | "results_pending" | "reviewed" | "disposed" };
  promise: TestStartMoment; actual_start: (TestStartMoment & { received_at: string }) | null;
  recipient: null; recipient_status: "not_recorded";
  timing: "awaiting_start" | "past_due_no_start_record" | "started_on_or_before" | "started_late";
  coverage: { sample_count: number; item_count: number; pair_count: number };
};
export type PersonalTestStartPromisePage = {
  version: "personal-test-start-promises/v1"; principal_id: string; as_of: string;
  total_records: number; items: PersonalTestStartPromise[]; next_cursor: string | null;
};

export function personalTestStartPromisesPath(cursor: string | null = null) {
  return `v1/personal/test-start-promises?page_size=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`;
}
export function testStartWorkbenchHref(item: PersonalTestStartPromise) {
  const params = new URLSearchParams({ area: "category", category: item.category.id, bench: "projects", view: "verification", task: "launch", product: item.product.id, project: item.project.id });
  return `/?${params}`;
}

const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const count = (value: unknown) => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
const time = (value: unknown): value is string => text(value) && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
function zone(value: unknown): value is string {
  if (!text(value)) return false;
  try { new Intl.DateTimeFormat("en", { timeZone: value }); return true; } catch { return false; }
}
const moment = (value: unknown) => record(value) && time(value.occurred_at) && zone(value.original_timezone) && (value.effective_at === null || time(value.effective_at));
const named = (value: unknown) => record(value) && text(value.id) && typeof value.name === "string";

/** The server owns temporal classification and the current actor's readable scope. */
export function isPersonalTestStartPromisePage(value: unknown, principalId: string): value is PersonalTestStartPromisePage {
  return record(value) && value.version === "personal-test-start-promises/v1" && value.principal_id === principalId && time(value.as_of)
    && count(value.total_records) && (value.next_cursor === null || text(value.next_cursor)) && Array.isArray(value.items)
    && value.items.every(item => record(item) && text(item.id) && time(item.recorded_at)
      && named(item.category) && named(item.product) && named(item.project) && named(item.build) && record(item.request) && text(item.request.id)
      && record(item.run) && text(item.run.id) && count(item.run.revision) && Number(item.run.revision) > 0 && ["planned", "running", "results_pending", "reviewed", "disposed"].includes(String(item.run.status))
      && moment(item.promise) && (item.actual_start === null || record(item.actual_start) && moment(item.actual_start) && time(item.actual_start.received_at))
      && item.recipient === null && item.recipient_status === "not_recorded"
      && ["awaiting_start", "past_due_no_start_record", "started_on_or_before", "started_late"].includes(String(item.timing))
      && record(item.coverage) && ["sample_count", "item_count", "pair_count"].every(field => count((item.coverage as Record<string, unknown>)[field])));
}

/** Display in the recorded timezone without rounding away stored subsecond digits. */
export function originalTestStartTime(value: TestStartMoment): string {
  const formatter = new Intl.DateTimeFormat("en-GB", { timeZone: value.original_timezone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
  const parts = Object.fromEntries(formatter.formatToParts(new Date(value.occurred_at)).map(part => [part.type, part.value]));
  const fraction = /\.(\d+)(?:Z|[+-]\d{2}:\d{2})$/.exec(value.occurred_at)?.[1];
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}${fraction ? `.${fraction}` : ""} ${value.original_timezone}`;
}

export function mergeTestStartPromises(previous: readonly PersonalTestStartPromise[], incoming: readonly PersonalTestStartPromise[]) {
  const result = new Map(previous.map(item => [item.id, item]));
  for (const item of incoming) result.set(item.id, item);
  return [...result.values()];
}
