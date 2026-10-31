/** Ordinary owner-only summary DTOs. These choices never supply authority. */
export type SummaryGroupId = "action" | "waiting" | "following";
export type SummarySelection = { followed_project_ids: string[]; category_ids: string[]; groups: SummaryGroupId[]; excluded_kinds: string[]; max_items: number; dingtalk_binding_id?: string };
export type SummaryPerson = { id: string; name: string | null };
export type SummaryItem = { id: string; kind: string; group: SummaryGroupId; title: string; object: { kind: string; id: string; version_id: string | null; revision: number | null; category_id: string; product_id: string | null; project_id: string | null }; as_of: string; recorded_at: string; state_as_recorded: string; change: { kind: "initial" | "updated" | "unchanged"; text: string }; relationship: { kind: string; text: string }; next_step: { kind: "recorded" | "navigation" | "unknown"; text: string; responsible: SummaryPerson | null; recorded_by: SummaryPerson | null }; continue_url: string; facts: Record<string, unknown>; possible_impact: "待确认"; health: null; fingerprint: string };
export type PersonalSummary = { version: "personal-summary/v1"; tenant_id: string; principal_id: string; as_of: string; groups: { id: SummaryGroupId; title: string; items: SummaryItem[]; unchanged_items: SummaryItem[]; unchanged_collapsed: true }[]; coverage: { source: string; returned: number; available: number | null; has_more: boolean; unavailable: number }[]; complete: boolean; omitted_current_items: number; model_used: false; missing_since_previous: "not_classified" };
export type SummaryFeedItem = { run_id: string; category_id: string; category_name: string; title: string; status: "completed" | "partial"; created_at: string; as_of: string; reading_token: string };
export type SummaryFeed = { version: "personal-summary-feed/v1"; principal_id: string; as_of: string; items: SummaryFeedItem[]; next_cursor: string | null };
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const id = (v: unknown): v is string => typeof v === "string" && /^[a-f\d]{8}(?:-[a-f\d]{4}){3}-[a-f\d]{12}$/i.test(v);
const text = (v: unknown): v is string => typeof v === "string" && !!v.trim();
const time = (v: unknown): v is string => typeof v === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
const integer = (v: unknown, minimum = 0) => Number.isSafeInteger(v) && Number(v) >= minimum;
const unique = (v: string[]) => new Set(v).size === v.length;
export const summaryGroups: Record<SummaryGroupId, string> = { action: "需要我决定或处理的事", waiting: "我在等待别人完成的事", following: "我关注项目的新变化" };
export const summaryKinds: Record<string, string> = { task: "待承接与待接收任务", own_task: "本人进行中的任务", own_promise: "本人已登记承诺", waiting_promise: "等待他人的具名承诺", promise_review: "承诺履行核对", external_wait: "外部等待", external_wait_transfer: "等待责任转交", external_handoff: "外部移交回执", project_risk: "G0风险跟进", g0_review: "具名提案评审", verification_handoff_return: "交样补缺", verification_result_return: "结果补缺", supply_commitment: "供应承诺", project_update: "项目最新具名状态", quality_issue_opened: "开放问题与新开单", capa_observation_due: "CAPA 观察期到期", upcoming_stage_gate: "临近门禁（已批准基线预计）" };
export function parseSummarySelection(v: unknown): SummarySelection {
  if (!record(v) || !Object.keys(v).every(k => ["followed_project_ids", "category_ids", "groups", "excluded_kinds", "max_items", "dingtalk_binding_id"].includes(k))) throw new Error("摘要选择不能包含身份、岗位或权限字段。");
  const value: Record<string, unknown> = { followed_project_ids: [], category_ids: [], groups: ["action", "waiting", "following"], excluded_kinds: [], max_items: 100, ...v };
  for (const [key, maximum] of [["followed_project_ids", 50], ["category_ids", 32]] as const) if (!Array.isArray(value[key]) || value[key].length > maximum || !value[key].every(id) || !unique(value[key])) throw new Error("关注项目或品类选择无法核对。");
  if (!Array.isArray(value.groups) || value.groups.length > 3 || !value.groups.every(k => Object.hasOwn(summaryGroups, k)) || !unique(value.groups) || !Array.isArray(value.excluded_kinds) || value.excluded_kinds.length > 40 || !value.excluded_kinds.every(k => text(k) && k.length <= 80) || !unique(value.excluded_kinds) || !integer(value.max_items, 1) || Number(value.max_items) > 300) throw new Error("摘要分组、类型或条目上限无效。");
  if (value.dingtalk_binding_id != null && !id(value.dingtalk_binding_id)) throw new Error("请从本人当前绑定选择摘要投递。 ");
  if (value.dingtalk_binding_id == null) delete value.dingtalk_binding_id;
  return structuredClone(value) as SummarySelection;
}
export function summaryHref(item: SummaryItem): string | null {
  const value = item.continue_url;
  if (!value.startsWith("/") || value.startsWith("//")) return null;
  const proposal = `/categories/${item.object.category_id}/proposals/${item.object.id}`;
  if (value === proposal) return value;
  try { const url = new URL(value, "https://pdos.invalid"); if (url.pathname !== "/" || url.origin !== "https://pdos.invalid" || url.hash || url.searchParams.get("area") !== "cockpit" || url.searchParams.get("category") !== item.object.category_id || url.searchParams.get("project") !== item.object.project_id || [...url.searchParams.keys()].length !== 3) return null; return value; } catch { return null; }
}
function person(v: unknown): boolean { return v === null || record(v) && id(v.id) && (v.name === null || text(v.name)); }
function item(v: unknown, group: string): v is SummaryItem {
  if (!record(v) || !text(v.id) || !text(v.kind) || v.group !== group || !text(v.title) || !record(v.object) || !id(v.object.id) || !id(v.object.category_id) || !["version_id", "product_id", "project_id"].every(k => v.object && record(v.object) && (v.object[k] === null || id(v.object[k]))) || !(v.object.revision === null || integer(v.object.revision, 1)) || !time(v.as_of) || !time(v.recorded_at) || !text(v.state_as_recorded) || !record(v.change) || !["initial", "updated", "unchanged"].includes(String(v.change.kind)) || !text(v.change.text) || !record(v.relationship) || !text(v.relationship.kind) || !text(v.relationship.text) || !record(v.next_step) || !["recorded", "navigation", "unknown"].includes(String(v.next_step.kind)) || !text(v.next_step.text) || !person(v.next_step.responsible) || !person(v.next_step.recorded_by) || !text(v.continue_url) || !record(v.facts) || v.possible_impact !== "待确认" || v.health !== null || typeof v.fingerprint !== "string" || !/^[a-f\d]{64}$/.test(v.fingerprint)) return false;
  return summaryHref(v as SummaryItem) !== null;
}
export function parsePersonalSummary(v: unknown, principalId?: string): PersonalSummary {
  if (!record(v) || v.version !== "personal-summary/v1" || !id(v.tenant_id) || !id(v.principal_id) || principalId !== undefined && v.principal_id !== principalId || !time(v.as_of) || v.model_used !== false || v.missing_since_previous !== "not_classified" || typeof v.complete !== "boolean" || !integer(v.omitted_current_items) || !Array.isArray(v.groups) || v.groups.length > 3 || !Array.isArray(v.coverage)) throw new Error("摘要范围或生成记录无法核对，原内容未显示。");
  const ids: string[] = [], groupIds: string[] = [];
  for (const g of v.groups) { if (!record(g) || !Object.hasOwn(summaryGroups, String(g.id)) || !text(g.title) || g.unchanged_collapsed !== true || !Array.isArray(g.items) || !Array.isArray(g.unchanged_items) || !g.items.every(row => item(row, String(g.id)) && row.change.kind !== "unchanged") || !g.unchanged_items.every(row => item(row, String(g.id)) && row.change.kind === "unchanged")) throw new Error("摘要条目不完整，不能按空结果展示。"); groupIds.push(String(g.id)); ids.push(...[...g.items, ...g.unchanged_items].map(row => row.id)); }
  if (!unique(groupIds) || !unique(ids) || ids.length > 300 || !v.coverage.every(c => record(c) && text(c.source) && integer(c.returned) && (c.available === null || integer(c.available)) && typeof c.has_more === "boolean" && integer(c.unavailable))) throw new Error("摘要覆盖或来源记录不完整。");
  return v as PersonalSummary;
}
export function summaryFromRun(v: unknown, principalId: string, runId: string): PersonalSummary {
  if (!record(v) || v.run_id !== runId || !record(v.result) || !record(v.result.result)) throw new Error("本次摘要原运行尚未取得。");
  return parsePersonalSummary(v.result.result.personal_summary, principalId);
}
export function parseSummaryFeed(v: unknown, principalId: string): SummaryFeed {
  if (!record(v) || v.version !== "personal-summary-feed/v1" || v.principal_id !== principalId || !time(v.as_of) || !(v.next_cursor === null || id(v.next_cursor)) || !Array.isArray(v.items) || !v.items.every(row => record(row) && id(row.run_id) && id(row.category_id) && text(row.category_name) && text(row.title) && ["completed", "partial"].includes(String(row.status)) && time(row.created_at) && time(row.as_of) && typeof row.reading_token === "string" && new RegExp(`^${row.status}:\\d+$`).test(row.reading_token)) || !unique(v.items.map(row => row.run_id))) throw new Error("本人摘要列表未完整取得。");
  return v as SummaryFeed;
}
const parts = (instant: number, zone: string) => Object.fromEntries(new Intl.DateTimeFormat("en-CA", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" }).formatToParts(instant).filter(p => p.type !== "literal").map(p => [p.type, Number(p.value)]));
function localInstant(day: Date, clock: string, zone: string): number {
  const [hour, minute] = clock.split(":").map(Number), target = Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), hour, minute);
  const offsets = new Set([-36, 0, 36].map(h => { const instant = target + h * 3600000, p = parts(instant, zone); return Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second) - instant; }));
  const candidates = [...offsets].map(offset => target - offset).filter(instant => { const p = parts(instant, zone); return Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute) === target; });
  if (!candidates.length) throw new Error("该本地时间不存在，请选择有效时间。");
  return Math.min(...candidates);
}
export function summarySchedule(calendar: "weekly_monday" | "weekdays", zone: string, clock = "09:00", now = Date.now()) {
  if (!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(clock)) throw new Error("请选择有效的本地摘要时间。");
  const p = parts(now, zone), today = new Date(Date.UTC(p.year, p.month - 1, p.day));
  for (let n = 0; n < 15; n++) { const day = new Date(today.getTime() + n * 86400000), weekday = day.getUTCDay(); if (calendar === "weekly_monday" ? weekday !== 1 : weekday === 0 || weekday === 6) continue; try { const instant = localInstant(day, clock, zone); if (instant > now) return { first_at: new Date(instant).toISOString(), original_timezone: zone, interval_seconds: null, expires_at: null, calendar }; } catch { /* Skip a missing calendar wall slot, matching server semantics. */ } }
  throw new Error("未找到有效的下一摘要时间，请核对时区。");
}

