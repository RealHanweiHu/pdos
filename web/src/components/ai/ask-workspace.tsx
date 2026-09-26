"use client";
import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { WorkspaceShell } from "@/components/workspace-shell";
import { requestIdentity } from "@/components/workspace-api";
import type { WorkspaceIdentity } from "@/components/workspace-types";
import { requestProjectList } from "@/components/projects/project-api";
import type { Project } from "@/components/projects/project-types";
import { parseWorkFocus } from "./conversation-work-focus";
import { ProjectConversation } from "./project-conversation";

export function AskWorkspace() {
  const query = useSearchParams(), router = useRouter();
  const projectId = query.get("project") ?? "", meetingId = query.get("meeting"), conversationId = query.get("conversation") ?? undefined;
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [draftDirty, setDraftDirty] = useState(false);
  useEffect(() => { let active = true; void (async () => { try { const user = await requestIdentity(); if (!user) { router.replace("/login"); return; } const rows = await requestProjectList(); if (!rows) { router.replace("/login"); return; } if (active) { setIdentity(user); setProjects(rows); } } catch (e) { if (active) setError(e instanceof Error ? e.message : "会话入口暂不可用"); } })(); return () => { active = false; }; }, [router]);
  if (!identity) return <p className="p-6 text-sm" role="status">{error ?? "正在读取本人可访问项目…"}</p>;
  return <WorkspaceShell active="ask" identity={identity} loggingOut={busy} onLogout={() => { setBusy(true); void fetch("/api/session/logout", { method: "POST" }).finally(() => router.replace("/login")); }}>
    <div className="mx-auto max-w-5xl space-y-5 p-4 sm:p-6"><header><h1 className="text-xl font-semibold">Ask PDOS</h1><p className="mt-2 text-sm text-muted-foreground">连续提问、补充资料，并在同一会话核对和办理会议候选。</p></header>
      <label className="block text-sm">当前项目<select className="ml-3 rounded-md border bg-background p-2" value={projectId} disabled={draftDirty} onChange={e => router.push(`/ask?project=${e.target.value}`)}><option value="">请选择本次范围</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
      {draftDirty && <p className="text-xs text-muted-foreground">请先保存或清空当前消息和附件选择，再切换项目。</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {projectId && projects.some(p => p.id === projectId) ? <ProjectConversation key={`${projectId}:${meetingId}:${conversationId}:${query.get("focus_kind")}:${query.get("focus_id")}`} initialWorkFocus={parseWorkFocus(query.get("focus_kind"), query.get("focus_id"))} projectId={projectId} meetingId={meetingId} initialConversationId={conversationId} initialAttachmentId={query.get("attachment") ?? undefined} initialFragment={Math.max(1, Number(query.get("fragment")) || 1)} defaultOpen onDraftDirtyChange={setDraftDirty} /> : <p className="text-sm text-muted-foreground">先选定可访问项目再开始。本入口目前使用单项目会话，选择项目后可保存消息并继续项目或会议会话。</p>}
    </div>
  </WorkspaceShell>;
}
