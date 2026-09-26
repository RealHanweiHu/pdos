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
    <ProjectExecutionPanel key={`execution:${projectId}`} projectId={projectId} />
    <ScheduleExecutionPanel key={`schedule-execution:${projectId}`} projectId={projectId} />
    <ScheduleForecastPanel key={`forecasts:${projectId}`} projectId={projectId} />
    <ScheduleCommitmentPanel key={`commitments:${projectId}`} projectId={projectId} />
    <ResourceAllocationLanding projectId={projectId}/>
    <ProjectResourceInventory key={`inventory:${projectId}`} projectId={projectId} />
    <ReservationResponsibilityLanding projectId={projectId}/>
    <ProjectReservationPanel key={`reservations:${projectId}`} projectId={projectId} userId={userId} />
  </section>;
}
