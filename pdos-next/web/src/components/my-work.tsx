"use client";

import { useEffect, useState } from "react";
import { ArrowClockwise, ArrowRight, CaretDown, Circle, Clock, FolderSimple, Tray, Sparkle, Warning } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { myOpenItems, readPortfolio, readRunActivity, type ActivityRun, type MyOpenItem, type Portfolio } from "@/lib/portfolio-reads";
import type { browserApi } from "@/lib/browser-api";
import { MyWorkPromises, useMyWorkPromises } from "./my-work-promises";
import { usePersonalProjectWork } from "@/lib/personal-project-work";
import { PersonalProjectWorkQueue } from "./my-work-project-work";
import { PersonalAttention } from "./my-work-attention";
import styles from "./my-work.module.css";

type Api = typeof browserApi;
type TaskPeriod = "today" | "week" | "later";
const runLabels: Record<string, string> = { queued: "已保存，等待执行", running: "正在执行", waiting_input: "运行已暂停，需查看", completed: "已完成", partial: "已形成部分结果", cancelled: "已取消后续执行", failed: "执行未完成" };
const taskPeriods: { id: TaskPeriod; label: string }[] = [{ id: "today", label: "今日" }, { id: "week", label: "本周" }, { id: "later", label: "稍后" }];

function localDay(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

/** 今日含逾期，本周为今日之后至本周日；未定期限保留在稍后。 */
export function taskPeriod(dueDate: string | null, today: string): TaskPeriod {
  if (!dueDate) return "later";
  if (dueDate <= today) return "today";
  const end = new Date(`${today}T12:00:00`);
  end.setDate(end.getDate() + (7 - end.getDay()) % 7);
  return dueDate <= localDay(end) ? "week" : "later";
}

function dueLabel(dueDate: string | null, today: string) {
  if (!dueDate) return "未定期限";
  if (dueDate < today) return `已逾期 · ${dueDate.slice(5)}`;
  return dueDate === today ? "今日" : dueDate.slice(5);
}

function recentStorageKey(principalId: string) { return `pdos-next:my-work:recent-projects:${principalId}`; }
function readRecentProjects(principalId: string): string[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(recentStorageKey(principalId)) ?? "[]");
    return Array.isArray(value) ? value.filter((id): id is string => typeof id === "string").slice(0, 4) : [];
  } catch { return []; }
}

