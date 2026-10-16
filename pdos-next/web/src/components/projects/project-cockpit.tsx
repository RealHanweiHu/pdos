"use client";

import { useEffect, useState } from "react";
import { ArrowClockwise, ArrowLeft, ArrowRight, CalendarBlank, ClipboardText, FolderSimple, Warning } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { dueState, findProject, openRisks, openTasks, projectStateLabel, readPortfolio, type Portfolio, type PortfolioProject } from "@/lib/portfolio-reads";
import type { GlobalLocation } from "@/lib/global-navigation";
import type { browserApi } from "@/lib/browser-api";

type Api = typeof browserApi;
const visibilityLabels: Record<string, string> = { private: "私有", category: "品类共享", audience: "指定受众" };
const disciplineLabels: Record<string, string> = { engineering: "工程", npi: "NPI" };
const kindLabels: Record<string, string> = { task: "任务", risk: "风险" };

function dueChip(item: { due_date: string | null; status: string }, today: string) {
  const state = dueState(item, today);
  if (state === "overdue") return <span className="workspace-state text-destructive border-destructive">已逾期 · {item.due_date}</span>;
  if (state === "soon") return <span className="workspace-state">临期 · {item.due_date}</span>;
  if (item.due_date) return <span className="workspace-state">{item.due_date}</span>;
  return <span className="workspace-state">无期限</span>;
}

function Overview({ portfolio, today, onOpenProject }: {
  portfolio: Portfolio; today: string;
  onOpenProject: (categoryId: string, projectId: string) => void;
}) {
  const riskCount = portfolio.projects.reduce((count, entry) => count + openRisks(entry).length, 0);
  const conflictCount = portfolio.projects.reduce((count, entry) => { const { overdue, soon } = openTasks(entry, today); return count + overdue.length + soon.length; }, 0);
  const partial = portfolio.readErrors.length > 0;
  return <>
    <div className="workspace-page-heading flex-col sm:flex-row"><div className="min-w-0"><h1>项目驾驶舱</h1><p>本人权限内项目的经营总览：开放风险与到期冲突逐项目列出。资源与供应冲突读集尚未接入；基线、承诺与实绩时间线尚未记录时不填零。</p></div></div>
    <div className="workspace-object-counts">
      <div><dt><FolderSimple size={16} aria-hidden="true"/>可见项目</dt><dd>{partial ? "未完整读取" : portfolio.projects.length}</dd></div>
      <div><dt><Warning size={16} aria-hidden="true"/>开放风险</dt><dd>{partial ? "未完整读取" : riskCount}</dd></div>
      <div><dt><CalendarBlank size={16} aria-hidden="true"/>逾期与临期任务</dt><dd>{partial ? "未完整读取" : conflictCount}</dd></div>
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
          {risks.length === 0 && conflicts.length === 0 && <p className="subtle">无开放风险或到期冲突。</p>}
          {risks.map(item => <p key={item.id} className="flex items-center gap-2 text-sm"><Warning size={15} className="shrink-0 text-destructive" aria-hidden="true"/><span className="break-words">{item.title}</span></p>)}
          {conflicts.map(item => <p key={item.id} className="flex items-center gap-2 text-sm"><CalendarBlank size={15} className="shrink-0" aria-hidden="true"/><span className="break-words">{item.title}</span>{dueState(item, today) === "overdue" && <span className="workspace-state text-destructive border-destructive">已逾期</span>}</p>)}
        </div>
        <div className="mt-5"><Button size="sm" variant="outline" onClick={() => onOpenProject(entry.category.id, entry.project.id)}>进入项目驾驶舱<ArrowRight size={14}/></Button></div>
      </section>;
    })}</div>
  </>;
}

