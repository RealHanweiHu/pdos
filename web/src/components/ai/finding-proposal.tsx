"use client";
import { CostReductionProposalView, costReductionReady, CostReductionApplied } from "./cost-reduction-proposal";
import type { AiFinding } from "./ai-types";
import { cn } from "@/lib/utils";
import { SupplierRecoveryProposalView, supplierRecoveryReady, SupplierRecoveryAppliedTasks } from "./supplier-recovery-proposal";
import { QualityWorkPackageProposalView, qualityPackageReady } from "./quality-work-package-proposal";
import { ChangeWorkPackageProposalView, changePackageReady } from "./change-work-package-proposal";
import { TestPlanProposalView, testPlanProposalReady } from "./test-plan-proposal";
import { MeetingMinutesProposalView, minutesProposalReady } from "./meeting-minutes-proposal";
import { MeetingActionProposalView, actionProposalReady } from "./meeting-action-proposal";
import { MeetingDecisionProposalView, decisionProposalReady } from "./meeting-decision-proposal";
import { MeetingBusinessProposalView, businessProposalReady, meetingBusinessTypes } from "./meeting-business-proposal";

export const fieldLabels: Record<string, string> = {
  title: "标题",
  description: "描述",
  likelihood: "发生概率",
  impact: "影响程度",
  mitigation_plan: "缓解计划",
  contingency_plan: "应急计划",
  target_date: "目标日期",
  draft_text: "知识草稿",
  applicability: "适用范围",
};

export function proposalReady(finding: AiFinding, payload: Record<string, unknown>): boolean {
  if (finding.finding_type === "cost_reduction") return costReductionReady(payload);
  if (finding.finding_type === "supplier_recovery") return supplierRecoveryReady(payload);
  if (finding.finding_type === "capa_work_package") return qualityPackageReady(payload);
  if (finding.finding_type === "change_work_package") return changePackageReady(payload);
  if (finding.finding_type === "meeting_minutes") return minutesProposalReady(payload);
  if (finding.finding_type === "meeting_action") return actionProposalReady(payload);
  if (finding.finding_type === "meeting_decision") return decisionProposalReady(payload);
  if (meetingBusinessTypes.includes(finding.finding_type)) return businessProposalReady(payload);
  return finding.finding_type !== "test_plan_change" || testPlanProposalReady(payload);
}

export function PayloadEditor({
  finding,
  onChange,
  payload,
}: {
  finding: AiFinding;
  onChange: (payload: Record<string, unknown>) => void;
  payload: Record<string, unknown>;
}) {
  if (finding.finding_type === "cost_reduction") return <CostReductionProposalView projectId={finding.project_id} payload={payload} onChange={onChange} />;
  if (finding.finding_type === "supplier_recovery") return <SupplierRecoveryProposalView projectId={finding.project_id} payload={payload} onChange={onChange} />;
  if (finding.finding_type === "capa_work_package") return <QualityWorkPackageProposalView projectId={finding.project_id} payload={payload} onChange={onChange} />;
  if (finding.finding_type === "change_work_package") return <ChangeWorkPackageProposalView projectId={finding.project_id} payload={payload} onChange={onChange} />;
  if (finding.finding_type === "test_plan_change") return <TestPlanProposalView payload={payload} onChange={onChange} />;
  if (meetingBusinessTypes.includes(finding.finding_type)) return <MeetingBusinessProposalView projectId={finding.project_id} payload={payload} onChange={onChange} />;
  if (finding.finding_type === "meeting_decision") return <MeetingDecisionProposalView draftOwned={Boolean(finding.ai_draft_id)} projectId={finding.project_id} payload={payload} onChange={onChange} />;
  if (finding.finding_type === "meeting_action") return <MeetingActionProposalView draftOwned={Boolean(finding.ai_draft_id)} projectId={finding.project_id} payload={payload} onChange={onChange} />;
  if (finding.finding_type === "meeting_minutes") return <MeetingMinutesProposalView draftOwned={Boolean(finding.ai_draft_id)} projectId={finding.project_id} payload={payload} onChange={onChange} />;
  const fields = finding.finding_type === "knowledge_draft"
    ? ["title", "draft_text", "applicability"]
    : [
        "title",
        "description",
        "likelihood",
        "impact",
        "mitigation_plan",
        "contingency_plan",
        "target_date",
      ];
  return (
    <div className="grid gap-3 border-t bg-muted/20 p-4 sm:grid-cols-2">
      {fields.map((field) => {
        const numeric = field === "likelihood" || field === "impact";
        const multiline = ["description", "mitigation_plan", "contingency_plan", "draft_text", "applicability"].includes(field);
        return (
          <label className={cn("grid gap-1.5 text-xs font-medium", multiline && "sm:col-span-2")} key={field}>
            {fieldLabels[field] ?? field}
            {multiline ? (
              <textarea
                className="min-h-24 rounded-lg border bg-background px-3 py-2 text-sm font-normal"
                onChange={(event) => onChange({ ...payload, [field]: event.target.value || null })}
                value={typeof payload[field] === "string" ? payload[field] : ""}
              />
            ) : (
              <input
                className="h-11 rounded-lg border bg-background px-3 text-sm font-normal"
                max={numeric ? 5 : undefined}
                min={numeric ? 1 : undefined}
                onChange={(event) => onChange({
                  ...payload,
                  [field]: numeric ? Number(event.target.value) : event.target.value || null,
                })}
                required={field === "title" || numeric}
                type={numeric ? "number" : field === "target_date" ? "date" : "text"}
                value={typeof payload[field] === "string" || typeof payload[field] === "number" ? String(payload[field]) : ""}
              />
            )}
          </label>
        );
      })}
    </div>
  );
}

