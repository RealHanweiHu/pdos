"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { caseLinkRequest } from "@/components/cases/case-requirements";
import { Button } from "@/components/ui/button";
import { ProjectIdFreeze } from "./project-id-freeze";

type Context = { revision: { id: string; owner_user_id: string; variant_id: string; version: number; payload_digest: string }; people: { id: string; display_name: string }[]; artifacts: { id: string; kind: string; filename: string }[]; current_user_id: string; can_manage: boolean; can_revise: boolean; can_decide: boolean };
function subscribe(callback: () => void) { window.addEventListener("popstate", callback); return () => window.removeEventListener("popstate", callback); }
function selected() { const p = new URLSearchParams(window.location.search); return `${p.get("id_freeze_request") ?? ""}:${p.get("id_revision") ?? ""}`; }

function Request({ projectId, requestId, revisionId }: { projectId: string; requestId: string; revisionId: string }) {
  const [data, setData] = useState<Context | null>(null), [error, setError] = useState(""), [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    void caseLinkRequest<Context>(`projects/${projectId}/execution/id-design/revisions/${revisionId}`).then(value => { if (active) { setData(value); setError(""); } }, e => { if (active) setError(e instanceof Error ? e.message : "原申请依据读取失败"); });
    return () => { active = false; };
  }, [projectId, revisionId, retry]);
  return <section className="space-y-3" aria-label="原设计冻结确认申请"><h3 className="font-semibold">设计冻结确认申请</h3>{error ? <div><p role="alert" className="text-destructive">{error}</p><Button type="button" size="sm" variant="outline" onClick={() => setRetry(value => value + 1)}>重新读取</Button></div> : null}{!data && !error ? <p className="text-sm">正在读取具名确认及固定依据…</p> : null}{data ? <ProjectIdFreeze projectId={projectId} revision={data.revision} people={data.people} artifacts={data.artifacts} currentUserId={data.current_user_id} canManage={data.can_manage && data.can_revise} canDecide={data.can_decide} focusRequestId={requestId}/> : null}</section>;
}

export function IdFreezeRequestLanding({ projectId }: { projectId: string }) {
  const target = useSyncExternalStore(subscribe, selected, () => ""), [requestId, revisionId] = target.split(":");
  if (![requestId, revisionId].every(id => id && /^[0-9a-f-]{36}$/.test(id))) return null;
  return <Request key={`${projectId}:${target}`} projectId={projectId} requestId={requestId} revisionId={revisionId}/>;
}
