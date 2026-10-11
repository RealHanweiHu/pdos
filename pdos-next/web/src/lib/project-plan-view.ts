import type { DefinitionRevision } from "@/lib/product-view";

export type ProjectApi = <T>(path: string, body?: unknown) => Promise<T>;
export type SourceRead = { artifact_id: string; expected_revision: number };
export type Discipline = "engineering" | "npi";
export type CalendarInput = {
  key: string; version: string; timezone: string; working_weekdays: number[];
  intervals: { start_minute: number; end_minute: number }[]; holidays: string[];
  timezone_rules_sha256?: string | null;
};
export type PlanTaskInput = {
  key: string; title: string; discipline: Discipline; depends_on: string[];
  duration_min_minutes: number | null; duration_max_minutes: number | null; estimate_source: string | null;
};
export type ScheduleInput = { start: string; calendar: CalendarInput; tasks: PlanTaskInput[] };
export type CalendarRef = { key: string; version: string; timezone: string; timezone_rules_sha256?: string | null };
export type TaskForecast = PlanTaskInput & {
  earliest_start: string | null; earliest_finish: string | null; latest_start: string | null; latest_finish: string | null;
  calendar_ref: CalendarRef; unknown_reasons: string[]; blocked_by: string[];
};
export type PlanForecast = {
  algorithm_version: string; input_start: string; calendar_ref: CalendarRef; tasks: TaskForecast[];
  earliest_finish: string | null; latest_finish: string | null; warnings: string[];
};
export type PlanProposal = { id: string; revision: number; reason: string; input_snapshot: ScheduleInput; forecast: PlanForecast; project_revision: number };
export type Project = {
  id: string; name: string; purpose: string; scope: string; owner_id: string; visibility: "private" | "category" | "audience";
  revision: number; status: string; source_status: string; created_at: string;
  definition: { id: string; title: string; revision: number; status: string; source_status: string };
  required_source_read_set: SourceRead[]; proposals: PlanProposal[];
  plan: { id: string; revision: number; status: string; forecast: PlanForecast } | null;
  timeline: { baseline: null; forecast: PlanForecast | null; commitment: null; actual: null };
  work_packages: { id: string; discipline: Discipline }[];
  tasks: { id: string; key: string; work_package_id: string; forecast: TaskForecast }[];
};
export type ProjectList = { items: Project[]; has_more: boolean; unavailable_count: number };
export type CreateProjectPayload = {
  name: string; purpose: string; scope: string; definition_id: string; expected_definition_revision: number;
  visibility: "private" | "category" | "audience"; confirmation_token?: string | null;
};
export type ProposePlanPayload = { project_id: string; expected_project_revision: number; schedule: ScheduleInput; reason: string };
export type ApplyPlanPayload = { project_id: string; proposal_id: string; expected_project_revision: number; confirmation_token?: string | null };
export type ProjectCommand = {
  command_id: string; idempotency_key: string; operation: "project.create" | "work.plan.propose" | "work.plan.apply";
  product_id: string; expected_revision: number; source_read_set: SourceRead[];
  payload: CreateProjectPayload | ProposePlanPayload | ApplyPlanPayload;
};
export type ProjectReview = {
  operation: ProjectCommand["operation"]; name: string; effect: string; purpose?: string; scope?: string;
  visibility?: "private" | "category" | "audience"; definition?: { id: string; title: string; revision: number; status: string };
  project_id?: string; project_revision?: number; proposal_id?: string; proposal_revision?: number;
  forecast?: PlanForecast; input_snapshot?: ScheduleInput; reason?: string;
};
export type PreparedProject = { command: ProjectCommand; review: ProjectReview; expires_at: string; confirmation_token: string };
export type TaskDraft = { key: string; title: string; discipline: Discipline; depends_on: string[]; minimum: string; maximum: string; basis: string };
export type ProjectDraft = {
  name: string; purpose: string; scope: string; definitionId: string; visibility: "private" | "category" | "audience";
  projectId: string; startUtc: string; timezone: string; calendarVersion: string; weekdays: number[];
  intervals: string; holidays: string; tasks: TaskDraft[]; reason: string;
};
export type WaitingProject = { stage: "preview" | "execute"; command: ProjectCommand };
export type LocalProjectDraft = { draft: ProjectDraft; pending: WaitingProject | null };

