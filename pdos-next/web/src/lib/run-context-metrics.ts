import type { ProcessStep } from "./run-process";

export type ContextWarning = "fixed_over_half_focus" | "context_incomplete" | "cleanup_more_than_twice" | "persistent_estimation_error";
type Counts = Record<string, number | null>;
export type ContextMetrics = {
  version: 1; window: number | null; window_configured: boolean | null; reserve: number | null; focus: number | null;
  fixed_over_half?: boolean | null;
  estimated_input_tokens: number | null; admission_tokens: number | null; actual_input_tokens: number | null; actual_output_tokens: number | null;
  segments: Record<string, { estimated_tokens: number | null; actual_tokens: number | null } | null> | null;
  estimation_error_ratio: number | null; estimation_error_streak: number | null; calibration_factor: number | null;
  estimation_basis: "previous_actual_input" | "first_call_estimate" | null;
  cache: { read_tokens: number | null; creation_tokens: number | null; read_hit_ratio: number | null; reporting: "positive_usage_reported" | "zero_or_unreported" | null; status: "not_recorded_for_failed_call" | null; input_includes_cache: boolean | null } | null;
  cleanup: { triggered: boolean | null; applied: boolean | null; minimum_tokens: number | null; before_tokens: number | null; after_tokens: number | null; saved_tokens: number | null; candidate_saved_tokens: number | null; eligible_results: number | null; protected_results: number | null; retained_latest_results: number | null; replaced_results: number | null; cache_invalidation_from_message: number | null; reason: string | null } | null;
  cleanup_count: number | null; history: Counts | null;
  work_state: { revision: number | null; context_incomplete: boolean | null; item_counts: Counts | null } | null;
  run_budget: { limit: number | null; used: number | null; held: number | null; remaining: number | null } | null;
  context_incomplete: boolean; call_state: "completed" | "failed" | "unknown" | null; usage_status: "recorded" | "unavailable" | null;
  isolation: string | null; warnings: ContextWarning[];
  reductions_count: number | null; reductions: { kind: string | null; field: string | null; recoverable: boolean }[];
  missing_count: number | null; missing: { field: string | null; estimated_tokens: number | null }[];
};
export const metricSegments = [["system", "系统"], ["tools", "工具与输出结构"], ["skills", "已载入方法"], ["envelope", "当前上下文"], ["history", "历史"], ["loop", "运行内消息"]] as const;
export const warningLabels: Record<ContextWarning, string> = {
  fixed_over_half_focus: "固定段估算已超过聚焦上限 F 的 50%。",
  context_incomplete: "必需上下文装不下，本次模型调用已停止。",
  cleanup_more_than_twice: "本运行已清理超过 2 次，清理点之后的缓存可能失效。",
  persistent_estimation_error: "同一路线连续至少两次输入估算偏差超过 10%。",
};
const cleanupReasons: Record<string, string> = {
  within_focus: "未超过聚焦上限，无需清理", no_eligible_results: "没有可安全清理的较早结果",
  no_controlled_compactor: "没有可受控恢复的清理方式", minimum_reached: "已达到至少 20%F 的清理量",
  insufficient_eligible_tokens: "可清理内容不足 20%F，保留原结果", legacy_call: "旧调用未记录清理详情",
};
const reductions: Record<string, string> = { history_directory: "较早历史改为目录", history_answer_preview: "历史回答改为预览", older_tool_result: "较早工具结果改为受控引用", object_detail_directory: "当前对象正文改为目录" };
const workFields: Record<string, string> = { constraints: "约束", exclusions: "排除条件", focus_objects: "焦点对象", completed: "已办动作", candidates: "候选", unfinished: "待办", questions: "待答问题", citations: "待核对引用" };
export const metricWorkFields = Object.entries(workFields);
export function metricNumber(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(value) : "未知";
}
export function metricPercent(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? `${new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 1 }).format(value * 100)}%` : "未知";
}
export function metricCacheTokens(value: number | null | undefined): string {
  // Existing normalized ProviderUsage defaults unreported fields to zero. Zero
  // therefore does not prove a measured cache miss or measured creation count.
  return typeof value === "number" && value > 0 ? metricNumber(value) : "未知";
}
export function cleanupReason(reason: string | null | undefined): string { return reason ? cleanupReasons[reason] ?? "原因未记录" : "原因未记录"; }
export function reductionLabel(kind: string | null): string { return kind ? reductions[kind] ?? "已记录的省略动作" : "已记录的省略动作"; }
export function metricField(field: string | null): string {
  if (!field) return "字段未知";
  const key = field.split(".").at(-1) ?? "";
  return workFields[key] ?? ({ current_question: "当前问题", system: "系统提示", tool_definitions: "工具定义", output_schema: "输出结构", sources: "绑定来源" } as Record<string, string>)[key] ?? (/^(?:system|tool_definitions|output_schema|current_question|sources|(?:work_state|context|conversation|proposal)\.[A-Za-z0-9_.\[\]/-]{1,180}|(?:messages|skill_body|human_or_verification_message)\[\d+\])$/.test(field) ? field : "字段未知");
}
export function contextMetricSteps(steps: ProcessStep[]): (ProcessStep & { context_metrics: ContextMetrics })[] {
  return steps.filter((step): step is ProcessStep & { context_metrics: ContextMetrics } =>
    ["context_observed", "context_admission_observed"].includes(step.kind) && !!step.context_metrics && step.context_metrics.version === 1);
}
export function contextCarrySummary(value: ContextMetrics): string {
  return `携带历史 ${metricNumber(value.history?.carried)} 轮 · 工作状态第 ${metricNumber(value.work_state?.revision)} 版 · 本次新增省略 ${metricNumber(value.reductions_count)} 项`;
}

export function metricIsolation(value: string | null): string {
  return ({ main: "主调用", research: "只读研究", extract: "原件提取", mcp: "外部只读", assistant_extract: "证据抽取", assistant_compare: "资料比较" } as Record<string, string>)[value ?? ""] ?? "调用范围未知";
}
