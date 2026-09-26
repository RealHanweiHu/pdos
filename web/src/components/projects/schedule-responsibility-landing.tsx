"use client";

import { useSyncExternalStore } from "react";
import { ProjectScheduleScenarios } from "./project-schedule-scenarios";

function subscribe(callback: () => void) { window.addEventListener("popstate", callback); return () => window.removeEventListener("popstate", callback); }
function selected() { return new URLSearchParams(window.location.search).get("schedule_responsibility_node") ?? ""; }

export function ScheduleResponsibilityLanding({ projectId }: { projectId: string }) {
  const nodeId = useSyncExternalStore(subscribe, selected, () => "");
  if (!/^[0-9a-f-]{36}$/.test(nodeId)) return null;
  return <section className="space-y-3" aria-label="正式计划责任接续"><h3 className="font-semibold">本次交接涉及的正式计划责任</h3><p className="text-sm text-muted-foreground">核对当前节点，准备责任调整情景，完成容量检查、批准与独立应用后接续办理。</p><ProjectScheduleScenarios key={`${projectId}:${nodeId}`} projectId={projectId} targetNodeId={nodeId}/></section>;
}
