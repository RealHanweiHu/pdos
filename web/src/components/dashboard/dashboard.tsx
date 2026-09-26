"use client";

import { FolderDashedIcon, WarningCircleIcon } from "@phosphor-icons/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { WorkspaceShell } from "@/components/workspace-shell";
import type { WorkspaceIdentity } from "@/components/workspace-types";
import { requestProjects } from "@/components/projects/project-api";
import { projectStatusLabels } from "@/components/projects/project-list";
import type { Project } from "@/components/projects/project-types";
import { cn } from "@/lib/utils";
import { requestAiBrief } from "@/components/ai/ai-api";
import { AiBriefCard, type AiBriefLoadState } from "@/components/ai/ai-brief-card";
import type { AiBrief } from "@/components/ai/ai-types";
import { requestDashboardRisks, type DashboardRisks } from "./dashboard-api";

type DashboardState = "loading" | "ready" | "error" | "redirecting";
type RiskState = "loading" | "ready" | "error" | "restricted";
const riskRoles = ["owner", "admin", "project_manager", "engineer", "quality"];

function scoreTone(score: number) {
  if (score >= 15) return "border-destructive/25 bg-destructive/10 text-destructive";
  if (score >= 8) return "border-pending/25 bg-pending/10 text-pending";
  return "border-border bg-muted text-muted-foreground";
}