export function summaryLocalClock(instant: string, zone: string) { const p = parts(Date.parse(instant), zone); return `${String(p.hour).padStart(2, "0")}:${String(p.minute).padStart(2, "0")}`; }

export type SummaryTemplate = { id: string; title: string; groups: SummaryGroupId[]; kinds: string[] };
export type SummaryOptions = { version: "personal-summary-options/v1"; principal_id: string; category_id: string; product_id: string | null; default_template: string | null; reason: string; basis: { saved_role: string | null; current_duty_roles: string[]; project_manager: boolean }; templates: SummaryTemplate[] };
export function parseSummaryOptions(v: unknown, principalId: string, categoryId: string, productId: string | null = null): SummaryOptions {
  if (!record(v) || v.version !== "personal-summary-options/v1" || v.principal_id !== principalId || v.category_id !== categoryId || v.product_id !== productId || !text(v.reason) || !record(v.basis) || !(v.basis.saved_role === null || ["product", "engineering", "quality", "manufacturing", "supply", "management", "other"].includes(String(v.basis.saved_role))) || !Array.isArray(v.basis.current_duty_roles) || !v.basis.current_duty_roles.every(r => ["engineering", "quality", "manufacturing", "knowledge"].includes(String(r))) || typeof v.basis.project_manager !== "boolean" || !Array.isArray(v.templates) || v.templates.length !== 5 || !v.templates.every(t => record(t) && ["general", "management", "product", "quality", "supply"].includes(String(t.id)) && text(t.title) && Array.isArray(t.groups) && t.groups.length > 0 && t.groups.length <= 3 && t.groups.every(g => Object.hasOwn(summaryGroups, g)) && unique(t.groups) && Array.isArray(t.kinds) && t.kinds.every(k => Object.hasOwn(summaryKinds, k)) && unique(t.kinds)) || !unique(v.templates.map(t => t.id)) || !(v.default_template === null || v.templates.some(t => t.id === v.default_template))) throw new Error("本人摘要岗位建议或范围无法核对，请重新读取。");
  return structuredClone(v) as SummaryOptions;
}
export function applySummaryTemplate(choice: SummarySelection, template: SummaryTemplate): SummarySelection {
  return parseSummarySelection({ ...choice, groups: [...template.groups], excluded_kinds: Object.keys(summaryKinds).filter(k => !template.kinds.includes(k)) });
}
export function selectedSummaryTemplate(choice: SummarySelection, templates: SummaryTemplate[]): string {
  return templates.find(t => t.groups.length === choice.groups.length && t.groups.every(g => choice.groups.includes(g)) && Object.keys(summaryKinds).every(k => choice.excluded_kinds.includes(k) === !t.kinds.includes(k)))?.id ?? "custom";
}