export const disciplineNames: Record<Discipline, string> = { engineering: "工程", npi: "NPI / 制造导入" };
export const weekdayNames = ["一", "二", "三", "四", "五", "六", "日"];
export const forecastReasonNames: Record<string, string> = {
  DURATION_MIN_UNKNOWN: "最低工时未知", DURATION_MAX_UNKNOWN: "最高工时未知",
  DEPENDENCY_MIN_UNKNOWN: "前置任务的最早完成时间未知", DEPENDENCY_MAX_UNKNOWN: "前置任务的最晚完成时间未知",
};
export const forecastWarningNames: Record<string, string> = {
  START_ROUNDED_UP_TO_MINUTE: "起点已向上取整至下一分钟", ESTIMATE_SOURCE_UNSPECIFIED: "部分工时尚未记录估计依据",
};
export function blankProjectDraft(purpose: string): ProjectDraft {
  return { name: "", purpose, scope: "", definitionId: "", visibility: "private", projectId: "", startUtc: "",
    timezone: "UTC", calendarVersion: "manual-v1", weekdays: [0, 1, 2, 3, 4],
    intervals: "09:00-12:00\n13:00-17:00", holidays: "",
    tasks: [{ key: "task-1", title: "", discipline: "engineering", depends_on: [], minimum: "", maximum: "", basis: "" }], reason: "" };
}
export function definitionReadSet(definition: DefinitionRevision): SourceRead[] {
  return [...new Map(definition.sources.map(ref => [ref.artifact_id, { artifact_id: ref.artifact_id, expected_revision: ref.expected_revision }])).values()];
}
function stringFields(item: Record<string, unknown>, fields: string[]) { return fields.every(key => typeof item[key] === "string"); }
function isRecord(value: unknown): value is Record<string, unknown> { return !!value && typeof value === "object" && !Array.isArray(value); }
export function restoreProjectDraft(value: unknown, productId: string): LocalProjectDraft | null {
  if (!isRecord(value) || !isRecord(value.draft)) return null;
  const draft = value.draft;
  if (!stringFields(draft, ["name", "purpose", "scope", "definitionId", "projectId", "startUtc", "timezone", "calendarVersion", "intervals", "holidays", "reason"]) || !["private", "category", "audience"].includes(String(draft.visibility))) return null;
  if (!Array.isArray(draft.weekdays) || !draft.weekdays.every(day => Number.isInteger(day) && Number(day) >= 0 && Number(day) <= 6)) return null;
  if (!Array.isArray(draft.tasks) || draft.tasks.length > 500 || !draft.tasks.every(task => isRecord(task) && stringFields(task, ["key", "title", "minimum", "maximum", "basis"]) && ["engineering", "npi"].includes(String(task.discipline)) && Array.isArray(task.depends_on) && task.depends_on.every(key => typeof key === "string"))) return null;
  if (value.pending != null) {
    const pending = value.pending;
    if (!isRecord(pending) || !["preview", "execute"].includes(String(pending.stage)) || !isRecord(pending.command)) return null;
    const command = pending.command;
    if (!stringFields(command, ["command_id", "idempotency_key"]) || command.product_id !== productId || !["project.create", "work.plan.propose", "work.plan.apply"].includes(String(command.operation)) || !Number.isInteger(command.expected_revision) || Number(command.expected_revision) < 1 || !isRecord(command.payload)) return null;
    if (pending.stage === "preview" && command.operation === "work.plan.propose") return null;
    if (!Array.isArray(command.source_read_set) || !command.source_read_set.every(read => isRecord(read) && typeof read.artifact_id === "string" && Number.isInteger(read.expected_revision) && Number(read.expected_revision) > 0)) return null;
  }
  return { draft: draft as unknown as ProjectDraft, pending: (value.pending ?? null) as WaitingProject | null };
}
function failure(message: string): never { throw new Error(message); }
function duration(value: string, title: string): number | null {
  if (!value.trim()) return null;
  if (!/^\d+$/.test(value.trim()) || Number(value) > 525600) failure(`${title}工时须为 0–525600 的整数分钟；未知时留空。`);
  return Number(value);
}
function localMinute(value: string, end: boolean): number {
  const match = /^(\d{2}):(\d{2})$/.exec(value);
  if (!match) failure("每日工作时段请按 09:00-12:00 填写，每行一个。");
  const result = Number(match[1]) * 60 + Number(match[2]);
  if (Number(match[2]) > 59 || Number(match[1]) > 24 || result > 1440 || (!end && result === 1440) || (Number(match[1]) === 24 && Number(match[2]) !== 0)) failure("工作时段中的时刻无效；跨午夜时段请拆成两段。");
  return result;
}
export function buildSchedule(draft: ProjectDraft): ScheduleInput {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(draft.startUtc)) failure("请填写明确的 UTC 计划起点。");
  const start = `${draft.startUtc}:00.000Z`;
  const point = new Date(start);
  if (!Number.isFinite(point.getTime()) || point.toISOString() !== start) failure("UTC 计划起点不是有效日期或时刻。");
  if (!draft.timezone.trim() || draft.timezone.length > 100) failure("请填写有效的 IANA 工作日历时区。");
  try { new Intl.DateTimeFormat("en", { timeZone: draft.timezone.trim() }).format(point); } catch { failure("工作日历时区无效，例如 Asia/Shanghai 或 UTC。"); }
  if (!draft.calendarVersion.trim() || draft.calendarVersion.length > 80) failure("请填写不超过 80 字的工作日历版本。");
  if (!draft.weekdays.length || new Set(draft.weekdays).size !== draft.weekdays.length) failure("请选择至少一个工作日，且不能重复。");
  const intervalLines = draft.intervals.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  if (!intervalLines.length || intervalLines.length > 12) failure("请填写 1–12 个每日工作时段。");
  const intervals = intervalLines.map(line => {
    const match = /^(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})$/.exec(line);
    if (!match) failure("每日工作时段请按 09:00-12:00 填写，每行一个。");
    const start_minute = localMinute(match[1], false), end_minute = localMinute(match[2], true);
    if (end_minute <= start_minute) failure("工作时段结束须晚于开始；跨午夜时段请拆成两段。");
    return { start_minute, end_minute };
  }).sort((a, b) => a.start_minute - b.start_minute);
  if (intervals.some((item, index) => index > 0 && intervals[index - 1].end_minute > item.start_minute)) failure("每日工作时段不能重叠。");
  const holidays = draft.holidays.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  if (holidays.length > 3660 || new Set(holidays).size !== holidays.length || holidays.some(day => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return true;
    const instant = new Date(`${day}T00:00:00.000Z`);
    return !Number.isFinite(instant.getTime()) || instant.toISOString().slice(0, 10) !== day;
  })) failure("休息日期须为有效且不重复的 YYYY-MM-DD，每行一项。");
  if (!draft.tasks.length || draft.tasks.length > 500) failure("请填写 1–500 个真实任务。");
  const tasks = draft.tasks.map(task => {
    if (!/^[a-zA-Z0-9_-]{1,80}$/.test(task.key) || !task.title.trim() || task.title.length > 200) failure("每个任务都需要有效标识及不超过 200 字的标题。");
    const minimum = duration(task.minimum, task.title), maximum = duration(task.maximum, task.title);
    if (minimum !== null && maximum !== null && minimum > maximum) failure(`${task.title}的最低工时不能大于最高工时。`);
    if ((minimum !== null || maximum !== null) && !task.basis.trim()) failure(`${task.title}已有工时估计，请填写估计依据。`);
    if (task.basis.length > 2000) failure(`${task.title}的估计依据不能超过 2000 字。`);
    if (task.depends_on.length > 100 || new Set(task.depends_on).size !== task.depends_on.length) failure(`${task.title}的前置任务重复或超过 100 项。`);
    return { key: task.key, title: task.title.trim(), discipline: task.discipline, depends_on: [...task.depends_on], duration_min_minutes: minimum, duration_max_minutes: maximum, estimate_source: task.basis.trim() || null };
  });
  const keys = new Set(tasks.map(task => task.key));
  if (keys.size !== tasks.length) failure("任务标识不能重复。");
  if (tasks.some(task => task.depends_on.some(key => !keys.has(key)))) failure("前置任务已不存在，请先核对依赖。");
  const unresolved = new Set(keys);
  while (unresolved.size) {
    const next = tasks.filter(task => unresolved.has(task.key) && task.depends_on.every(key => !unresolved.has(key)));
    if (!next.length) failure("任务依赖存在循环，请先解除循环。");
    next.forEach(task => unresolved.delete(task.key));
  }
  return { start, calendar: { key: "manual", version: draft.calendarVersion.trim(), timezone: draft.timezone.trim(), working_weekdays: [...draft.weekdays].sort(), intervals, holidays }, tasks };
}
export function utcText(value: string | null): string {
  if (value === null) return "未知 / 暂不可预测";
  const instant = new Date(value);
  if (!Number.isFinite(instant.getTime())) return "时间需要重核";
  return `${instant.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}
export function durationText(minimum: number | null, maximum: number | null): string {
  return `${minimum === null ? "未知" : minimum} ～ ${maximum === null ? "未知" : maximum} 分钟`;
}
