// T0 value metrics and P41 thresholds (D117, D37 ⑧). Every number comes from the
// server's receipt-based computation; the page only formats it.
export type QualityMetrics = {
  runs_window: number; runs_withdrawn: number; writes_window: number; writes_changed: number; writes_withdrawn: number;
  withdrawal_rate: number | null; modification_rate: number | null; retention_rate: number | null; untouched_rate: number | null;
};
export type QualityRule = {
  key: "withdrawal" | "modification" | "framework_check"; label: string; window: number; limit: number; definition: string; gating: boolean;
  state: "within" | "breached" | "insufficient" | "unavailable"; sample: number; count: number; rate: number | null; reason: string | null;
};
export type SpotCheckSample = {
  rule: string;
  weeks: { week_start: string; runs: number; sampled: number; required: number }[];
  runs: { run_id: string; first_at: string; week_start: string; reason: "hash_20_percent" | "weekly_minimum" }[];
};
export type QualityHold = {
  id: string; skill_key: string; skill_version: string; model_version: string;
  reason: "withdrawal" | "modification" | "framework_check" | "critical_spot_check";
  threshold: { window?: number; limit?: number }; metrics: { sample: number; count: number };
  basis_run_ids: string[]; spot_check_id: string | null; owner_name: string | null; created_at: string;
};
export type SpotCheckMark = { id: string; run_id: string; outcome: SpotOutcome; critical_kinds: CriticalKind[]; note: string; reviewed_by_name: string; created_at: string };
export type SpotOutcome = "correct" | "ordinary_error" | "critical_error";
export type CriticalKind = "scope" | "fabrication" | "override" | "red_line" | "commitment_baseline";
// P42's five critical error kinds, in the decision record's own words.
export const criticalKinds: Record<CriticalKind, string> = {
  scope: "越权，或写错项目、品类、受众",
  fabrication: "编造来源、数值或人员职责",
  override: "覆盖人工值，或修改已承接、已提交的任务",
  red_line: "缺少红线成果的计划仍然生效",
  commitment_baseline: "把计划日期写成承诺，或改变基线",
};
export const spotOutcomes: Record<SpotOutcome, string> = { correct: "正确", ordinary_error: "普通错误（计入人工修改率）", critical_error: "关键错误（立即暂停）" };
export type QualityView = {
  skill_key: string;
  holds: QualityHold[];
  definitions: Record<"withdrawal_rate" | "modification_rate" | "retention_rate" | "untouched_rate" | "granularity", string>;
  groups: { skill_version: string; model_version: string; runs_total: number; writes_total: number; first_at: string | null; last_at: string | null; metrics: QualityMetrics | null }[];
  current: null | {
    skill_version: string; model_version: string; since: string; metrics: QualityMetrics | null; rules: QualityRule[];
    breach: string | null; basis: { withdrawal: string[]; modification: string[] }; spot_check: SpotCheckSample; spot_checks: SpotCheckMark[];
  };
  model_judgement: false;
};

export function percent(rate: number | null | undefined) {
  return rate === null || rate === undefined || !Number.isFinite(rate) ? "—" : `${(Math.round(rate * 1000) / 10).toFixed(1)}%`;
}

export const ruleStates: Record<QualityRule["state"], string> = {
  within: "未超过阈值",
  breached: "超过阈值",
  insufficient: "样本不足（N/A）",
  unavailable: "暂无可计算记录",
};

export function ruleSummary(rule: QualityRule) {
  const threshold = `阈值 >${percent(rule.limit)} · 最近 ${rule.window} 次`;
  const value = rule.state === "unavailable" ? "—" : `${rule.count}/${rule.sample}（${percent(rule.rate)}）`;
  const scope = rule.gating ? "触发降回一次确认" : "只作价值指标，不触发降级";
  return `${rule.label}：${value} · ${threshold} · ${ruleStates[rule.state]} · ${scope}`;
}

export const breachLabels: Record<string, string> = {
  withdrawal: "撤回率超过阈值",
  modification: "人工修改率超过阈值",
  framework_check: "框架检查失败率超过阈值",
  critical_spot_check: "抽检发现关键错误",
  unavailable: "指标读取失败，按未通过处理",
};

export function holdSummary(hold: QualityHold) {
  const facts = hold.reason === "critical_spot_check" ? "抽检标注为关键错误" : `${hold.metrics.count}/${hold.metrics.sample}（阈值 >${percent(hold.threshold.limit)} · 最近 ${hold.threshold.window} 次）`;
  const owner = hold.owner_name ? `资格负责人：${hold.owner_name}` : "资格负责人已停用，由当前租户管理员处理";
  return `${breachLabels[hold.reason] ?? hold.reason} · ${facts} · ${owner}`;
}

// Marks still owed on the current sample: sampled runs without a recorded mark.
export function unmarkedSample(sample: SpotCheckSample, marks: SpotCheckMark[]) {
  const marked = new Set(marks.map(mark => mark.run_id));
  return sample.runs.filter(run => !marked.has(run.run_id));
}

export const sampleReasons: Record<SpotCheckSample["runs"][number]["reason"], string> = {
  hash_20_percent: "20% 抽样",
  weekly_minimum: "每周至少 2 次补足",
};

// Weeks whose sample is below min(2, T0 runs that week) would break P42.
export function sampleShortfall(sample: SpotCheckSample) {
  return sample.weeks.filter(week => week.sampled < week.required).map(week => week.week_start);
}
