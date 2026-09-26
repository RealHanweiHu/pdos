"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { caseLinkRequest } from "@/components/cases/case-requirements";
import { Button } from "@/components/ui/button";
import { ProjectIdHandoff } from "./project-id-handoff";

type Context = { revision: { id: string; owner_user_id: string }; people: { id: string; display_name: string }[]; artifacts: { id: string; kind: string; filename: string }[]; current_user_id: string; can_manage: boolean };
function subscribe(callback: () => void) { window.addEventListener("popstate", callback); return () => window.removeEventListener("popstate", callback); }
function selected() { const p = new URLSearchParams(window.location.search); return `${p.get("id_handoff") ?? ""}:${p.get("id_freeze") ?? ""}`; }

function Handoff({ projectId, handoffId, freezeId }: { projectId: string; handoffId: string; freezeId: string }) {
  const [data, setData] = useState<Context | null>(null), [error, setError] = useState(""), [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    async function read() {
      try {
        const packages = await caseLinkRequest<{ handoffs: { id: string; freeze_id: string; snapshot: { revision: { id: string } } }[] }>(`projects/${projectId}/execution/id-design/handoffs`);
        const original = packages.handoffs.find(item => item.id === handoffId && item.freeze_id === freezeId);
        if (!original) throw new Error("原交接不属于当前项目或冻结版本，请从移交清单重新打开");
        const value = await caseLinkRequest<Context>(`projects/${projectId}/execution/id-design/revisions/${original.snapshot.revision.id}`);
        if (active) { setData(value); setError(""); }
      } catch (e) { if (active) setError(e instanceof Error ? e.message : "原交接依据读取失败"); }
    }
    void read();
    return () => { active = false; };
  }, [projectId, handoffId, freezeId, retry]);
  return <section className="space-y-3" aria-label="设计原交接办理"><h3 className="font-semibold">设计交付与具名接收</h3>{error ? <div><p role="alert" className="text-destructive">{error}</p><Button type="button" size="sm" variant="outline" onClick={() => setRetry(value => value + 1)}>重新读取</Button></div> : null}{!data && !error ? <p className="text-sm">正在读取原交付及当前责任…</p> : null}{data ? <ProjectIdHandoff projectId={projectId} freezeId={freezeId} people={data.people} artifacts={data.artifacts} currentUserId={data.current_user_id} canManage={data.can_manage} ownerUserId={data.revision.owner_user_id} focusHandoffId={handoffId}/> : null}</section>;
}

export function IdHandoffLanding({ projectId }: { projectId: string }) {
  const target = useSyncExternalStore(subscribe, selected, () => ""), [handoffId, freezeId] = target.split(":");
  if (![handoffId, freezeId].every(id => id && /^[0-9a-f-]{36}$/.test(id))) return null;
  return <Handoff key={`${projectId}:${target}`} projectId={projectId} handoffId={handoffId} freezeId={freezeId}/>;
}
