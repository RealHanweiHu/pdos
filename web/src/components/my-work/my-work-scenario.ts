import type { MyWork, MyWorkCollection, MyWorkCounts } from "./my-work-types";
import { workDate } from "./work-dates";
import { searchEntryDate, workSearchEntries } from "./work-search-entries";

export type MyWorkScenario = "all" | "execution" | "reception" | "coordination" | "ai" | "preproject";

const allCollections: MyWorkCollection[] = [
  "tasks", "issues", "risks", "capa_actions", "gate_signoffs", "findings",
  "cross_schedule_approvals", "id_design_actions", "change_execution_confirmations",
  "risk_followup_actions", "task_takeover_actions", "cost_freeze_approvals",
];

export const myWorkScenarios: { key: MyWorkScenario; label: string; description: string; collections: readonly MyWorkCollection[] }[] = [
  { key: "all", label: "全部办理", description: "查看本人全部项目待办；研究、专业协审与产品定义在立项前工作中另行核对。", collections: allCollections },
  { key: "execution", label: "执行与整改", description: "核对输入和前置，执行任务、处理问题、提交整改与变更结果。", collections: ["tasks", "issues", "capa_actions", "change_execution_confirmations", "risk_followup_actions"] },
  { key: "reception", label: "验证与接收", description: "核对实际证据、交接与当前签核轮次。问题卡包含处理和验证，请按原卡确认本人可办理动作。", collections: ["issues", "gate_signoffs", "id_design_actions", "task_takeover_actions"] },
  { key: "coordination", label: "批准与协调", description: "处理风险、跨项目依赖和成本冻结；正式批准仍按对象权限与当前依据办理。", collections: ["risks", "cross_schedule_approvals", "cost_freeze_approvals"] },
  { key: "ai", label: "AI 建议", description: "核对来源与建议差异，审阅和独立应用沿原办理规则。", collections: ["findings"] },
  { key: "preproject", label: "立项前工作", description: "研究、专业工作、实验、策略与定义协审按本人责任另列，不计入项目待办数量。", collections: [] },
];

export function scenarioHasCollection(scenario: MyWorkScenario, collection: MyWorkCollection) {
  return myWorkScenarios.find(item => item.key === scenario)!.collections.includes(collection);
}

export function scenarioCount(scenario: MyWorkScenario, counts: MyWorkCounts): number | null {
  if (scenario === "preproject") return null;
  return myWorkScenarios.find(item => item.key === scenario)!.collections.reduce((sum, key) => sum + (counts[key] ?? 0), 0);
}

export function scenarioForCollection(collection: MyWorkCollection): MyWorkScenario {
  if (["gate_signoffs", "id_design_actions", "task_takeover_actions"].includes(collection)) return "reception";
  if (["risks", "cross_schedule_approvals", "cost_freeze_approvals"].includes(collection)) return "coordination";
  return collection === "findings" ? "ai" : "execution";
}

export function collectionForWorkAnchor(anchor: string): MyWorkCollection | null {
  const prefixes: [string, MyWorkCollection][] = [
    ["work-risk-result-", "risk_followup_actions"], ["work-cost-freeze-", "cost_freeze_approvals"],
    ["work-id-freeze-", "id_design_actions"], ["work-id-handoff-", "id_design_actions"],
    ["work-takeover-", "task_takeover_actions"], ["work-task-", "tasks"],
    ["work-issue-", "issues"], ["work-risk-", "risks"], ["work-capa-", "capa_actions"],
    ["work-gate-", "gate_signoffs"], ["work-finding-", "findings"],
    ["work-cross-", "cross_schedule_approvals"], ["work-change-", "change_execution_confirmations"],
  ];
  return prefixes.find(([prefix]) => anchor.startsWith(prefix))?.[1] ?? null;
}

/** The initial view follows actual loaded urgency, never a guessed profession. */
export function preferredWorkScenario(work: MyWork, today: string): MyWorkScenario {
  const candidates = workSearchEntries(work).map((entry, index) => {
    const date = searchEntryDate(entry);
    const due = date ? workDate(date) : null;
    const taskLike = entry.kind === "tasks" || entry.kind === "task_takeover_actions";
    const blocked = taskLike && entry.item.status === "blocked";
    const high = taskLike ? ["high", "critical"].includes(entry.item.priority)
      : entry.kind === "issues" && ["high", "critical"].includes(entry.item.severity);
    const confirmation = entry.kind === "gate_signoffs" || entry.kind === "id_design_actions" ||
      entry.kind === "cross_schedule_approvals" || entry.kind === "cost_freeze_approvals" ||
      entry.kind === "change_execution_confirmations" || entry.kind === "findings" ||
      entry.kind === "issues" && entry.item.status === "verification" ||
      entry.kind === "task_takeover_actions" && entry.item.mode === "review" ||
      entry.kind === "risk_followup_actions" && entry.item.mode === "review" ||
      entry.kind === "tasks" && entry.item.status === "pending_approval";
    const rank = due && due < today ? 0 : blocked ? 1 : due === today ? 2 : high ? 3 : confirmation ? 4 : 5;
    const scenario = entry.kind === "issues" && entry.item.status === "verification" ? "reception" : scenarioForCollection(entry.kind);
    return { rank, due, index, scenario };
  }).sort((a, b) => a.rank - b.rank || (a.due ?? "9999").localeCompare(b.due ?? "9999") || a.index - b.index);
  if (candidates.length) return candidates[0].scenario;
  return myWorkScenarios.find(item => item.key !== "all" && (scenarioCount(item.key, work.counts) ?? 0) > 0)?.key ?? "all";
}
