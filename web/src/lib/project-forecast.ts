// D47 forecast refresh (P82 D181, P58, P66): a system recompute that never changes
// the plan, the baseline or any commitment. Pure helpers, no transport.

export type Window = { earliest: string | null; latest: string | null };
export type ForecastTask = {
  key: string; task_id: string; origin: "estimate" | "actual_and_remaining" | "actual_anchor"; status: "exact" | "range" | "unknown" | "conflicted";
  start: Window; finish: Window; float_minutes: number | null; working_float_minutes: number | null; critical: boolean | null;
  issues: string[]; depends_on: string[]; planned_finish: string | null; planned_latest_finish: string | null; shift_minutes: number | null;
};
export type ForecastCommitment = { commitment_id: string; key: string | null; promised_at: string | null; forecast_finish: string | null; impact: "later" | "within" | "unknown"; fulfilled: boolean };
export type ForecastResult = {
  status: "complete" | "partial" | "invalid"; float_status: "calculated" | "not_calculated"; critical_path: string[];
  project_finish: Window; planned_finish: string | null; as_of: string; as_of_day: string;
  calendar: { key: string; version: string; timezone: string; label: string | null };
  tasks: ForecastTask[]; commitments: ForecastCommitment[]; issues: string[]; effect: string; plan: { id: string; revision: number };
};
export type ForecastRecord = { id: string; revision: number; plan_id: string; plan_revision: number; status: string; input_sha256: string; created_at: string; kind: "system_recompute"; result: ForecastResult };
export type ForecastView = {
  project: { id: string; revision: number }; current: ForecastRecord | null; unavailable: string | null;
  inputs: { plan: { id: string; revision: number }; input_sha256: string; as_of_day: string; changed: boolean; facts: Record<string, { start: string | null; finish: string | null }> } | null;
  history: { id: string; revision: number; status: string; created_at: string; project_finish: Window | null; kind: "system_recompute" }[];
};
export type RefreshCommand = { command_id: string; idempotency_key: string; product_id: string; expected_revision: number; operation: "work.forecast.refresh"; source_read_set: []; payload: { project_id: string; plan: { id: string; revision: number }; expected_input_sha256: string } };

export const originNames: Record<ForecastTask["origin"], string> = { estimate: "按估时", actual_and_remaining: "已开始", actual_anchor: "已完成（实际）" };
export const impactNames: Record<ForecastCommitment["impact"], string> = { later: "预测晚于承诺", within: "在承诺内", unknown: "无法比较" };
export const issueNames: Record<string, string> = {
  remaining_estimate_required: "已开始，缺剩余工期估计",
  work_duration_unknown: "工期上限未知",
  dependency_uncertain: "前置为区间或未知",
  actual_start_unknown: "实际开始未知",
  actual_after_as_of: "实际时间晚于预测时点",
};

export function refreshCommand(view: ForecastView, product: { id: string; revision: number }): RefreshCommand {
  if (!view.inputs) throw new Error("项目还没有应用的计划，无法重算预测。");
  return { command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), product_id: product.id, expected_revision: product.revision, operation: "work.forecast.refresh", source_read_set: [], payload: { project_id: view.project.id, plan: { ...view.inputs.plan }, expected_input_sha256: view.inputs.input_sha256 } };
}

export function windowText(value: Window, format: (value: string) => string): string {
  if (!value.earliest && !value.latest) return "未知";
  if (value.earliest && value.latest && value.earliest === value.latest) return format(value.earliest);
  return `${value.earliest ? format(value.earliest) : "未知"} — ${value.latest ? format(value.latest) : "未知"}`;
}

export function shiftText(minutes: number | null): string {
  if (minutes == null) return "无法比较";
  if (minutes === 0) return "与计划一致";
  const days = Math.abs(minutes) / 1440;
  const amount = days >= 1 ? `${Number(days.toFixed(1))} 天` : `${Math.round(Math.abs(minutes) / 60)} 小时`;
  return minutes > 0 ? `比计划晚 ${amount}` : `比计划早 ${amount}`;
}

export function floatText(task: ForecastTask): string {
  if (task.critical) return "关键路径";
  if (task.working_float_minutes == null) return "未计算";
  return `浮时 ${Number((task.working_float_minutes / 480).toFixed(1))} 个工作日`;
}

export function checkView(value: unknown, projectId: string): asserts value is ForecastView {
  const view = value as ForecastView;
  if (!view || typeof view !== "object" || view.project?.id !== projectId || !Array.isArray(view.history)) throw new Error("预测暂时无法读取，请刷新。");
}
