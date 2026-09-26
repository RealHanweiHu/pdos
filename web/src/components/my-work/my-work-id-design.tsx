"use client";
import { useEffect, useState } from "react";
import { caseLinkRequest } from "@/components/cases/case-requirements";
import { ProjectIdFreeze } from "@/components/projects/project-id-freeze";
import { ProjectIdHandoff } from "@/components/projects/project-id-handoff";
import type { MyWorkIdDesign } from "./my-work-types";

type Context = { revision: { id: string; owner_user_id: string; variant_id: string; version: number; payload_digest: string }; people: { id: string; display_name: string }[]; artifacts: { id: string; kind: string; filename: string }[]; current_user_id: string; can_manage: boolean; can_revise: boolean; can_decide: boolean };
export function MyWorkIdDesignAction({ item, onChanged }: { item: MyWorkIdDesign; onChanged: () => void }) {
  const [data,setData] = useState<Context | null>(null); const [error,setError] = useState<string | null>(null);
  useEffect(() => { let active=true; caseLinkRequest<Context>(`projects/${item.project.id}/execution/id-design/revisions/${item.revision_id}`).then((value) => { if(active) setData(value); }).catch((error: unknown) => { if(active) setError(error instanceof Error ? error.message : "办理依据读取失败"); }); return () => { active=false; }; },[item.project.id,item.revision_id]);
  return <div className="space-y-2">
    <p className="text-sm">{item.project.code} · {item.title}</p>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {!data && !error && <p className="text-sm text-muted-foreground">正在读取当前权限与交付依据…</p>}
    {data && item.kind === "freeze" && <ProjectIdFreeze projectId={item.project.id} revision={data.revision} people={data.people} artifacts={data.artifacts} currentUserId={data.current_user_id} canManage={data.can_manage && data.can_revise} canDecide={data.can_decide} focusRequestId={item.id} onChanged={onChanged} />}
    {data && item.kind === "handoff" && item.freeze_id && <ProjectIdHandoff projectId={item.project.id} freezeId={item.freeze_id} people={data.people} artifacts={data.artifacts} currentUserId={data.current_user_id} canManage={data.can_manage} ownerUserId={data.revision.owner_user_id} focusHandoffId={item.id} onChanged={onChanged} />}
  </div>;
}
