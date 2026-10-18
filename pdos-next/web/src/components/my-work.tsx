"use client";

import { useEffect, useState } from "react";
import { ArrowClockwise, ArrowRight, BellRinging, ClipboardText, FolderSimple, Sparkle, Warning } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { dueState, myOpenItems, readPortfolio, readRunActivity, type ActivityRun, type MyOpenItem, type Portfolio } from "@/lib/portfolio-reads";
import type { browserApi } from "@/lib/browser-api";
import { usePersonalProjectWork } from "@/lib/personal-project-work";
import { PersonalProjectWorkQueue } from "./my-work-project-work";
import { PersonalAttention } from "./my-work-attention";

type Api = typeof browserApi;
const runLabels: Record<string, string> = { queued: "已保存，等待执行", running: "正在执行", waiting_input: "运行已暂停，需查看", completed: "已完成", partial: "已形成部分结果", cancelled: "已取消后续执行", failed: "执行未完成" };
const kindLabels: Record<string, string> = { task: "任务", risk: "风险" };

function dueChip(item: { due_date: string | null; status: string }, today: string) {
  const state = dueState(item, today);
  if (state === "overdue") return <span className="workspace-state text-destructive border-destructive">已逾期 · {item.due_date}</span>;
  if (state === "soon") return <span className="workspace-state">临期 · {item.due_date}</span>;
  if (item.due_date) return <span className="workspace-state">{item.due_date}</span>;
  return <span className="workspace-state">无期限</span>;
}

