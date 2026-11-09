"use client";

import { useEffect, useState } from "react";
import { ArrowClockwise, ArrowLeft } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { findProject, readPortfolio, type Portfolio } from "@/lib/portfolio-reads";
import type { GlobalLocation } from "@/lib/global-navigation";
import type { browserApi } from "@/lib/browser-api";
import type { ProjectViewId } from "@/lib/project-workspace-navigation";
import { ProjectWorkspace } from "./project-workspace";
import { ProjectList } from "./project-list";

import type { PaiContext } from "@/features/xiaopai/pai-rail";

type Api = typeof browserApi;


export function ProjectCockpit({ api, session, location, onOpenProject, onOpenOverview, onOpenWorkbench, onOpenRun, onPaiContext, initialView = "tasks" }: {
  initialView?: ProjectViewId;
  api: Api; session: { name: string; principal_id: string }; location: GlobalLocation;
  onOpenProject: (categoryId: string, projectId: string) => void;
  onOpenOverview: () => void;
  onPaiContext?: (context: PaiContext | null) => void;
  onOpenWorkbench: (categoryId: string, productId: string, projectId: string) => void;
  onOpenRun?: (runId: string, categoryId: string) => void;
}) {
  const [reload, setReload] = useState(0);
  const scope = JSON.stringify([session.principal_id, location.categoryId, location.projectId, reload]);
  const [reading, setReading] = useState<{ scope: string; api: Api; portfolio: Portfolio | null; error: string } | null>(null);
  const current = reading?.scope === scope && reading.api === api ? reading : null;
  const portfolio = current?.portfolio ?? null, error = current?.error ?? "";
  const today = new Date().toISOString().slice(0, 10);
  const found = location.projectId && portfolio ? findProject(portfolio, location.projectId) : undefined;
  const entry = found && (!location.categoryId || found.category.id === location.categoryId) ? found : undefined;
  useEffect(() => {
    onPaiContext?.(entry ? { categoryId: entry.category.id, productId: entry.product.id, projectId: entry.project.id, projectName: entry.project.name, sources: [] } : null);
    return () => onPaiContext?.(null);
  }, [entry, onPaiContext]);

  useEffect(() => {
    let active = true;
    void readPortfolio(api, location.projectId || undefined).then(next => { if (active) setReading({ scope, api, portfolio: next, error: "" }); }).catch(failure => { if (active) setReading({ scope, api, portfolio: null, error: (failure as Error).message }); });
    return () => { active = false; };
  }, [api, location.projectId, scope]);

  const refresh = <Button variant="outline" className="mb-4" onClick={() => setReload(value => value + 1)}><ArrowClockwise/>刷新</Button>;
  if (error) return <><div className="workspace-page-heading flex-col sm:flex-row"><div className="min-w-0"><h1>项目驾驶舱</h1><p>读取失败。</p></div></div><p role="alert" className="workspace-read-error">{error}</p>{refresh}</>;
  if (!portfolio) return <p role="status" className="subtle">正在读取项目经营总览…</p>;
  if (location.projectId && !entry) return <>
    <div className="workspace-page-heading flex-col sm:flex-row"><div className="min-w-0"><h1>项目驾驶舱</h1><p>此项目当前不可见或已移除；仅显示本人权限内项目。</p></div></div>
    <Button variant="outline" onClick={onOpenOverview}><ArrowLeft/>返回经营总览</Button>
  </>;
  if (entry) return <ProjectWorkspace initialView={initialView} entry={entry} api={api} session={session} today={today} onBack={onOpenOverview} onOpenWorkbench={onOpenWorkbench} onOpenRun={onOpenRun} readAt={portfolio.asOf} readVersion={reload} onRefresh={() => setReload(value => value + 1)} />;
  // 没有指定项目时，旧“项目驾驶舱”入口打开“项目”页的驾驶舱视图（P75-2/3），不再另设计数卡片页。
  return <ProjectList api={api} principalId={session.principal_id} onOpenProject={onOpenProject} initialView="驾驶舱"/>;
}