export function FindingProposal({ finding, payload }: { finding: AiFinding; payload: Record<string, unknown> }) {
  if (finding.finding_type === "cost_reduction") return <CostReductionProposalView projectId={finding.project_id} payload={payload}/>;
  if (finding.finding_type === "supplier_recovery") return <SupplierRecoveryProposalView projectId={finding.project_id} payload={payload}/>;
  if (finding.finding_type === "capa_work_package") return <QualityWorkPackageProposalView projectId={finding.project_id} payload={payload}/>;
  if (finding.finding_type === "change_work_package") return <ChangeWorkPackageProposalView projectId={finding.project_id} payload={payload}/>;
  if (finding.finding_type === "test_plan_change") return <TestPlanProposalView payload={payload}/>;
  if (finding.finding_type === "meeting_minutes") return <MeetingMinutesProposalView draftOwned={Boolean(finding.ai_draft_id)} projectId={finding.project_id} payload={payload}/>;
  if (finding.finding_type === "meeting_action") return <MeetingActionProposalView draftOwned={Boolean(finding.ai_draft_id)} projectId={finding.project_id} payload={payload}/>;
  if (finding.finding_type === "meeting_decision") return <MeetingDecisionProposalView draftOwned={Boolean(finding.ai_draft_id)} projectId={finding.project_id} payload={payload}/>;
  if (meetingBusinessTypes.includes(finding.finding_type)) return <MeetingBusinessProposalView projectId={finding.project_id} payload={payload}/>;
  return <dl className="space-y-2 text-sm">{Object.entries(payload).map(([key, value]) => <div key={key}><dt className="font-medium">{fieldLabels[key] ?? key}</dt><dd className="whitespace-pre-wrap break-words">{typeof value === "string" ? value : value == null ? "未填写" : JSON.stringify(value)}</dd></div>)}</dl>;
}

export function FindingDraftDiff({ original, changed }: { original: Record<string, unknown>; changed: Record<string, unknown> }) {
  const keys = [...new Set([...Object.keys(original), ...Object.keys(changed)])].filter(key => JSON.stringify(original[key]) !== JSON.stringify(changed[key]));
  return <details className="rounded-md border p-3 text-sm"><summary className="cursor-pointer">与 AI 原稿的差异 · {keys.length} 项</summary>{keys.map(key => <div key={key} className="mt-2 space-y-1"><p className="font-medium">{fieldLabels[key] ?? key}</p><p className="whitespace-pre-wrap break-words text-muted-foreground">AI 原稿：{JSON.stringify(original[key] ?? null)}</p><p className="whitespace-pre-wrap break-words">人工稿：{JSON.stringify(changed[key] ?? null)}</p></div>)}</details>;
}

