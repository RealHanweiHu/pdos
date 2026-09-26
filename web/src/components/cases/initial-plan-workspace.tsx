"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { WorkspaceShell } from "@/components/workspace-shell";
import { requestIdentity } from "@/components/workspace-api";
import type { WorkspaceIdentity } from "@/components/workspace-types";
import { Button } from "@/components/ui/button";
import { caseLinkRequest } from "./case-requirements";
import { InitialPlans, type InitialPlanDetail } from "./initial-plans";

export function InitialPlanWorkspace({ candidateId, nodeKey }: { candidateId: string; nodeKey?: string }) {
  const router = useRouter();
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null), [detail, setDetail] = useState<InitialPlanDetail | null>(null);
  const [error, setError] = useState(""), [retry, setRetry] = useState(0), [loggingOut, setLoggingOut] = useState(false);
  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const user = await requestIdentity();
        if (!user) { if (active) router.replace("/login"); return; }
        if (active) setIdentity(user);
        if (!/^[0-9a-f-]{36}$/i.test(candidateId)) throw new Error("计划编号无效，请从移交清单重新打开");
        const value = await caseLinkRequest<InitialPlanDetail>(`initial-plans/${candidateId}`);
        if (value.candidate.id !== candidateId) throw new Error("计划回执与所选版本不一致，请重新读取");
        if (active) { setDetail(value); setError(""); }
      } catch (e) { if (active) setError(e instanceof Error ? e.message : "原计划暂不可读取"); }
    }
    void load();
    return () => { active = false; };
  }, [candidateId, retry, router]);
  const status = <div className="space-y-2 p-6"><p role={error ? "alert" : "status"}>{error || "正在读取计划来源、原版本和当前办理权限…"}</p>{error ? <Button type="button" size="sm" variant="outline" onClick={() => setRetry(value => value + 1)}>重新读取</Button> : null}</div>;
  if (!identity) return status;
  return <WorkspaceShell active={detail?.source.kind === "development_case" ? "cases" : "product-work"} identity={identity} loggingOut={loggingOut} onLogout={() => { setLoggingOut(true); void fetch("/api/session/logout", { method: "POST" }).finally(() => router.replace("/login")); }}>
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6"><h1 className="text-xl font-semibold">计划责任与接续</h1><p className="text-sm text-muted-foreground">核对原计划及所涉节点，沿原修订、本人责任确认、排程和审阅流程办理。</p>{detail ? <><Link className="text-sm text-primary underline" href={detail.source.kind === "development_case" ? `/cases#case-${detail.source.id}` : `/product-work?space=${detail.space_id}`}>回到来源工作区</Link><InitialPlans key={candidateId} source={detail.source} spaceId={detail.space_id ?? undefined} initialDetail={detail} nodeKey={nodeKey}/></> : status}</div>
  </WorkspaceShell>;
}
