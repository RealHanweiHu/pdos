import type { MyWork, MyWorkCollection } from "./my-work-types";

export type WorkSearchEntry = { [K in MyWorkCollection]: { kind: K; item: NonNullable<MyWork[K]>[number] } }[MyWorkCollection];
export const workKindLabels: Record<MyWorkCollection, string> = { cost_freeze_approvals: "成本冻结待批", tasks: "任务", issues: "问题", risks: "风险", capa_actions: "CAPA 行动", gate_signoffs: "阶段签核", findings: "AI 建议", cross_schedule_approvals: "跨项目确认", id_design_actions: "ID 设计确认／接收", change_execution_confirmations: "变更执行确认", risk_followup_actions: "风险结果提交／接收", task_takeover_actions: "任务交接接收／补齐" };
export function workSearchEntries(work: MyWork): WorkSearchEntry[] {
  return [
    ...(work.cost_freeze_approvals ?? []).map(item => ({ kind: "cost_freeze_approvals" as const, item })),
    ...work.tasks.map(item => ({ kind: "tasks" as const, item })),
    ...work.issues.map(item => ({ kind: "issues" as const, item })),
    ...work.risks.map(item => ({ kind: "risks" as const, item })),
    ...work.capa_actions.map(item => ({ kind: "capa_actions" as const, item })),
    ...work.gate_signoffs.map(item => ({ kind: "gate_signoffs" as const, item })),
    ...work.findings.map(item => ({ kind: "findings" as const, item })),
    ...(work.cross_schedule_approvals ?? []).map(item => ({ kind: "cross_schedule_approvals" as const, item })),
    ...(work.id_design_actions ?? []).map(item => ({ kind: "id_design_actions" as const, item })),
    ...(work.task_takeover_actions ?? []).map(item => ({ kind: "task_takeover_actions" as const, item })),
    ...(work.risk_followup_actions ?? []).map(item => ({ kind: "risk_followup_actions" as const, item })),
    ...(work.change_execution_confirmations ?? []).map(item => ({ kind: "change_execution_confirmations" as const, item })),
  ];
}
export function searchEntryKey(entry: WorkSearchEntry) {
  return `search-work-${entry.kind}-${entry.item.project.id}-${entry.item.id}${entry.kind === "id_design_actions" ? `-${entry.item.kind}` : ""}`;
}
export function searchEntryTitle(entry: WorkSearchEntry) {
  return entry.kind === "capa_actions" ? entry.item.description : entry.kind === "gate_signoffs" ? `${entry.item.gate_name} · 第${entry.item.round_number}轮` : entry.item.title;
}
export function searchEntryDate(entry: WorkSearchEntry) {
  if (entry.kind === "tasks" || entry.kind === "capa_actions" || entry.kind === "task_takeover_actions") return entry.item.due_date;
  if (entry.kind === "issues" || entry.kind === "risks") return entry.item.target_date;
  return entry.kind === "gate_signoffs" ? entry.item.review_due_at : null;
}
