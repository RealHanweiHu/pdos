"use client";
import { useEffect, useState } from "react";
import { LegacyAskWorkspace } from "./legacy-ask-workspace";
import { useRouter, useSearchParams } from "next/navigation";
import { WorkspaceShell } from "@/components/workspace-shell";
import { requestIdentity } from "@/components/workspace-api";
import type { WorkspaceIdentity } from "@/components/workspace-types";

export function AskWorkspace() {
  const query = useSearchParams();
  return query.get("meeting") ? <LegacyAskWorkspace/> : <XiaopaiWorkspaceShell/>;
}

function XiaopaiWorkspaceShell() {
  const router = useRouter();
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { let active = true; void requestIdentity().then(value => { if (!active) return; if (!value) router.replace("/login"); else setIdentity(value); }).catch(() => { if (active) setError("小Pai入口暂时无法连接，请刷新重试"); }); return () => { active = false; }; }, [router]);
  if (!identity) return <p className="p-6 text-sm" role="status">{error ?? "正在打开小Pai…"}</p>;
  return <WorkspaceShell active="ask" identity={identity} loggingOut={busy} onLogout={() => { setBusy(true); void fetch("/api/session/logout", { method: "POST" }).finally(() => router.replace("/login")); }}><div className="min-h-[70vh] p-6"><p className="sr-only">小Pai个人 Agent 完整对话</p></div></WorkspaceShell>;
}
