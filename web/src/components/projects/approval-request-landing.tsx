"use client";

import { useSyncExternalStore } from "react";
import { ProjectExecutionPanel } from "./project-execution-panel";
import { ProjectBaselineChanges } from "./project-baseline-changes";

function subscribe(callback: () => void) { window.addEventListener("popstate", callback); return () => window.removeEventListener("popstate", callback); }
function selected() { const p = new URLSearchParams(window.location.search); return `${p.get("approval_request_kind") ?? ""}:${p.get("approval_request_id") ?? ""}`; }
export function ApprovalRequestLanding({ projectId }: { projectId: string }) {
  const target = useSyncExternalStore(subscribe, selected, () => ""), [kind, id] = target.split(":");
  if ((kind !== "execution" && kind !== "baseline") || !id || !/^[0-9a-f-]{36}$/.test(id)) return null;
  return <section className="space-y-3" aria-label="原批准申请办理"><h3 className="font-semibold">本次交接涉及的原申请</h3>
    <p className="text-sm text-muted-foreground">按原申请核对依据、当前政策与办理条件。历史批准和正式应用继续保留。</p>
    {kind === "execution" ? <ProjectExecutionPanel key={`${projectId}:${id}`} projectId={projectId} targetId={id}/> : <ProjectBaselineChanges key={`${projectId}:${id}`} projectId={projectId} scenarios={[]} targetId={id}/>}
  </section>;
}
