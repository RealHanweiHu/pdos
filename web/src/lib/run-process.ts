import type { ContextMetrics } from "./run-context-metrics";

export type ContextIssue = { field: string; reason: string };
export type ProcessStep = { id: string; sequence: number; at: string; kind: string; tool: string | null; skill: string | null; version: string | null; status: string | null; context_fields?: string[]; context_omitted?: ContextIssue[]; context_issues?: ContextIssue[]; context_metrics?: ContextMetrics };
export type RunProcessData = {
  run_id: string; status: string; reverted: boolean; error_code: string | null;
  started_at: string; observed_at: string; last_recorded_at: string | null; ended_at: string | null; elapsed_seconds: number | null;
  call_counts: { total: number; completed: number; pending: number; failed: number };
  source_count: number; business_receipt_count: number;
  sources: { id: string; title: string; bound_revision: number; current_revision: number }[]; next_source_cursor: string | null;
  receipts: { id: string; operation: string; subject_id: string; subject_revision: number }[];
  next_receipt_cursor: string | null; steps: ProcessStep[]; next_before: number | null;
};
const skills: Record<string, string> = { public_research: "公开研究", category_framing: "品类边界", proposal_drafting: "提案起草", rfq_extraction: "客户需求提取", competitor_comparison: "竞品对比", price_band: "价格带分析", review_pain_clustering: "用户痛点归纳", jtbd: "用户任务分析", option_comparison: "方案比较", opportunity_scoring: "机会评估", derivative_diff: "派生差异", gap_check: "缺口核对" };
export function usedSkillName(key: string): string { return skills[key] ?? key; }
export function actionLabel(tool: string | null): string {
  if (!tool) return "已登记处理步骤";
  if (tool === "mcp.tools.list") return "核对已授权的外部工具";
  if (tool === "mcp.read") return "读取已授权的外部资料";
  if (tool.startsWith("research.")) return "搜索、读取并核对公开资料";
  if (tool.startsWith("calc.")) return "按固定口径计算或比较";
  if (tool === "evidence.extract") return "提取所选原件中的事实";
  if (tool.startsWith("category.")) return "核对品类资料";
  if (tool.includes("read") || tool.includes("list") || tool.includes("search")) return "读取当前授权范围内的依据";
  return "准备或办理领域动作";
}
export function processStepLabel(step: ProcessStep): string {
  switch (step.kind) {
    case "accepted": return "工作已保存，等待执行";
    case "skill_loaded": return `加载${skills[step.skill ?? ""] ?? "本次工作方法"}${step.version ? ` · ${step.version}` : ""}`;
    case "context_projected": return step.status === "rejected" ? "所需资料合同不匹配，已保留核对原因" : `已按当前方法核对资料范围${step.context_omitted?.length ? ` · 省略 ${step.context_omitted.length} 个字段` : ""}`;
    case "context_observed": return "已记录本次上下文计量";
    case "context_admission_observed": return "必需上下文未装入，本次模型调用已停止";
    case "model_started": return "整理已取得的信息并选择下一步";
    case "tool_started": return actionLabel(step.tool);
    case "tool_finished": return `本步处理已返回 · ${actionLabel(step.tool)}`;
    case "needs_input": return "等待你的答复或确认";
    case "model_unavailable": return "模型暂不可用，已保留原工作";
    case "reconciliation_required": return "原调用结果待核对，不自动重发";
    case "run_reconciled": return "已核对原运行并保留已提交结果";
    case "run_state":
    case "finished": return ({ completed: "本次处理已形成结果", partial: "已形成部分结果，仍有待完成事项", failed: "执行未完成，请核对已保存记录", cancelled: "已停止后续执行，已做结果保留", waiting_input: "等待答复或运行条件恢复" } as Record<string,string>)[step.status ?? ""] ?? "已记录当前执行状态";
    default: return "已登记处理步骤";
  }
}
export function contextIssueLabel(issue: ContextIssue): string {
  const root = issue.field.split("/")[1];
  const field = ({ goal: "本次目标", sources: "绑定来源", category: "品类资料", product: "型号资料", proposal: "当前提案", conversation: "原工作记忆" } as Record<string,string>)[root] ?? "扩展资料";
  return `${field}：${issue.reason === "outside_skill_context_schema" ? "当前方法未声明使用这一字段，未提供给模型" : issue.reason === "context_required" ? "必要字段尚未提供" : "字段格式与当前方法的资料合同不符"}`;
}
export function processAge(value: RunProcessData, localSeconds = 0): string {
  const terminal = ["completed", "partial", "failed", "cancelled"].includes(value.status);
  if (terminal && value.elapsed_seconds === null) return "结束时刻未记录";
  const seconds = terminal ? value.elapsed_seconds! : Math.max(0, (Date.parse(value.observed_at) - Date.parse(value.started_at)) / 1000 + localSeconds);
  if (!Number.isFinite(seconds)) return "时间记录暂不可核对";
  const total = Math.floor(seconds);
  return total < 60 ? `${total} 秒` : total < 3600 ? `${Math.floor(total / 60)} 分 ${total % 60} 秒` : `${Math.floor(total / 3600)} 小时 ${Math.floor(total % 3600 / 60)} 分`;
}
export function mergeProcessSteps(older: ProcessStep[], current: ProcessStep[]): ProcessStep[] {
  return [...new Map([...older, ...current].map(row => [row.sequence, row])).values()].sort((a,b) => a.sequence-b.sequence);
}

