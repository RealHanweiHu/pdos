"use client";

import { useEffect, useRef } from "react";

import { CrossProposalLanding } from "./cross-proposal-landing";
import { ScheduleResponsibilityLanding } from "./schedule-responsibility-landing";
import { ApprovalRequestLanding } from "./approval-request-landing";
import { ApprovalResponsibilityLanding } from "./approval-responsibility";
import { ProjectExecutionPanel } from "./project-execution-panel";
import { ScheduleExecutionPanel } from "./schedule-execution-panel";
import { ScheduleForecastPanel } from "./schedule-forecast-panel";
import { ScheduleCommitmentPanel } from "./schedule-commitment-panel";
import { ResourceAllocationLanding } from "./resource-allocation-release";
import { ProjectResourceInventory } from "./project-resource-inventory";
import { ReservationResponsibilityLanding } from "@/components/quality/quality-responsibility";
import { ProjectReservationPanel } from "./project-reservation-panel";
import { ProjectTaskWorkspace } from "./project-task-workspace";

export function ProjectPlanPanel({ projectId, userId }: { projectId: string; userId: string }) {
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    const root = panel.current;
    if (!root || !window.location.hash) return;
    let id: string;
    try { id = decodeURIComponent(window.location.hash.slice(1)); } catch { return; }
    const reveal = () => {
      const target = document.getElementById(id);
      if (!target || !root.contains(target)) return false;
      target.scrollIntoView({ block: "start" });
      return true;
    };
    if (reveal()) return;
    const observer = new MutationObserver(() => { if (reveal()) observer.disconnect(); });
    observer.observe(root, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [projectId]);
  return <section ref={panel} aria-label="计划与资源办理" className="space-y-4">
    <div className="space-y-1"><h3 className="font-semibold">计划·资源</h3><p className="text-sm text-muted-foreground">核对正式执行与基线、实际进展、滚动预测和具名承诺；在资源预约中维护排程对象、里程碑、情景与跨项目依赖。</p></div>
    <CrossProposalLanding projectId={projectId} />
    <ScheduleResponsibilityLanding projectId={projectId} />
    <ApprovalRequestLanding projectId={projectId} />
    <ApprovalResponsibilityLanding projectId={projectId} />
    <ResourceAllocationLanding projectId={projectId}/>
    <ReservationResponsibilityLanding projectId={projectId}/>
    <ProjectTaskWorkspace label="计划与协调办理" sections={[
      { id: "execution-baseline", title: "确认执行与基线", description: "核对立项输入和执行批准，查看当前有效计划。", queryKeys: ["approval_request_id", "approval_policy_id"], hashPrefixes: ["project-execution"], children: <ProjectExecutionPanel key={`execution:${projectId}`} projectId={projectId} /> },
      { id: "formal-schedule", title: "查看正式计划", description: "核对正式节点、依赖和实际执行记录。", hashPrefixes: ["schedule-execution"], children: <ScheduleExecutionPanel key={`schedule-execution:${projectId}`} projectId={projectId} /> },
      { id: "progress-forecast", title: "核对进展与预测", description: "比较最新实际与基线，追查预测变化的来源。", queryKeys: ["forecast"], hashPrefixes: ["schedule-forecasts"], children: <ScheduleForecastPanel key={`forecasts:${projectId}`} projectId={projectId} /> },
      { id: "date-commitments", title: "办理时间承诺", description: "基于当前依据准备承诺，保留具名确认和外发边界。", queryKeys: ["commitment_node"], hashPrefixes: ["schedule-commitments"], children: <ScheduleCommitmentPanel key={`commitments:${projectId}`} projectId={projectId} /> },
      { id: "resource-inventory", title: "核对可用资源", description: "查看实际资源、容量和适用限制。", hashPrefixes: ["resource-inventory"], children: <ProjectResourceInventory key={`inventory:${projectId}`} projectId={projectId} /> },
      { id: "resource-coordination", title: "协调预约与依赖", description: "核对资源预约和跨项目接续，分别办理具名确认。", queryKeys: ["resource_allocation_id", "resource_reservation_id", "reservation_node_id", "reservation_resource_id", "reservation_owner_id", "cross_proposal", "schedule_responsibility_node"], hashPrefixes: ["resource-", "reservation-", "cross-proposal"], children: <ProjectReservationPanel key={`reservations:${projectId}`} projectId={projectId} userId={userId} /> },
    ]} />
  </section>;
}