export function findingApplyEffect(finding: AiFinding): string {
  switch (finding.finding_type) {
    case "cost_reduction": return "为每项采用建议建立人工核对的降本备选方案，保留原模型引用与费用版本；后续仍走原工程变更批准和实际验证。";
    case "supplier_recovery": return "按人工核对内容为每个采用项建立具名恢复任务。原供应、替代验证、拆借授权与工装记录继续办理；沟通文案保留待人工发送。";
    case "capa_work_package": return "按已接受内容建立具名调查任务或 CAPA 措施，后续由指定负责人执行和提交证据，质量人员独立验证。";
    case "change_work_package": return "将人工核对结论合并为变更范围新版本，后续由原变更负责人继续分析、批准及分派执行。";
    case "test_plan_change": return "创建测试计划新修订，保留旧计划和结果，后续由测试负责人安排执行。";
    case "knowledge_draft": return "创建未验证知识草稿，后续仍须另一位成员核对验证才进入检索。";
    case "meeting_minutes": return "保存正式纪要新版本，保留原版本和来源；决定与行动仍分别办理。";
    case "meeting_action": return "建立上方具名负责人、日期及完成标准对应的实际任务，交负责人执行并回到原会议复查。";
    case "meeting_decision": return "由指定批准人本人记录正式决定，后续执行仍沿原决策跟进。";
    case "meeting_issue": return "建立正式问题，后续由具名负责人和验证人沿原问题流程办理。";
    case "meeting_risk": return "建立正式风险，后续按已接受的责任与缓解措施跟踪。";
    case "meeting_change": return "建立变更申请，后续分析、审批与执行仍沿原变更流程办理。";
    default: return "建立项目风险记录，后续由项目成员分派责任、跟踪缓解和关闭；此候选的应用对象是风险。";
  }
}

export function FindingAppliedReceipt({ finding }: { finding: AiFinding }) {
  if (finding.status !== "applied" || !finding.applied_entity_id) return null;
  const base = `/projects?project=${finding.project_id}`;
  const payload = finding.accepted_payload ?? {};
  const href = finding.applied_entity_type === "memory" ? `/knowledge?project=${finding.project_id}&memory=${finding.applied_entity_id}`
    : finding.applied_entity_type === "cost_reduction" ? `${base}&tab=materials`
    : finding.applied_entity_type === "supplier_recovery" ? `${base}&tab=materials`
    : finding.applied_entity_type === "quality_work_package" ? `${base}&tab=quality&ncr=${String(payload.ncr_id ?? "")}`
    : finding.applied_entity_type === "change_impact_scope" ? `${base}&tab=engineering&ecr=${String(payload.ecr_id ?? "")}`
    : finding.finding_type === "meeting_change" ? `${base}&tab=engineering&ecr=${finding.applied_entity_id}`
    : finding.finding_type === "meeting_minutes" ? `${base}&tab=decisions&meeting=${String(payload.meeting_id ?? "")}`
    : finding.finding_type === "meeting_decision" ? `${base}&tab=decisions`
    : finding.applied_entity_type === "test_plan" ? `${base}&tab=quality`
    : `${base}&tab=work-items&entity_id=${finding.applied_entity_id}`;
  return <div className="space-y-2 rounded-md border p-3 text-sm"><p>已应用：{finding.title}{finding.applied_at ? ` · ${new Date(finding.applied_at).toLocaleString("zh-CN")}` : ""}</p><p>{findingApplyEffect(finding)}</p>{finding.applied_entity_type === "cost_reduction" && <CostReductionApplied projectId={finding.project_id} findingId={finding.id}/>} {finding.applied_entity_type === "supplier_recovery" && <SupplierRecoveryAppliedTasks projectId={finding.project_id} findingId={finding.id}/>}<div className="flex flex-wrap gap-3"><a className="text-primary underline" href={href}>查看实际业务记录与后续办理</a><a className="text-primary underline" href={`/ai-review?finding=${finding.id}`}>查看原建议及裁决</a></div></div>;
}