export type ProgressEntry = { id: string; kind: "summary"; text: string } | {
  id: string; kind: "tools"; actions: { id: string; tool: string | null; text: string; state: "started" | "returned" | "loaded" }[];
};
const conversationActions: Record<string, string> = {
  "category.read": "读取品类资料", "category.list": "查看可访问品类",
  "category.parameters.list": "读取规格字典", "category.competitors.list": "读取竞品记录",
  "category.knowledge.list": "读取品类知识", "proposal.read": "读取提案",
  "proposal.items.read": "读取提案条目", "proposal.create": "准备立项提案",
  "proposal.item.patch": "准备提案修订", "evidence.search": "检索已绑定资料",
  "evidence.artifact.read": "读取选定资料", "research.search": "搜索公开资料",
  "research.read": "阅读公开页面", "skill.load": "加载技能",
};

/** Public progress summaries use only persisted action metadata, never model text. */
export function conversationProgress(steps: ProcessStep[]): ProgressEntry[] {
  const entries: ProgressEntry[] = [];
  const pending = new Map<string | null, Extract<ProgressEntry, {kind: "tools"}>["actions"]>();
  let modelSummaryShown = false;
  for (const step of mergeProcessSteps([], steps)) {
    if (step.kind === "model_started") {
      if (modelSummaryShown) continue;
      modelSummaryShown = true;
    }
    if (step.kind === "skill_loaded" || step.kind === "tool_started" || step.kind === "tool_finished") {
      if (step.kind === "tool_finished") {
        const previous = pending.get(step.tool)?.shift();
        if (previous) { previous.state = "returned"; continue; }
      }
      let group = entries.at(-1);
      if (!group || group.kind !== "tools") { group = { id: step.id, kind: "tools", actions: [] }; entries.push(group); }
      const action: Extract<ProgressEntry, {kind: "tools"}>["actions"][number] = {
        id: step.id, tool: step.tool,
        text: step.kind === "skill_loaded" ? usedSkillName(step.skill ?? "本次技能") : conversationActions[step.tool ?? ""] ?? actionLabel(step.tool),
        state: step.kind === "skill_loaded" ? "loaded" : step.kind === "tool_finished" ? "returned" : "started",
      };
      group.actions.push(action);
      if (action.state === "started") pending.set(step.tool, [...(pending.get(step.tool) ?? []), action]);
      continue;
    }
    const text = step.kind === "accepted" ? "收到请求，准备处理。"
      : step.kind === "context_projected" ? step.status === "rejected" ? "当前资料未通过检查，需要补充或调整后继续。" : "已核对本轮可用的上下文与资料范围。"
      : step.kind === "model_started" ? "结合当前资料，整理回复并确定下一步。"
      : step.kind === "needs_input" ? "需要你补充信息或确认，等待继续。"
      : step.kind === "model_unavailable" ? "模型暂不可用，已有记录已保留。"
      : step.kind === "reconciliation_required" ? "上一步的结果尚不确定，先核对已有记录。"
      : step.kind === "run_reconciled" ? "已核对原运行，保留已提交的结果。"
      : ["finished", "run_state"].includes(step.kind) ? ({ completed: "本轮处理已结束，回复如下。", partial: "已整理部分结果，仍有待完成事项。", cancelled: "已停止后续处理，已有结果保留。", failed: "本轮未能完成，已保留执行记录。", waiting_input: "等待补充信息或执行条件恢复。" } as Record<string, string>)[step.status ?? ""] : undefined;
    const previous = entries.at(-1);
    if (text && !(previous?.kind === "summary" && previous.text === text)) entries.push({ id: step.id, kind: "summary", text });
  }
  return entries;
}
