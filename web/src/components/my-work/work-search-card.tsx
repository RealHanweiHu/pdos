"use client";

import { CostFreezes } from "@/components/projects/cost-freezes";
import { ConversationFinding } from "@/components/ai/conversation-finding";
import { RiskFollowupResults } from "@/components/projects/risk-followup-results";
import { ChangeExecutionResults } from "@/components/projects/change-execution-results";
import { ProjectCrossDependencies } from "@/components/projects/project-cross-dependencies";
import { CapaWorkCard } from "./capa-work-card";
import { GateSignoffWorkCard } from "./gate-signoff-work-card";
import { IssueRiskWorkCard } from "./issue-risk-work-card";
import { MyWorkIdDesignAction } from "./my-work-id-design";
import type { MyWorkIdDesign } from "./my-work-types";
import { TaskTakeover } from "./task-takeover";
import { TaskPreparation } from "./task-preparation";
import { WorkCardConversation } from "./work-card-conversation";

import type { WorkSearchEntry } from "./work-search-entries";

export function WorkSearchCard({ entry, handoffs, onChanged, onNotice }: { entry: WorkSearchEntry; handoffs: MyWorkIdDesign[]; onChanged: () => Promise<void>; onNotice: (notice: string) => void }) {
  switch (entry.kind) {
    case "tasks": return <><TaskPreparation inlineActions projectId={entry.item.project.id} taskId={entry.item.id} handoffActions={handoffs} onChanged={() => void onChanged()} onAction={onNotice}/><WorkCardConversation projectId={entry.item.project.id} kind="task" id={entry.item.id}/></>;
    case "issues":
    case "risks": return <><IssueRiskWorkCard projectId={entry.item.project.id} itemId={entry.item.id} kind={entry.kind} onChanged={onChanged} onNotice={onNotice}/><WorkCardConversation projectId={entry.item.project.id} kind={entry.kind === "issues" ? "issue" : "risk"} id={entry.item.id}/></>;
    case "capa_actions": return <><CapaWorkCard item={entry.item} onChanged={onChanged} onNotice={onNotice}/><WorkCardConversation projectId={entry.item.project.id} kind="capa" id={entry.item.id}/></>;
    case "gate_signoffs": return <><GateSignoffWorkCard item={entry.item} onChanged={onChanged} onNotice={onNotice}/><WorkCardConversation projectId={entry.item.project.id} kind="gate" id={entry.item.gate_id}/></>;
    case "findings": return <ConversationFinding findingId={entry.item.id} onRecorded={() => void onChanged()}/>;
    case "id_design_actions": return <MyWorkIdDesignAction item={entry.item} onChanged={() => void onChanged()}/>;
    case "cross_schedule_approvals": return <ProjectCrossDependencies projectId={entry.item.project.id} focusProposalId={entry.item.id} onChanged={() => void onChanged()}/>;
    case "cost_freeze_approvals": return <CostFreezes canEdit calculation={null} initialRequestId={entry.item.id} projectId={entry.item.project.id} onChanged={() => void onChanged()}/>;
    case "task_takeover_actions": return <TaskTakeover initiallyOpen projectId={entry.item.project.id} taskId={entry.item.task_id} onChanged={() => void onChanged()}/>;
    case "risk_followup_actions": return <><p className="text-xs text-muted-foreground">{entry.item.mode === "review" ? "待本人接收" : "待提交或补齐结果"}</p><RiskFollowupResults projectId={entry.item.project.id} riskId={entry.item.risk_id} taskId={entry.item.task_id} onRecorded={() => void onChanged()}/></>;
    case "change_execution_confirmations": return <ChangeExecutionResults projectId={entry.item.project.id} bindingId={entry.item.binding_id} initiallyOpen focusResultId={entry.item.id} onChanged={onChanged}/>;
  }
}
