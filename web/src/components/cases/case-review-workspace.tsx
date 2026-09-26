"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { WorkspaceShell } from "@/components/workspace-shell";
import { requestIdentity } from "@/components/workspace-api";
import type { WorkspaceIdentity } from "@/components/workspace-types";
import { Button } from "@/components/ui/button";
import { CaseReviews } from "./case-reviews";

export function CaseReviewWorkspace({ caseId, reviewId, policyId }: { caseId: string; reviewId?: string; policyId?: string }) {
  const router = useRouter();
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null);
  const [error, setError] = useState(""), [retry, setRetry] = useState(0), [loggingOut, setLoggingOut] = useState(false);
  useEffect(() => {
    let active = true;
    void requestIdentity().then(user => {
      if (!active) return;
      if (!user) { router.replace("/login"); return; }
      setIdentity(user); setError("");
    }).catch(e => { if (active) setError(e instanceof Error ? e.message : "读取登录信息失败"); });
    return () => { active = false; };
  }, [retry, router]);
  if (!identity) return <div className="space-y-3 p-6"><p role={error ? "alert" : "status"}>{error || "正在读取评审办理身份…"}</p>{error && <Button onClick={() => setRetry(value => value + 1)}>重新读取</Button>}</div>;
  const valid = [caseId, ...(reviewId ? [reviewId] : []), ...(policyId ? [policyId] : [])].every(id => /^[0-9a-f-]{36}$/i.test(id));
  return <WorkspaceShell active="cases" identity={identity} loggingOut={loggingOut} onLogout={() => { setLoggingOut(true); void fetch("/api/session/logout", { method: "POST" }).finally(() => router.replace("/login")); }}>
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6"><h1 className="text-xl font-semibold">评审责任与接续</h1><Link className="text-sm text-primary underline" href={`/cases#case-${caseId}`}>回到开发案例</Link>{valid ? <CaseReviews key={`${caseId}:${reviewId}:${policyId}`} caseId={caseId} updatedAt="" reviewId={reviewId} policyFocusId={policyId}/> : <p role="alert">评审编号无效，请从移交清单重新打开。</p>}</div>
  </WorkspaceShell>;
}