export function MyWork({ api, session, onOpenRun, onOpenProject, onOpenPai }: {
  api: Api; session: { name: string; principal_id: string };
  onOpenRun: (runId: string, categoryId: string) => void;
  onOpenProject: (categoryId: string, projectId: string) => void;
  onOpenPai: () => void;
}) {
  const [portfolioResult, setPortfolio] = useState<Portfolio | null>(null);
  const [runResults, setRuns] = useState<ActivityRun[]>([]);
  const [recentProjectResults, setRecentProjectIds] = useState<string[]>([]);
  const [reload, setReload] = useState(0);
  const [readError, setError] = useState("");
  const [readIdentity, setReadIdentity] = useState<{ scope: string; api: Api } | null>(null);
  const [triage, setTriage] = useState<"all" | "pai" | "risk">("all");
  const [taskFilter, setTaskFilter] = useState<"all" | TaskPeriod>("all");
  const [collapsed, setCollapsed] = useState<TaskPeriod[]>([]);
  const today = localDay(new Date());
  const scope = JSON.stringify([session.principal_id, reload]);
  const current = readIdentity?.scope === scope && readIdentity.api === api;
  const portfolio = current ? portfolioResult : null;
  const runs = current ? runResults : [];
  const recentProjectIds = current ? recentProjectResults : [];
  const error = current ? readError : "";
  const promises = useMyWorkPromises(api, session.principal_id, reload);
  const taskWork = usePersonalProjectWork(api, session.principal_id, reload, "tasks");
  const commitmentWork = usePersonalProjectWork(api, session.principal_id, reload, "commitments");

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const [next, awaiting, recent] = await Promise.all([readPortfolio(api), readRunActivity(api, true), readRunActivity(api)]);
        if (!active) return;
        const merged = [...new Map([...awaiting, ...recent].map(run => [run.run_id, run])).values()]
          .sort((a, b) => b.created_at.localeCompare(a.created_at));
        setPortfolio(next);
        setRuns(merged);
        setRecentProjectIds(readRecentProjects(session.principal_id));
        setError("");
        setReadIdentity({ scope, api });
      } catch (failure) { if (active) { setPortfolio(null); setRuns([]); setRecentProjectIds([]); setError((failure as Error).message); setReadIdentity({ scope, api }); } }
    })();
    return () => { active = false; };
  }, [api, scope, session.principal_id]);

  const items: MyOpenItem[] = portfolio ? myOpenItems(portfolio, session.principal_id) : [];
  const tasks = items.filter(item => item.kind === "task");
  const risks = items.filter(item => item.kind !== "task");
  const waiting = runs.filter(run => run.status === "waiting_input");
  const activity = runs.filter(run => run.status !== "waiting_input").slice(0, 12);
  const recentProjects = recentProjectIds.flatMap(id => portfolio?.projects.filter(entry => entry.project.id === id) ?? []);
  const count = (value: number) => portfolio && !portfolio.readErrors.length ? value : "—";
  const workCountKnown = portfolio !== null && portfolio.readErrors.length === 0;
  const workCount = waiting.length + risks.length;
  const totalCount = workCountKnown ? workCount : "—";
  const openProject = (categoryId: string, projectId: string) => {
    const ids = [projectId, ...readRecentProjects(session.principal_id).filter(id => id !== projectId)].slice(0, 4);
    try { localStorage.setItem(recentStorageKey(session.principal_id), JSON.stringify(ids)); } catch { /* Optional navigation preference. */ }
    onOpenProject(categoryId, projectId);
  };
  const emptyText = !portfolio ? error ? "资料暂不可读，请刷新重试。" : "正在读取…" : portfolio.readErrors.length ? "部分项目资料暂不可读，当前列表可能不完整。" : "";

  return <div className={styles.page}>
    <h1 className="sr-only">我的工作</h1>
    <div className={styles.quickbar}>
      <nav className={styles.recents} aria-label="最近访问的项目">
        <span className={styles.meta}>最近访问</span>
        {recentProjects.map(entry => <button type="button" className={styles.chip} key={entry.project.id} onClick={() => openProject(entry.category.id, entry.project.id)}><FolderSimple size={12} aria-hidden="true"/>{entry.project.name}</button>)}
        {recentProjects.length === 0 && <span className={styles.meta}>{portfolio ? "从下方打开项目后显示在这里" : "—"}</span>}
      </nav>
      <div className={styles.tools}>
        <Button size="xs" variant="ghost" onClick={() => { setPortfolio(null); setRuns([]); setError(""); setReload(value => value + 1); }}><ArrowClockwise aria-hidden="true"/>刷新</Button>
        <Button size="xs" variant="outline" onClick={onOpenPai}><Sparkle aria-hidden="true"/>打开小Pai</Button>
      </div>
    </div>
    {error && <p role="alert" className="workspace-read-error">{error}</p>}
    {portfolio?.readErrors.map(item => <p key={item.path} role="status" className={styles.readNotice}>{item.message}</p>)}
    <div className={styles.grid}>
      <div className={styles.main}>
        <PersonalAttention api={api} principalId={session.principal_id} reload={reload}/>
        <section aria-label="运行与项目风险">
          <div className={styles.sectionHeading}><h2>运行与项目风险</h2><span className={styles.meta}>查看暂停的运行与本人负责的项目风险</span></div>
          <div className={styles.triage} aria-label="办理类型">
            <button type="button" className={styles.chip} aria-pressed={triage === "all"} onClick={() => setTriage("all")}>全部 <b>{totalCount}</b></button>
            <button type="button" className={styles.chip} aria-pressed={triage === "pai"} onClick={() => setTriage("pai")}>暂停的运行 <b>{count(waiting.length)}</b></button>
            <button type="button" className={styles.chip} aria-pressed={triage === "risk"} onClick={() => setTriage("risk")}>风险 <b>{count(risks.length)}</b></button>
          </div>
          <div className={styles.cards}>
            {(triage === "all" || triage === "pai") && waiting.map(run => <article className={styles.workcard} key={run.run_id}>
              <div className={styles.cardTop}><h3>{run.goal}</h3><span className={styles.pending}>需查看</span></div>
              <p className={styles.cardWhy}>运行已暂停，请查看缺项、配置或对账状态。</p>
              <div className={styles.cardMeta}><span className={styles.agentTag}><Sparkle size={12} aria-hidden="true"/>小Pai</span><span>{run.categoryName}</span><time dateTime={run.created_at}>{new Date(run.created_at).toLocaleString()}</time></div>
              <div className={styles.cardActions}><Button variant="outline" size="xs" onClick={() => onOpenRun(run.run_id, run.categoryId)}>查看运行<ArrowRight aria-hidden="true"/></Button></div>
            </article>)}
            {(triage === "all" || triage === "risk") && risks.map(item => <article className={styles.workcard} key={item.id}>
              <div className={styles.cardTop}><h3>{item.title}</h3><span className={styles.riskBadge}><Warning size={12} aria-hidden="true"/>{item.kind === "risk" ? "风险" : "待处置"}</span></div>
              <div className={styles.cardMeta}><span>{item.projectName}</span><span>{session.name}</span><span className={item.due_date && item.due_date <= today ? styles.hot : undefined}>{dueLabel(item.due_date, today)}</span></div>
              <div className={styles.cardActions}><Button variant="outline" size="xs" onClick={() => openProject(item.categoryId, item.projectId)}>进入项目处置<ArrowRight aria-hidden="true"/></Button></div>
            </article>)}
            {["all", "pai", "risk"].includes(triage) && (emptyText || (triage === "all" ? waiting.length + risks.length === 0 : triage === "pai" ? waiting.length === 0 : risks.length === 0)) && <div className={styles.emptyCard}>{emptyText || (triage === "pai" ? "当前没有暂停的小Pai运行。" : triage === "risk" ? "当前没有指派给你的未决风险。" : "当前没有暂停的运行或待处置风险。")}</div>}
          </div>
          <p className={styles.queueNote}>注意项由上方四类队列按原记录汇总；此处保留运行状态与项目风险。</p>
        </section>

        <PersonalProjectWorkQueue queue="tasks" state={taskWork} onOpenProject={openProject}/>
        <section aria-label="我的任务">
          <div className={styles.sectionHeading}><h2>我的任务</h2><span className={styles.meta}>关联项目的任务，进入项目办理</span></div>
          <div className={styles.taskFilters} aria-label="任务期限筛选">
            <button type="button" className={styles.chip} aria-pressed={taskFilter === "all"} onClick={() => setTaskFilter("all")}>全部 <b>{count(tasks.length)}</b></button>
            {taskPeriods.map(period => <button type="button" key={period.id} className={styles.chip} aria-pressed={taskFilter === period.id} onClick={() => setTaskFilter(period.id)}>{period.label}</button>)}
          </div>
          <div className={styles.panel}>
            {emptyText && <p className={styles.empty}>{emptyText}</p>}
            {taskPeriods.filter(period => taskFilter === "all" || taskFilter === period.id).map(period => {
              const group = tasks.filter(task => taskPeriod(task.due_date, today) === period.id);
              const closed = collapsed.includes(period.id);
              return <div key={period.id}>
                <button type="button" className={styles.groupHeading} aria-expanded={!closed} aria-controls={`my-work-tasks-${period.id}`} onClick={() => setCollapsed(old => closed ? old.filter(id => id !== period.id) : [...old, period.id])}><CaretDown size={12} aria-hidden="true"/>{period.label}{period.id === "today" && <span className={styles.groupHint}>含逾期</span>}<span className={styles.groupCount}>{count(group.length)}</span></button>
                <div id={`my-work-tasks-${period.id}`} hidden={closed}>
                  {group.map(item => <div className={styles.taskRow} key={item.id}>
                    <Circle size={16} className={styles.taskCircle} aria-hidden="true"/>
                    <button type="button" className={styles.taskTitle} onClick={() => openProject(item.categoryId, item.projectId)}>{item.title}</button>
                    <span className={styles.taskObject} title={item.projectName}>{item.projectName}</span>
                    <span className={`${styles.taskDue}${item.due_date && item.due_date <= today ? ` ${styles.hot}` : ""}`}>{dueLabel(item.due_date, today)}</span>
                  </div>)}
                  {portfolio && !portfolio.readErrors.length && group.length === 0 && <p className={styles.groupEmpty}>暂无{period.label}任务</p>}
                </div>
              </div>;
            })}
          </div>
        </section>
      </div>

      <aside className={styles.aside} aria-label="通知与项目快捷访问">
        <section className={styles.panel} aria-label="通知与运行动态">
          <header className={styles.panelHeading}><Tray size={15} aria-hidden="true"/><h2>通知</h2><span className={styles.panelTail}>小Pai 运行动态</span></header>
          {emptyText && <p className={styles.empty}>{emptyText}</p>}
          {portfolio && activity.length === 0 && <p className={styles.empty}>暂无其他运行动态。待答复事项在左侧办理。</p>}
          {activity.map(run => <button type="button" className={styles.activityRow} key={run.run_id} onClick={() => onOpenRun(run.run_id, run.categoryId)}>
            <span className={styles.activityBody}><span className={styles.activityGoal}>{run.goal}</span><span className={styles.activityMeta}><span className={styles.agentTag}><Sparkle size={11} aria-hidden="true"/>小Pai</span><span>{runLabels[run.status] ?? run.status}</span></span><span className={styles.activityScope}>{run.categoryName}</span></span>
            <time className={styles.activityTime} dateTime={run.created_at}>{localDay(new Date(run.created_at)) === today ? new Date(run.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : new Date(run.created_at).toLocaleDateString([], { month: "2-digit", day: "2-digit" })}</time>
          </button>)}
        </section>
        <PersonalProjectWorkQueue queue="commitments" state={commitmentWork} onOpenProject={openProject}/>
        <section className={styles.panel} aria-label="承诺与外部等待">
          <header className={styles.panelHeading}><Clock size={15} aria-hidden="true"/><h2>承诺与外部等待</h2><span className={styles.panelTail}>已接测试记录</span></header>
          <MyWorkPromises queue={promises}/>
        </section>
        <section className={styles.panel} aria-label="项目快捷访问">
          <header className={styles.panelHeading}><FolderSimple size={15} aria-hidden="true"/><h2>项目快捷访问</h2><span className={styles.panelTail}>本人可见</span></header>
          {emptyText && <p className={styles.empty}>{emptyText}</p>}
          {portfolio?.projects.slice(0, 4).map(entry => <button type="button" className={styles.projectLink} key={entry.project.id} onClick={() => openProject(entry.category.id, entry.project.id)}><span><strong>{entry.project.name}</strong><span>{entry.category.name} · {entry.product.name}</span></span><ArrowRight size={13} aria-hidden="true"/></button>)}
          {portfolio && !portfolio.readErrors.length && portfolio.projects.length === 0 && <p className={styles.empty}>当前没有可见项目。</p>}
        </section>
      </aside>
    </div>
    {portfolio?.asOf && <p className={styles.asOf}>资料读取于 <time dateTime={portfolio.asOf}>{new Date(portfolio.asOf).toLocaleString()}</time></p>}
  </div>;
}
