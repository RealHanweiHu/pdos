"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowClockwise, ArrowRight, FolderSimple } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import {
  myOpenItems,
  readPortfolio,
  readRunActivity,
  type ActivityRun,
  type MyOpenItem,
  type Portfolio,
} from "@/lib/portfolio-reads";
import type { browserApi } from "@/lib/browser-api";
import { useMyWorkPromises } from "./my-work-promises";
import { usePersonalProjectWork } from "@/lib/personal-project-work";
import { MyWorkList, type WorkReading } from "./my-work-list";
import { usePersonalAttention } from "@/lib/personal-attention";
import {
  responsibilityRows,
  commitmentRows,
  taskRow,
  sortWorkRows,
} from "@/lib/my-work-items";
import { MyWorkContinue } from "./my-work-continue";
import styles from "./my-work.module.css";

type Api = typeof browserApi;
type TaskPeriod = "today" | "week" | "later";

function localDay(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

/** 今日含逾期，本周为今日之后至本周日；未定期限保留在稍后。 */
export function taskPeriod(dueDate: string | null, today: string): TaskPeriod {
  if (!dueDate) return "later";
  if (dueDate <= today) return "today";
  const end = new Date(`${today}T12:00:00`);
  end.setDate(end.getDate() + ((7 - end.getDay()) % 7));
  return dueDate <= localDay(end) ? "week" : "later";
}

function recentStorageKey(principalId: string) {
  return `pdos-next:my-work:recent-projects:${principalId}`;
}
function readRecentProjects(principalId: string): string[] {
  try {
    const value: unknown = JSON.parse(
      localStorage.getItem(recentStorageKey(principalId)) ?? "[]",
    );
    return Array.isArray(value)
      ? value.filter((id): id is string => typeof id === "string").slice(0, 4)
      : [];
  } catch {
    return [];
  }
}

export function MyWork({
  api,
  session,
  onOpenRun,
  onOpenProject,
}: {
  api: Api;
  session: { name: string; principal_id: string };
  onOpenRun: (runId: string, categoryId: string) => void;
  onOpenProject: (categoryId: string, projectId: string) => void;
  onOpenPai: () => void;
}) {
  const [portfolioResult, setPortfolio] = useState<Portfolio | null>(null);
  const [runResults, setRuns] = useState<ActivityRun[]>([]);
  const [recentProjectResults, setRecentProjectIds] = useState<string[]>([]);
  const [reload, setReload] = useState(0);
  const [readError, setError] = useState("");
  const [readIdentity, setReadIdentity] = useState<{
    scope: string;
    api: Api;
  } | null>(null);
  const [view, setView] = useState<"active" | "commitments" | "completed">(
    "active",
  );
  const scope = JSON.stringify([session.principal_id, reload]);
  const current = readIdentity?.scope === scope && readIdentity.api === api;
  const portfolio = current ? portfolioResult : null;
  const runs = current ? runResults : [];
  const recentProjectIds = current ? recentProjectResults : [];
  const error = current ? readError : "";
  const promises = useMyWorkPromises(api, session.principal_id, reload);
  const taskWork = usePersonalProjectWork(
    api,
    session.principal_id,
    reload,
    "tasks",
  );
  const commitmentWork = usePersonalProjectWork(
    api,
    session.principal_id,
    reload,
    "commitments",
  );
  const decide = usePersonalAttention(
    api,
    session.principal_id,
    reload,
    "decide",
  );
  const receive = usePersonalAttention(
    api,
    session.principal_id,
    reload,
    "receive",
  );
  const verify = usePersonalAttention(
    api,
    session.principal_id,
    reload,
    "verify",
  );
  const external = usePersonalAttention(
    api,
    session.principal_id,
    reload,
    "external",
  );

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const [next, awaiting, recent] = await Promise.all([
          readPortfolio(api),
          readRunActivity(api, true),
          readRunActivity(api),
        ]);
        if (!active) return;
        const merged = [
          ...new Map(
            [...awaiting, ...recent].map((run) => [run.run_id, run]),
          ).values(),
        ].sort((a, b) => b.created_at.localeCompare(a.created_at));
        setPortfolio(next);
        setRuns(merged);
        setRecentProjectIds(readRecentProjects(session.principal_id));
        setError("");
        setReadIdentity({ scope, api });
      } catch (failure) {
        if (active) {
          setPortfolio(null);
          setRuns([]);
          setRecentProjectIds([]);
          setError((failure as Error).message);
          setReadIdentity({ scope, api });
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [api, scope, session.principal_id]);

  const items: MyOpenItem[] = portfolio
    ? myOpenItems(portfolio, session.principal_id)
    : [];
  const recentProjects = [
    ...new Map(
      [
        ...recentProjectIds.flatMap(
          (id) =>
            portfolio?.projects.filter((entry) => entry.project.id === id) ??
            [],
        ),
        ...(portfolio?.projects ?? []).filter(
          (entry) => entry.project.owner_id === session.principal_id,
        ),
      ].map((entry) => [entry.project.id, entry]),
    ).values(),
  ].slice(0, 4);
  const openProject = (categoryId: string, projectId: string) => {
    const ids = [
      projectId,
      ...readRecentProjects(session.principal_id).filter(
        (id) => id !== projectId,
      ),
    ].slice(0, 4);
    try {
      localStorage.setItem(
        recentStorageKey(session.principal_id),
        JSON.stringify(ids),
      );
    } catch {
      /* Optional navigation preference. */
    }
    onOpenProject(categoryId, projectId);
  };
  const attention = [
    ...decide.items,
    ...receive.items,
    ...verify.items,
    ...external.items,
  ];
  const read = (
    name: string,
    state: Omit<typeof taskWork, "items">,
  ): WorkReading => ({
    name,
    loading: state.status === "loading",
    error: state.error,
    moreError: state.moreError,
    more: !!state.nextCursor,
    busy: state.loadingMore,
    retry: state.retry,
    loadMore: state.loadMore,
  });
  const rows =
    view === "active"
      ? responsibilityRows(attention, taskWork.items, items, runs)
      : view === "commitments"
        ? commitmentRows(commitmentWork.items, promises.items)
        : sortWorkRows(
            taskWork.items
              .filter((item) => item.task.state === "completed")
              .map(taskRow),
          );
  const readings: WorkReading[] =
    view === "active"
      ? [
          read("待决定", decide),
          read("待接收", receive),
          read("待验证", verify),
          read("等外部", external),
          read("项目任务", taskWork),
          {
            name: "项目安排与小Pai",
            loading: !current,
            error:
              error ||
              portfolio?.readErrors.map((item) => item.message).join("；") ||
              "",
            more: false,
            retry: () => setReload((value) => value + 1),
          },
        ]
      : view === "commitments"
        ? [
            read("交付承诺", commitmentWork),
            {
              name: "开测承诺",
              loading: promises.totalRecords === null && !promises.error,
              error: promises.error,
              more: !!promises.nextCursor,
              busy: promises.loadingMore,
              retry: promises.refresh,
              loadMore: promises.loadMore,
            },
          ]
        : [read("已完成任务", taskWork)];

  return (
    <div className={styles.page}>
      <div className="workspace-page-heading">
        <div>
          <h1>我的工作</h1>
          <p>处理产品取舍，继续提案，跟进定义与项目。</p>
        </div><Button size="icon" variant="ghost" aria-label="刷新我的工作" title="刷新我的工作" onClick={() => { setPortfolio(null); setRuns([]); setError(""); setReload(value => value + 1); }}><ArrowClockwise size={15}/></Button>
      </div>
      <nav className="workspace-view-tabs" aria-label="我的工作视图">
        {(
          [
            { id: "active", label: "待我处理" },
            { id: "commitments", label: "承诺" },
            { id: "completed", label: "已完成" },
          ] as const
        ).map((item) => (
          <button
            type="button"
            key={item.id}
            aria-pressed={view === item.id}
            onClick={() => setView(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>
      {error && (
        <p role="alert" className="workspace-read-error">
          {error}
        </p>
      )}
      {portfolio?.readErrors.map((item) => (
        <p key={item.path} role="status" className={styles.readNotice}>
          {item.message}
        </p>
      ))}
      <MyWorkList
        key={`${session.principal_id}:${view}`}
        rows={rows}
        readings={readings}
        onOpenProject={openProject}
        onOpenRun={onOpenRun}
      />
      {view === "active" && (
        <MyWorkContinue
          api={api}
          principalId={session.principal_id}
          reload={reload}
        />
      )}
      {view === "active" && <section className={styles.continueSection} aria-label="继续项目"><div className={styles.sectionHeading}><h2>继续项目</h2><Link href="/?area=projects" className={styles.meta}>全部项目<ArrowRight size={12}/></Link></div>{recentProjects.map(entry => <button type="button" key={entry.project.id} className={styles.continueProject} onClick={() => openProject(entry.category.id,entry.project.id)}><FolderSimple size={16}/><strong>{entry.project.name}</strong><span>{entry.category.name}</span><ArrowRight size={14}/></button>)}{!recentProjects.length && <p className={styles.queueNote}>{portfolio ? "暂无你负责的项目" : "正在读取项目…"}</p>}</section>}
      {portfolio?.asOf && (
        <p className={styles.asOf}>
          资料读取于{" "}
          <time dateTime={portfolio.asOf}>
            {new Date(portfolio.asOf).toLocaleString()}
          </time>
        </p>
      )}
    </div>
  );
}
