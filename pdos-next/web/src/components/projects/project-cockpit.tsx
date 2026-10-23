"use client";

import { useEffect, useState } from "react";
import { ArrowClockwise, ArrowLeft, ArrowRight, CalendarBlank, FolderSimple, Warning } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { dueState, findProject, openRisks, openTasks, projectStateLabel, readPortfolio, type Portfolio } from "@/lib/portfolio-reads";
import type { GlobalLocation } from "@/lib/global-navigation";
import type { browserApi } from "@/lib/browser-api";
import { ProjectWorkspace } from "./project-workspace";
import { ProjectStatusSummary } from "./project-status-summary";

import type { PaiContext } from "@/components/pai-rail";

type Api = typeof browserApi;
const visibilityLabels: Record<string, string> = { private: "私有", category: "品类共享", audience: "指定受众" };


function Overview({ portfolio, today, onOpenProject }: {
  portfolio: Portfolio; today: string;
  onOpenProject: (categoryId: string, projectId: string) => void;
}) {
  const riskCount = portfolio.projects.reduce((count, entry) => count + openRisks(entry).length, 0);
  const conflictCount = portfolio.projects.reduce((count, entry) => { const { overdue, soon } = openTasks(entry, today); return count + overdue.length + soon.length; }, 0);
  const partial = portfolio.readErrors.length > 0;
  const incompleteItems = partial || portfolio.projects.some(entry => !!entry.openItemsError);
  return <div className="project-canvas">
    <div className="workspace-page-heading flex-col sm:flex-row"><div className="min-w-0"><h1>项目驾驶舱</h1><p>本人权限内项目的经营总览：开放风险与到期冲突逐项目列出。资源与供应冲突读集尚未接入；基线、承诺与实绩时间线尚未记录时不填零。</p></div></div>
    <div className="workspace-object-counts">
      <div><dt><FolderSimple size={16} aria-hidden="true"/>可见项目</dt><dd>{partial ? "未完整读取" : portfolio.projects.length}</dd></div>
      <div><dt><Warning size={16} aria-hidden="true"/>开放风险</dt><dd>{incompleteItems ? "未完整读取" : riskCount}</dd></div>
      <div><dt><CalendarBlank size={16} aria-hidden="true"/>逾期与临期任务</dt><dd>{incompleteItems ? "未完整读取" : conflictCount}</dd></div>
    </div>
    {!partial && portfolio.projects.length === 0 && <div className="workspace-empty" role="status"><FolderSimple size={24} aria-hidden="true"/><p>没有可见项目。立项提案经具名 G0 批准后建立项目。</p></div>}
    <div className="grid gap-4 lg:grid-cols-2">{portfolio.projects.map(entry => {
      const risks = openRisks(entry);
      const { overdue, soon } = openTasks(entry, today);
      const conflicts = [...overdue, ...soon];
      return <section className="panel" key={entry.project.id} aria-label={`${entry.project.name}驾驶舱摘要`}>
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="font-semibold">{entry.project.name}</h2>
            <p className="subtle mt-1">{entry.category.name} · {entry.product.name} · {visibilityLabels[entry.project.visibility] ?? entry.project.visibility}</p>
          </div>
          <span className="workspace-state">{projectStateLabel(entry)}</span>
        </div>
        <div className="mt-4 space-y-2">
          {entry.openItemsError ? <p role="status" className="workspace-read-error">任务与风险暂不可读：{entry.openItemsError}</p> : <>
            {risks.length === 0 && conflicts.length === 0 && <p className="subtle">无开放风险或到期冲突。</p>}
            {risks.map(item => <p key={item.id} className="flex items-center gap-2 text-sm"><Warning size={15} className="shrink-0 text-destructive" aria-hidden="true"/><span className="break-words">{item.title}</span></p>)}
            {conflicts.map(item => <p key={item.id} className="flex items-center gap-2 text-sm"><CalendarBlank size={15} className="shrink-0" aria-hidden="true"/><span className="break-words">{item.title}</span>{dueState(item, today) === "overdue" && <span className="workspace-state text-destructive border-destructive">已逾期</span>}</p>)}
          </>}
        </div>
        <ProjectStatusSummary update={entry.project.latest_status_update}/>
        <div className="mt-5"><Button size="sm" variant="outline" onClick={() => onOpenProject(entry.category.id, entry.project.id)}>进入项目驾驶舱<ArrowRight size={14}/></Button></div>
      </section>;
    })}</div>
  </div>;
}


export function ProjectCockpit({ api, session, location, onOpenProject, onOpenOverview, onOpenWorkbench, onPaiContext }: {
  api: Api; session: { name: string; principal_id: string }; location: GlobalLocation;
  onOpenProject: (categoryId: string, projectId: string) => void;
  onOpenOverview: () => void;
  onPaiContext?: (context: PaiContext | null) => void;
  onOpenWorkbench: (categoryId: string, productId: string, projectId: string) => void;
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
  if (error) return <div className="project-canvas"><div className="workspace-page-heading flex-col sm:flex-row"><div className="min-w-0"><h1>项目驾驶舱</h1><p>读取失败。</p></div></div><p role="alert" className="workspace-read-error">{error}</p>{refresh}</div>;
  if (!portfolio) return <div className="project-canvas"><p role="status" className="subtle">正在读取项目经营总览…</p></div>;
  if (location.projectId && !entry) return <div className="project-canvas">
    <div className="workspace-page-heading flex-col sm:flex-row"><div className="min-w-0"><h1>项目驾驶舱</h1><p>此项目当前不可见或已移除；仅显示本人权限内项目。</p></div></div>
    <Button variant="outline" onClick={onOpenOverview}><ArrowLeft/>返回经营总览</Button>
  </div>;
  const readTime = portfolio.asOf && <p className="subtle mb-4">项目资料读取于 <time dateTime={portfolio.asOf}>{new Date(portfolio.asOf).toLocaleString()}</time></p>;
  if (entry) return <ProjectWorkspace entry={entry} api={api} session={session} today={today} onBack={onOpenOverview} onOpenWorkbench={onOpenWorkbench} readAt={portfolio.asOf} readVersion={reload} onRefresh={() => setReload(value => value + 1)} />;
  return <div className="project-canvas">
    {refresh}{readTime}
    {portfolio.readErrors.map(item => <p key={item.path} role="status" className="subtle">部分范围暂不可读：{item.message}</p>)}
    <Overview portfolio={portfolio} today={today} onOpenProject={onOpenProject} />
  </div>;
}