function SingleCockpit({ entry, session, today, onBack, onOpenWorkbench }: {
  entry: PortfolioProject; session: { name: string; principal_id: string }; today: string;
  onBack: () => void; onOpenWorkbench: (categoryId: string, productId: string) => void;
}) {
  const { project, category, product } = entry;
  const open = entry.openItems.filter(item => item.status !== "done" && item.status !== "closed" && item.status !== "cancelled");
  return <>
    <div className="workspace-page-heading flex-col sm:flex-row">
      <div className="min-w-0"><h1>{project.name}</h1><p>{category.name} · {product.name} · 项目驾驶舱</p></div>
      <div className="flex flex-wrap gap-2"><Button variant="outline" onClick={onBack}><ArrowLeft/>经营总览</Button><Button variant="outline" onClick={() => onOpenWorkbench(category.id, product.id)}>进入项目工作台<ArrowRight size={14}/></Button></div>
    </div>
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
      <div className="space-y-6">
        <section className="panel" aria-label="项目基础信息">
          <h2 className="mb-4 font-semibold">基础信息</h2>
          <dl className="space-y-3 text-sm">
            <div className="flex justify-between gap-4"><dt className="subtle shrink-0">用途</dt><dd className="break-words text-right">{project.purpose}</dd></div>
            <div className="flex justify-between gap-4"><dt className="subtle shrink-0">工作范围</dt><dd className="break-words text-right">{project.scope}</dd></div>
            <div className="flex justify-between gap-4"><dt className="subtle shrink-0">可见性</dt><dd>{visibilityLabels[project.visibility] ?? project.visibility}</dd></div>
            <div className="flex justify-between gap-4"><dt className="subtle shrink-0">负责人</dt><dd>{project.owner_id === session.principal_id ? `${session.name}（本人）` : project.owner_name ?? "负责人信息暂不可读"}</dd></div>
            <div className="flex justify-between gap-4"><dt className="subtle shrink-0">建立时间</dt><dd><time dateTime={project.created_at}>{new Date(project.created_at).toLocaleString()}</time></dd></div>
            <div className="flex justify-between gap-4"><dt className="subtle shrink-0">立项定义</dt><dd className="text-right">{project.definition.title} · 固定 v{project.definition.revision}{project.source_status !== "current" ? " · 需重核" : ""}</dd></div>
          </dl>
        </section>
        <section className="panel" aria-label="未决事项">
          <div className="mb-4 flex items-center gap-2"><ClipboardText className="text-primary" aria-hidden="true"/><h2 className="font-semibold">未决事项</h2><span className="subtle ml-auto">{open.length} 项</span></div>
          {entry.openItemsError && <p role="status" className="subtle">未决事项暂不可读：{entry.openItemsError}</p>}
          {!entry.openItemsError && open.length === 0 && <p className="subtle">没有未决任务或风险。</p>}
          <div className="space-y-3">{open.map(item => <div key={item.id} className="flex items-center gap-3 border-t border-border pt-3 first:border-0 first:pt-0">
            {item.kind === "risk" ? <Warning size={16} className="shrink-0" aria-hidden="true"/> : <ClipboardText size={16} className="shrink-0" aria-hidden="true"/>}
            <div className="min-w-0 flex-1"><p className="break-words text-sm">{item.title}</p><p className="subtle mt-1">{kindLabels[item.kind] ?? item.kind} · {item.owner_id === session.principal_id ? "本人负责" : item.owner_name ? `${item.owner_name}负责` : "负责人信息暂不可读"}</p></div>
            {dueChip(item, today)}
          </div>)}</div>
        </section>
      </div>
      <div className="space-y-6">
        <section className="panel" aria-label="计划与时间线">
          <div className="mb-4 flex items-center gap-2"><CalendarBlank className="text-primary" aria-hidden="true"/><h2 className="font-semibold">计划与时间线</h2></div>
          {project.plan ? <dl className="space-y-3 text-sm">
            <div className="flex justify-between gap-4"><dt className="subtle">计划版本</dt><dd>v{project.plan.revision}</dd></div>
            <div className="flex justify-between gap-4"><dt className="subtle">最早完成</dt><dd>{project.plan.forecast?.earliest_finish ?? "未知"}</dd></div>
            <div className="flex justify-between gap-4"><dt className="subtle">最晚完成</dt><dd>{project.plan.forecast?.latest_finish ?? "未知"}</dd></div>
          </dl> : <p className="subtle">{project.plan_state === "unavailable" ? "当前计划暂不可读，请核对权限后刷新。" : "尚无已应用计划。首版计划在工作与计划区起草并经一次确认应用。"}</p>}
          <p className="subtle mt-4">批准基线、个人承诺与实绩时间线尚未记录；此处不填零，取得后分列显示。</p>
        </section>
        <section className="panel" aria-label="工作包与任务">
          <h2 className="mb-4 font-semibold">工作包与任务</h2>
          <dl className="space-y-3 text-sm">
            <div className="flex justify-between gap-4"><dt className="subtle shrink-0">工作包</dt><dd>{project.plan_state === "unavailable" ? "暂不可读" : project.work_packages.length === 0 ? "尚无" : project.work_packages.map(item => disciplineLabels[item.discipline] ?? item.discipline).join(" · ")}</dd></div>
            <div className="flex justify-between gap-4"><dt className="subtle shrink-0">排期任务</dt><dd>{project.task_count === null ? "尚无可读计划" : `${project.task_count} 项`}</dd></div>
          </dl>
          <div className="mt-5"><Button size="sm" variant="outline" onClick={() => onOpenWorkbench(category.id, product.id)}>在工作台办理计划与执行<ArrowRight size={14}/></Button></div>
        </section>
      </div>
    </div>
  </>;
}