export function MyWork({ api, session, onOpenRun, onOpenProject, onOpenPai }: {
  api: Api; session: { name: string; principal_id: string };
  onOpenRun: (runId: string, categoryId: string) => void;
  onOpenProject: (categoryId: string, projectId: string) => void;
  onOpenPai: () => void;
}) {
  const [portfolioResult, setPortfolio] = useState<Portfolio | null>(null);
  const [runResults, setRuns] = useState<ActivityRun[]>([]);
  const [reload, setReload] = useState(0);
  const [readError, setError] = useState("");
  const scope = JSON.stringify([session.principal_id, reload]);
  const [readIdentity, setReadIdentity] = useState<{ scope: string; api: Api } | null>(null);
  const current = readIdentity?.scope === scope && readIdentity.api === api;
  const portfolio = current ? portfolioResult : null, runs = current ? runResults : [], error = current ? readError : "";
  const taskWork = usePersonalProjectWork(api, session.principal_id, reload, "tasks");
  const commitmentWork = usePersonalProjectWork(api, session.principal_id, reload, "commitments");
  const today = new Date().toISOString().slice(0, 10);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const [next, awaiting] = await Promise.all([readPortfolio(api), readRunActivity(api, true)]);
        const recent = await readRunActivity(api);
        if (!active) return;
        const merged = [...new Map([...awaiting, ...recent].map(run => [run.run_id, run])).values()]
          .sort((a, b) => b.created_at.localeCompare(a.created_at));
        setPortfolio(next);
        setRuns(merged);
        setError("");
        setReadIdentity({ scope, api });
      } catch (failure) { if (active) { setPortfolio(null); setRuns([]); setError((failure as Error).message); setReadIdentity({ scope, api }); } }
    })();
    return () => { active = false; };
  }, [api, scope]);

  const items: MyOpenItem[] = portfolio ? myOpenItems(portfolio, session.principal_id) : [];
  const waiting = runs.filter(run => run.status === "waiting_input");

  return <>
    <div className="workspace-page-heading flex-col sm:flex-row"><div className="min-w-0"><h1>我的工作</h1><p>查看本人可见项目中的未决事项，接续需要答复的工作与最近运行。</p></div><div className="flex flex-wrap gap-2"><Button variant="outline" onClick={() => { setPortfolio(null); setRuns([]); setError(""); setReload(value => value + 1); }}><ArrowClockwise/>刷新</Button><Button variant="outline" onClick={onOpenPai}><Sparkle/>打开小Pai</Button></div></div>
    {error && <p role="alert" className="workspace-read-error">{error}</p>}
    {portfolio?.asOf && <p className="subtle mb-4">项目资料读取于 <time dateTime={portfolio.asOf}>{new Date(portfolio.asOf).toLocaleString()}</time></p>}
    {portfolio?.readErrors.map(item => <p key={item.path} role="status" className="subtle">部分范围暂不可读：{item.message}</p>)}
    <PersonalAttention api={api} principalId={session.principal_id} reload={reload}/>
    <div className="workspace-overview-columns">
      <PersonalProjectWorkQueue queue="tasks" state={taskWork} onOpenProject={onOpenProject}/>
      <PersonalProjectWorkQueue queue="commitments" state={commitmentWork} onOpenProject={onOpenProject}/>
    </div>
    {waiting.length > 0 && <section className="panel mb-6" aria-label="待查看运行">
      <div className="mb-4 flex items-center gap-2"><BellRinging className="text-primary" aria-hidden="true"/><h2 className="font-semibold">运行需关注</h2><span className="subtle ml-auto">{waiting.length} 项</span></div>
      <div className="space-y-3">{waiting.map(run => <div key={run.run_id} className="flex items-center gap-3 border-t border-border pt-3 first:border-0 first:pt-0">
        <div className="min-w-0 flex-1"><p className="break-words">{run.goal}</p><p className="subtle mt-1">{run.categoryName} · <time dateTime={run.created_at}>{new Date(run.created_at).toLocaleString()}</time></p></div>
        <Button size="sm" variant="outline" onClick={() => onOpenRun(run.run_id, run.categoryId)}>查看运行</Button>
      </div>)}</div>
    </section>}
    <div className="workspace-overview-columns">
      <section className="workspace-overview" aria-label="我的未决事项">
        <header><h2>未决事项</h2><span className="subtle">{!portfolio ? error ? "暂不可读" : "读取中" : portfolio.readErrors.length ? "资料未完整读取" : `${items.length} 项`}</span></header>
        {!portfolio && !error && <p className="workspace-list-empty">正在读取未决事项…</p>}
        {portfolio && !portfolio.readErrors.length && items.length === 0 && <p className="workspace-list-empty">当前没有指派给你的未决任务或风险。立项 G0 批准后，处置事项会按负责人出现在这里。</p>}
        {items.map(item => <div className="workspace-record-row" key={item.id}>
          {item.kind === "risk" ? <Warning size={18} aria-hidden="true"/> : <ClipboardText size={18} aria-hidden="true"/>}
          <div className="min-w-0 flex-1">
            <p className="break-words font-medium">{item.title}</p>
            <p className="subtle">{kindLabels[item.kind] ?? item.kind} · {item.projectName}</p>
          </div>
          {dueChip(item, today)}
          <Button size="sm" variant="ghost" onClick={() => onOpenProject(item.categoryId, item.projectId)}>项目驾驶舱<ArrowRight size={14}/></Button>
        </div>)}
      </section>
      <section className="workspace-overview" aria-label="我的运行">
        <header><h2>最近运行</h2><span className="subtle">{portfolio ? `${Math.min(runs.length, 12)} 次` : error ? "暂不可读" : "读取中"}</span></header>
        {!error && portfolio && runs.length === 0 && <p className="workspace-list-empty">暂无运行。打开小Pai 委派第一项工作。</p>}
        {runs.slice(0, 12).map(run => <div className="workspace-record-row" key={run.run_id}>
          <Sparkle size={18} aria-hidden="true"/>
          <div className="min-w-0 flex-1">
            <p className="break-words">{run.goal}</p>
            <p className="subtle mt-1">{runLabels[run.status] ?? run.status} · {run.categoryName} · <time dateTime={run.created_at}>{new Date(run.created_at).toLocaleString()}</time></p>
          </div>
          <Button size="sm" variant="ghost" onClick={() => onOpenRun(run.run_id, run.categoryId)}>查看</Button>
        </div>)}
      </section>
    </div>
    <section className="workspace-overview" aria-label="可见项目">
      <header><h2>可见项目</h2></header>
      {portfolio && !portfolio.readErrors.length && portfolio.projects.length === 0 && <p className="workspace-list-empty">没有可见项目。立项提案经具名 G0 批准后建立项目；也可在产品品类工作区先起草提案。</p>}
      {portfolio?.projects.slice(0, 6).map(entry => <div className="workspace-record-row" key={entry.project.id}>
        <FolderSimple size={18} aria-hidden="true"/>
        <div className="min-w-0 flex-1"><p className="truncate font-medium">{entry.project.name}</p><p className="subtle truncate">{entry.category.name} · {entry.product.name}</p></div>
        <Button size="sm" variant="ghost" onClick={() => onOpenProject(entry.category.id, entry.project.id)}>驾驶舱<ArrowRight size={14}/></Button>
      </div>)}
    </section>
  </>;
}