export function Dashboard() {
  const { replace } = useRouter();
  const [state, setState] = useState<DashboardState>("loading");
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [riskSnapshot, setRiskSnapshot] = useState<DashboardRisks | null>(null);
  const [riskState, setRiskState] = useState<RiskState>("loading");
  const [brief, setBrief] = useState<AiBrief | null>(null);
  const [briefState, setBriefState] = useState<AiBriefLoadState>("loading");
  const [loggingOut, setLoggingOut] = useState(false);

  async function loadDashboard() {
    setState("loading");
    try {
      const loaded = await requestProjects();
      if (loaded === null) {
        setState("redirecting");
        replace("/login");
        return;
      }
      if (["engineer", "quality"].includes(loaded.identity.user.role)) {
        setState("redirecting");
        replace("/my-work");
        return;
      }
      setIdentity(loaded.identity);
      setProjects(loaded.projects);
      setState("ready");
      if (!riskRoles.includes(loaded.identity.user.role)) {
        setRiskSnapshot(null);
        setRiskState("restricted");
        setBrief(null);
        setBriefState("restricted");
        return;
      }
      await Promise.all([loadRisks(), loadBrief()]);
    } catch {
      setState("error");
    }
  }

  async function loadRisks() {
    setRiskState("loading");
    try {
      setRiskSnapshot(await requestDashboardRisks());
      setRiskState("ready");
    } catch {
      setRiskSnapshot(null);
      setRiskState("error");
    }
  }

  async function loadBrief() {
    setBriefState("loading");
    try {
      setBrief(await requestAiBrief());
      setBriefState("ready");
    } catch {
      setBrief(null);
      setBriefState("error");
    }
  }

  useEffect(() => {
    let active = true;
    requestProjects().then(
      (loaded) => {
        if (!active) return;
        if (loaded === null) {
          setState("redirecting");
          replace("/login");
          return;
        }
        if (["engineer", "quality"].includes(loaded.identity.user.role)) {
          setState("redirecting");
          replace("/my-work");
          return;
        }
        setIdentity(loaded.identity);
        setProjects(loaded.projects);
        setState("ready");
        if (!riskRoles.includes(loaded.identity.user.role)) {
          setRiskSnapshot(null);
          setRiskState("restricted");
          setBrief(null);
          setBriefState("restricted");
          return;
        }
        requestDashboardRisks().then(
          (snapshot) => {
            if (!active) return;
            setRiskSnapshot(snapshot);
            setRiskState("ready");
          },
          () => {
            if (!active) return;
            setRiskSnapshot(null);
            setRiskState("error");
          },
        );
        requestAiBrief().then(
          (loadedBrief) => {
            if (!active) return;
            setBrief(loadedBrief);
            setBriefState("ready");
          },
          () => {
            if (!active) return;
            setBrief(null);
            setBriefState("error");
          },
        );
      },
      () => {
        if (active) setState("error");
      },
    );
    return () => { active = false; };
  }, [replace]);

  async function logout() {
    setLoggingOut(true);
    try {
      await fetch("/api/session/logout", { method: "POST", credentials: "same-origin" });
    } finally {
      replace("/login");
    }
  }

  if (state === "redirecting") return null;
  if (state === "loading") return <main className="mx-auto max-w-6xl px-4 py-10 text-sm text-muted-foreground">正在加载驾驶舱…</main>;
  if (state === "error" || identity === null) {
    return (
      <main className="mx-auto flex min-h-svh max-w-md flex-col items-center justify-center px-6 text-center">
        <WarningCircleIcon aria-hidden="true" className="size-9 text-destructive" />
        <h1 className="mt-3 text-lg font-semibold">驾驶舱暂不可用</h1>
        <p className="mt-1 text-sm text-muted-foreground">无法读取项目组合，请检查连接后重试。</p>
        <Button className="mt-4 h-11" onClick={() => void loadDashboard()}>重新加载</Button>
      </main>
    );
  }

  const risks = riskSnapshot?.items ?? [];
  const risksByProject = new Map(riskSnapshot?.projects.map((summary) => [summary.project_id, summary]) ?? []);

  return (
    <WorkspaceShell active="dashboard" identity={identity} loggingOut={loggingOut} onLogout={() => void logout()}>
      <div className="flex flex-wrap items-end justify-between gap-3 border-b pb-4">
        <div>
          <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-primary">Portfolio</p>
          <h1 className="mt-1 text-lg font-semibold">驾驶舱</h1>
          <p className="mt-1 text-sm text-muted-foreground">可见项目组合与开放风险的当前快照。</p>
        </div>
        <span className="font-mono text-[11px] text-muted-foreground">{projects.length} 个可见项目</span>
      </div>

      <div className="mt-6 grid min-w-0 items-start gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(300px,1fr)]">
        <section aria-label="项目组合" className="min-w-0 overflow-hidden rounded-lg border bg-card">
          <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
            <h2 className="font-semibold">项目组合</h2>
            <Link className="inline-flex min-h-11 items-center text-xs font-medium text-primary xl:min-h-0" href="/projects">全部项目 ›</Link>
          </div>
          {projects.length === 0 ? (
            <div className="flex min-h-64 flex-col items-center justify-center px-6 text-center">
              <FolderDashedIcon aria-hidden="true" className="size-8 text-muted-foreground" />
              <h3 className="mt-3 font-semibold">还没有可见项目</h3>
              <p className="mt-1 text-sm text-muted-foreground">先从已批准的开发案例创建项目。</p>
            </div>
          ) : (
            <div className="grid sm:grid-cols-2">
              {projects.map((project) => {
                const riskSummary = risksByProject.get(project.id);
                const maxRisk = riskSummary?.max_score ?? 0;
                const progress = Math.round((project.current_stage.sequence / project.workflow.stages.length) * 100);
                return (
                  <Link
                    aria-label={`打开项目 ${project.code}`}
                    className="min-w-0 border-b p-4 transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-inset focus-visible:ring-ring/25 sm:odd:border-r"
                    href={`/projects?project=${encodeURIComponent(project.id)}`}
                    key={project.id}
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <span
                        aria-hidden="true"
                        className={cn(
                          "size-2 shrink-0 rounded-full",
                          riskState !== "ready" || !riskSummary ? "bg-muted-foreground/35" : maxRisk >= 15 ? "bg-destructive" : maxRisk > 0 ? "bg-pending" : "bg-success",
                        )}
                      />
                      <span className="truncate font-semibold">{project.name}</span>
                      <span className="ml-auto shrink-0 rounded-full border bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">{project.current_stage.code.toUpperCase()}</span>
                    </div>
                    <div className="mt-1 flex items-center justify-between gap-3 text-[11px] text-muted-foreground">
                      <span className="font-mono">{project.code}</span>
                      <span>{projectStatusLabels[project.status]}</span>
                    </div>
                    <div className="mt-4 h-1 overflow-hidden rounded-full bg-muted"><span className="block h-full rounded-full bg-primary" style={{ width: `${progress}%` }} /></div>
                    <div className="mt-1.5 flex justify-between gap-3 text-[11px] text-muted-foreground">
                      <span>阶段进度 {progress}%</span>
                      <span>{riskState === "ready" && riskSummary ? `开放风险 ${riskSummary.open_risk_count}` : "风险待确认"}</span>
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </section>

        <section aria-label="跨项目风险" className="min-w-0 overflow-hidden rounded-lg border bg-card">
          <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
            <h2 className="font-semibold">跨项目风险</h2>
            {riskState === "ready" ? <span className="font-mono text-[11px] text-muted-foreground">Top {risks.length} · 共 {riskSnapshot?.total ?? 0} 项</span> : null}
          </div>
          {riskState === "loading" ? <p className="px-4 py-10 text-center text-sm text-muted-foreground">正在汇总风险…</p> : null}
          {riskState === "restricted" ? <p className="px-4 py-10 text-center text-sm text-muted-foreground">外部成员不具备工程风险视图权限。</p> : null}
          {riskState === "error" ? (
            <div className="px-4 py-8 text-center" role="alert">
              <p className="font-medium text-destructive">风险聚合暂不可用</p>
              <p className="mt-1 text-xs text-muted-foreground">失败状态不会被展示为零风险。</p>
              <Button className="mt-4 h-11" onClick={() => void loadRisks()} variant="outline">重新汇总</Button>
            </div>
          ) : null}
          {riskState === "ready" && risks.length === 0 ? <p className="px-4 py-10 text-center text-sm text-muted-foreground">当前没有开放风险。</p> : null}
          {riskState === "ready" && risks.length > 0 ? (
            <ol className="divide-y">
              {risks.map((risk, index) => (
                <li data-testid="dashboard-risk" key={risk.id}>
                  <Link className="flex min-h-16 min-w-0 items-center gap-3 px-4 py-3 hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-inset focus-visible:ring-ring/25" href={`/projects?project=${encodeURIComponent(risk.project_id)}&tab=work-items`}>
                    <span className="w-4 shrink-0 font-mono text-[11px] text-muted-foreground">{index + 1}</span>
                    <span className={cn("shrink-0 rounded-full border px-2 py-0.5 font-mono text-[10px] font-semibold", scoreTone(risk.score))}>{risk.score}</span>
                    <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{risk.title}</span><span className="mt-0.5 block truncate font-mono text-[10px] text-muted-foreground">{risk.project.code}</span></span>
                  </Link>
                </li>
              ))}
            </ol>
          ) : null}
        </section>
        <AiBriefCard brief={brief} onRetry={() => void loadBrief()} state={briefState} />
      </div>
    </WorkspaceShell>
  );
}
