import { cookies } from "next/headers";
import type { NextRequest } from "next/server";
import { sameOrigin } from "@/lib/server/request-origin";

/** Tenant working calendar BFF (D221). Everyone reads; the API decides who may save. */
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const day = /^\d{4}-\d{2}-\d{2}$/;
const kinds = new Set(["holiday", "makeup_workday", "shutdown"]);
const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
const isRecord = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown, max: number) => typeof value === "string" && value.trim().length > 0 && value.length <= max;
const exactKeys = (value: Record<string, unknown>, allowed: string[], required: string[]) => Object.keys(value).every(key => allowed.includes(key)) && required.every(key => key in value);
const fail = (message: string, status: number, code = "VALIDATION_FAILED") => Response.json({ code, message }, { status, headers });

async function forward(path: string, method: "GET" | "POST", body?: unknown) {
  const token = (await cookies()).get("pdos-next-session")?.value;
  if (!token) return fail("请进入有效会话。", 401, "FORBIDDEN_SCOPE");
  const base = process.env.PDOS_NEXT_API_URL;
  if (!base) return fail("服务尚未配置。", 503, "SOURCE_UNAVAILABLE");
  try {
    const response = await fetch(`${base}${path}`, {
      method, headers: { Authorization: `Bearer ${token}`, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
      body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store", redirect: "error", signal: AbortSignal.timeout(30000),
    });
    return new Response(await response.arrayBuffer(), { status: response.status, headers: { ...headers, "Content-Type": response.headers.get("Content-Type") ?? "application/json" } });
  } catch {
    return method === "GET"
      ? fail("暂未读取到工作日历，请重新读取。", 503, "SOURCE_UNAVAILABLE")
      : fail("暂未取得保存回执，请刷新工作日历核对是否已保存。", 503, "EXTERNAL_OUTCOME_UNKNOWN");
  }
}

async function json(request: NextRequest): Promise<unknown> {
  const raw = await request.text();
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

function entry(value: unknown) {
  return isRecord(value) && exactKeys(value, ["kind", "start", "end", "label"], ["kind", "start", "end", "label"])
    && typeof value.kind === "string" && kinds.has(value.kind)
    && typeof value.start === "string" && day.test(value.start) && typeof value.end === "string" && day.test(value.end)
    && text(value.label, 80);
}

/** The definition fields both create and save carry; the API checks their meaning. */
function definition(value: Record<string, unknown>) {
  return (value.timezone === undefined || text(value.timezone, 64))
    && Array.isArray(value.working_weekdays) && value.working_weekdays.length >= 1 && value.working_weekdays.length <= 7
    && value.working_weekdays.every(item => Number.isInteger(item) && item >= 1 && item <= 7)
    && Array.isArray(value.entries) && value.entries.length <= 500 && value.entries.every(entry)
    && text(value.reason, 200) && typeof value.request_key === "string" && uuid.test(value.request_key);
}
const definitionKeys = ["timezone", "working_weekdays", "entries", "reason", "request_key"];

export async function listCalendars(request: NextRequest) {
  if (request.nextUrl.searchParams.size) return fail("工作日历只按当前租户读取。", 422);
  return forward("/v1/work-calendars", "GET");
}

export async function createCalendar(request: NextRequest) {
  if (!sameOrigin(request)) return fail("请求来源不匹配。", 403, "FORBIDDEN_SCOPE");
  const value = await json(request);
  if (!isRecord(value) || !exactKeys(value, ["kind", "name", ...definitionKeys], ["kind", "working_weekdays", "entries", "reason", "request_key"])
    || !(value.kind === "factory" || value.kind === "supplier")
    || (value.kind === "supplier" ? !text(value.name, 80) : value.name !== undefined && value.name !== null)
    || !definition(value)) return fail("请完整填写日历内容。", 422);
  return forward("/v1/work-calendars", "POST", value);
}

export async function workingDays(request: NextRequest) {
  const query = request.nextUrl.searchParams;
  const at = query.get("at"), days = query.get("days"), calendar = query.get("calendar_id");
  const known = [...query.keys()].every(key => ["at", "days", "calendar_id"].includes(key));
  if (!known || !at || Number.isNaN(Date.parse(at)) || !/(Z|[+-]\d{2}:\d{2})$/.test(at) || !days || !/^\d{1,3}$/.test(days) || Number(days) > 366 || (calendar !== null && !uuid.test(calendar))) return fail("请填写带时区的起点和 0–366 个工作日。", 422);
  const forwarded = new URLSearchParams({ at, days, ...(calendar ? { calendar_id: calendar } : {}) });
  return forward(`/v1/work-calendars/working-days?${forwarded}`, "GET");
}

export async function calendarVersions(request: NextRequest, context: { params: Promise<{ calendarId: string }> }) {
  const { calendarId } = await context.params;
  if (!uuid.test(calendarId)) return fail("此入口不可用。", 404, "NOT_FOUND");
  if (request.nextUrl.searchParams.size) return fail("日历版本不接受查询参数。", 422);
  return forward(`/v1/work-calendars/${calendarId}/versions`, "GET");
}

export async function saveCalendar(request: NextRequest, context: { params: Promise<{ calendarId: string }> }) {
  const { calendarId } = await context.params;
  if (!uuid.test(calendarId)) return fail("此入口不可用。", 404, "NOT_FOUND");
  if (!sameOrigin(request)) return fail("请求来源不匹配。", 403, "FORBIDDEN_SCOPE");
  if (request.nextUrl.searchParams.size) return fail("保存日历不接受查询参数。", 422);
  const value = await json(request);
  if (!isRecord(value) || !exactKeys(value, ["expected_revision", ...definitionKeys], ["expected_revision", "working_weekdays", "entries", "reason", "request_key"])
    || !Number.isInteger(value.expected_revision) || (value.expected_revision as number) < 1 || !definition(value)) return fail("请完整填写日历内容。", 422);
  return forward(`/v1/work-calendars/${calendarId}/versions`, "POST", value);
}
