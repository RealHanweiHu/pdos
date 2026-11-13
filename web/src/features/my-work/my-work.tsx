"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowClockwise, ArrowRight, FolderSimple } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { ExportButton } from "@/features/exports/export-button";
import { exportHref } from "@/features/exports/lib/export-download";
import {
  myOpenItems,
  readPortfolio,
  type MyOpenItem,
  type Portfolio,
} from "@/lib/portfolio-reads";
import type { browserApi } from "@/lib/browser-api";
import { useMyWorkPromises } from "./my-work-promises";
import { usePersonalProjectWork } from "@/features/my-work/lib/personal-project-work";
import { MyWorkList, type WorkGroup, type WorkReading } from "./my-work-list";
import { usePersonalAttention } from "@/features/my-work/lib/personal-attention";
import {
  responsibilityRows,
  commitmentRows,
  receivedRows,
  taskRow,
  sortWorkRows,
} from "@/features/my-work/lib/my-work-items";
import { decideTarget, runTitle, useRunDecisions } from "@/features/my-work/lib/run-decisions";
import { RunDecisions } from "./run-decisions";
import { MyWorkContinue } from "./my-work-continue";
import styles from "./my-work.module.css";
import { HandoverItems } from "./handover-items";

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
  // P35: 承诺 shows 我承诺的 or 别人承诺给我的.
  const [direction, setDirection] = useState<"mine" | "theirs">("mine");
  // B8 deep link: ?area=work&decide=<run>&candidate=<event> preselects one version.
  const [focus, setFocus] = useState<{ runId: string; eventId: string | null } | null>(null);
  useEffect(() => {
    const target = typeof window === "undefined" ? null : decideTarget(window.location.search);
    if (target) void Promise.resolve().then(() => { setFocus(target); setView("active"); });
  }, []);
  const scope = JSON.stringify([session.principal_id, reload]);
  const current = readIdentity?.scope === scope && readIdentity.api === api;
  const portfolio = current ? portfolioResult : null;
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
  const receivedWork = usePersonalProjectWork(
    api,
    session.principal_id,
    reload,
    "received",
  );
  const runDecisions = useRunDecisions(api, session.principal_id, reload);
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
        const next = await readPortfolio(api);
        if (!active) return;
        setPortfolio(next);
        setRecentProjectIds(readRecentProjects(session.principal_id));
        setError("");
        setReadIdentity({ scope, api });
      } catch (failure) {
        if (active) {
          setPortfolio(null);
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
      ? responsibilityRows(attention, taskWork.items, items)
      : view === "commitments"
        ? direction === "mine"
          ? commitmentRows(commitmentWork.items, promises.items)
          : receivedRows(receivedWork.items)
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
            name: "小Pai 运行",
            loading: runDecisions.status === "loading",
            error: runDecisions.error,
            more: false,
            retry: runDecisions.retry,
          },
          {
            name: "项目安排",
            loading: !current,
            error:
              error ||
              portfolio?.readErrors.map((item) => item.message).join("；") ||
              "",
            more: false,
            retry: () => setReload((value) => value + 1),
          },
        ]
      : view === "commitments" && direction === "theirs"
        ? [read("给我的承诺", receivedWork)]
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
  const decisionRuns = runDecisions.page?.runs ?? [];
  // P35 four groups (P75: coordination joins 要我决定), then the person's own tasks.
  const groups: WorkGroup[] | undefined =
    view === "active"
      ? [
          {
            key: "decide",
            label: "要我决定",
            kinds: ["decide"],
            extra: (query) => {
              const shown = decisionRuns.filter((item) =>
                `${runTitle(item.goal)} ${item.category?.name ?? "个人对话"}`
                  .toLocaleLowerCase()
                  .includes(query),
              );
              return shown.length
                ? {
                    count: shown.length,
                    node: (
                      <RunDecisions
                        api={api}
                        runs={shown}
                        focus={focus}
                        truncated={runDecisions.page?.truncated}
                        unavailable={runDecisions.page?.unavailable_runs}
                        onOpenRun={onOpenRun}
                        onChanged={() => setReload((value) => value + 1)}
                      />
                    ),
                  }
                : null;
            },
          },
          { key: "receive", label: "要我接收", kinds: ["receive"] },
          { key: "verify", label: "要我验证", kinds: ["verify"] },
          { key: "external", label: "等外部回复", kinds: ["external"] },
          { key: "mine", label: "我的任务", kinds: ["task", "risk"] },
        ]
      : undefined;

  return (
    <div className={styles.page}>
      <div className="workspace-page-heading">
        <div>
          <h1>我的工作</h1>
          <p>处理产品取舍，继续提案，跟进定义与项目。</p>
        </div><div className="inline-flex items-center gap-1"><ExportButton exportUrl={exportHref("my-work")} label="导出 Excel"/><Button size="icon" variant="ghost" aria-label="刷新我的工作" title="刷新我的工作" onClick={() => { setPortfolio(null); setError(""); setReload(value => value + 1); }}><ArrowClockwise size={15}/></Button></div>
      </div>
      <HandoverItems api={api} principalId={session.principal_id}/>
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
      {focus && runDecisions.status === "ready" && !decisionRuns.some((item) => item.run_id === focus.runId) && (
        <p role="status" className={styles.readNotice}>
          链接中的小Pai 运行已没有待你决定的候选或问题。
        </p>
      )}
      {portfolio?.readErrors.map((item) => (
        <p key={item.path} role="status" className={styles.readNotice}>
          {item.message}
        </p>
      ))}
      {view === "commitments" && (
        <div className={styles.direction} role="group" aria-label="承诺方向">
          {(
            [
              { id: "mine", label: "我承诺的" },
              { id: "theirs", label: "别人承诺给我的" },
            ] as const
          ).map((item) => (
            <button
              type="button"
              key={item.id}
              aria-pressed={direction === item.id}
              onClick={() => setDirection(item.id)}
            >
              {item.label}
            </button>
          ))}
          <span>对谁 · 交付什么 · 何时兑现</span>
        </div>
      )}
      <MyWorkList
        key={`${session.principal_id}:${view}:${direction}`}
        rows={rows}
        readings={readings}
        groups={groups}
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