export function ProjectCockpit({ api, session, location, onOpenProject, onOpenOverview, onOpenWorkbench }: {
  api: Api; session: { name: string; principal_id: string }; location: GlobalLocation;
  onOpenProject: (categoryId: string, projectId: string) => void;
  onOpenOverview: () => void;
  onOpenWorkbench: (categoryId: string, productId: string) => void;
}) {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const today = new Date().toISOString().slice(0, 10);

  useEffect(() => {
    let active = true;
    void readPortfolio(api, location.projectId || undefined).then(next => { if (active) { setPortfolio(next); setError(""); } }).catch(failure => { if (active) { setPortfolio(null); setError((failure as Error).message); } });
    return () => { active = false; };
  }, [api, location.projectId, reload]);

  const refresh = <Button variant="outline" className="mb-4" onClick={() => { setPortfolio(null); setError(""); setReload(value => value + 1); }}><ArrowClockwise/>刷新</Button>;
  if (error) return <><div className="workspace-page-heading flex-col sm:flex-row"><div className="min-w-0"><h1>项目驾驶舱</h1><p>读取失败。</p></div></div><p role="alert" className="workspace-read-error">{error}</p>{refresh}</>;
  if (!portfolio) return <p role="status" className="subtle">正在读取项目经营总览…</p>;
  const entry = location.projectId ? findProject(portfolio, location.projectId) : undefined;
  if (location.projectId && !entry) return <>
    <div className="workspace-page-heading flex-col sm:flex-row"><div className="min-w-0"><h1>项目驾驶舱</h1><p>此项目当前不可见或已移除；仅显示本人权限内项目。</p></div></div>
    <Button variant="outline" onClick={onOpenOverview}><ArrowLeft/>返回经营总览</Button>
  </>;
  const readTime = portfolio.asOf && <p className="subtle mb-4">项目资料读取于 <time dateTime={portfolio.asOf}>{new Date(portfolio.asOf).toLocaleString()}</time></p>;
  if (entry) return <>{refresh}{readTime}<SingleCockpit entry={entry} session={session} today={today} onBack={onOpenOverview} onOpenWorkbench={onOpenWorkbench} /></>;
  return <>
    {refresh}{readTime}
    {portfolio.readErrors.map(item => <p key={item.path} role="status" className="subtle">部分范围暂不可读：{item.message}</p>)}
    <Overview portfolio={portfolio} today={today} onOpenProject={onOpenProject} />
  </>;
}
