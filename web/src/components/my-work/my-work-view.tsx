"use client";

import dynamic from "next/dynamic";
import { DeferredPanelLoading, withDeferredPanelBoundary } from "@/components/deferred-panel-loading";





import {
  ArrowSquareOutIcon,
  BellRingingIcon,
  CheckFatIcon,
  ClipboardTextIcon,
  FlagIcon,
  ShieldCheckIcon,
  TrayIcon,
  WarningCircleIcon,
  WrenchIcon,
} from "@phosphor-icons/react";
import Link from "next/link";
import { useState, type ComponentType, type ReactNode } from "react";

import { FindingReviewUndo } from "@/components/ai/finding-review-undo";
import { FindingBatchReview } from "@/components/ai/finding-batch-review";
import { ConversationFinding } from "@/components/ai/conversation-finding";
import { FindingAppliedReceipt } from "@/components/ai/finding-proposal";
import type { AiFinding } from "@/components/ai/ai-types";
import { WorkPriorityIndex, workCardAnchor } from "./work-priority-index";
import { WorkCardConversation } from "./work-card-conversation";








import type { MyWorkCostFreeze, MyWorkIdDesign, MyWorkChangeExecution, MyWorkRiskFollowup, MyWorkTaskTakeover } from "./my-work-types";
import { PreProjectWork } from "@/components/product-work/preproject-work";
import { WorkSearch } from "./work-search";
import { workDate } from "./work-dates";
import { ReminderPreferences } from "./reminder-preferences";
import { useMyWorkQueue } from "./use-my-work-queue";

import { Button } from "@/components/ui/button";
import { WorkspaceShell } from "@/components/workspace-shell";
import type { WorkspaceIdentity } from "@/components/workspace-types";
import { cn } from "@/lib/utils";

import type { MyNotifications, MyWork, MyWorkCollection } from "./my-work-types";

const TaskTakeover = withDeferredPanelBoundary(dynamic(() => import("./task-takeover").then(module => module.TaskTakeover), { loading: DeferredPanelLoading }));
const RiskFollowupWork = withDeferredPanelBoundary(dynamic(() => import("./risk-followup-work").then(module => module.RiskFollowupWork), { loading: DeferredPanelLoading }));
const CapaWorkCard = withDeferredPanelBoundary(dynamic(() => import("./capa-work-card").then(module => module.CapaWorkCard), { loading: DeferredPanelLoading }));
const GateSignoffWorkCard = withDeferredPanelBoundary(dynamic(() => import("./gate-signoff-work-card").then(module => module.GateSignoffWorkCard), { loading: DeferredPanelLoading }));
const IssueRiskWorkCard = withDeferredPanelBoundary(dynamic(() => import("./issue-risk-work-card").then(module => module.IssueRiskWorkCard), { loading: DeferredPanelLoading }));
const ChangeExecutionResults = withDeferredPanelBoundary(dynamic(() => import("@/components/projects/change-execution-results").then(module => module.ChangeExecutionResults), { loading: DeferredPanelLoading }));
const MyWorkIdDesignAction = withDeferredPanelBoundary(dynamic(() => import("./my-work-id-design").then(module => module.MyWorkIdDesignAction), { loading: DeferredPanelLoading }));
const CostFreezes = withDeferredPanelBoundary(dynamic(() => import("@/components/projects/cost-freezes").then(module => module.CostFreezes), { loading: DeferredPanelLoading }));
const ProjectCrossDependencies = withDeferredPanelBoundary(dynamic(() => import("@/components/projects/project-cross-dependencies").then(module => module.ProjectCrossDependencies), { loading: DeferredPanelLoading }));

const MyWorkDiscussion = withDeferredPanelBoundary(dynamic(() => import("./my-work-discussion").then(module => module.MyWorkDiscussion), { loading: DeferredPanelLoading }));
const TaskPreparation = withDeferredPanelBoundary(dynamic(() => import("./task-preparation").then(module => module.TaskPreparation), { loading: DeferredPanelLoading }));

const statusLabels: Record<string, string> = {
  todo: "待开始",
  in_progress: "进行中",
  blocked: "已阻塞",
  pending_approval: "待批准",
  open: "待处理",
  analysis: "分析中",
  action: "行动中",
  verification: "待验证",
  mitigating: "缓解中",
  watching: "观察中",
  planned: "已计划",
  pending_review: "待人审",
  accepted: "待应用",
};

const severityLabels: Record<string, string> = {
  low: "低",
  medium: "中",
  high: "高",
  critical: "严重",
};

const slotLabels: Record<string, string> = {
  product: "产品",
  engineering: "工程",
  quality: "质量",
};

const capaTypeLabels: Record<string, string> = { corrective: "纠正", preventive: "预防" };

function label(map: Record<string, string>, value: string) {
  return map[value] ?? value;
}

const dateFormatter = new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", month: "short", day: "numeric" });

function formatDate(value: string | null) {
  if (!value) return null;
  return dateFormatter.format(new Date(value));
}

function isOverdue(value: string | null, today: string) {
  return value !== null && workDate(value) < today;
}

function DueBadge({ due, today }: { due: string | null; today: string }) {
  if (!due) return <span className="text-[11px] text-muted-foreground">无日期</span>;
  const overdue = isOverdue(due, today);
  return (
    <span
      className={cn(
        "rounded-full border px-2 py-0.5 text-[10px] font-semibold",
        overdue
          ? "border-destructive/30 bg-destructive/10 text-destructive"
          : "border-border bg-muted text-muted-foreground",
      )}
    >
      {overdue ? "逾期 " : ""}
      {formatDate(due)}
    </span>
  );
}

function Section({
  onLoadMore,
  onRefresh,
  loading,
  disabled,
  count,
  icon: Icon,
  items,
  title,
}: {
  onLoadMore?: () => void;
  onRefresh?: () => void;
  loading?: boolean;
  disabled?: boolean;
  count: number;
  icon: ComponentType<{ className?: string; "aria-hidden"?: boolean | "true" }>;
  items: ReactNode[];
  title: string;
}) {
  if (count === 0) return null;
  return (
    <section aria-label={title} className="overflow-hidden rounded-lg border bg-card">
      <header className="flex items-center gap-2 border-b px-4 py-3">
        <Icon aria-hidden className="size-4 text-primary" />
        <h2 className="font-semibold">{title}</h2>
        <span className="ml-auto font-mono text-xs text-muted-foreground">{count}</span>
      </header>
      <ol className="divide-y" role="list">
        {items}
      </ol>
      {(items.length < count || onRefresh) && <div className="flex flex-wrap items-center gap-2 border-t bg-muted/20 px-4 py-2 text-xs text-muted-foreground" aria-busy={loading}>
        <span>共 {count} 条，已加载 {items.length} 条。</span>
        {onLoadMore && <Button size="sm" variant="outline" disabled={disabled} onClick={onLoadMore}>{loading ? "正在读取…" : "继续加载"}</Button>}
        {onRefresh && <Button size="sm" variant="ghost" disabled={disabled} onClick={onRefresh}>刷新本类工作</Button>}
      </div>}
    </section>
  );
}

function Row({
  id,
  badges,
  children,
  href,
  project,
  title,
}: {
  id: string;
  badges: ReactNode;
  children?: ReactNode;
  href: string;
  project: { code: string };
  title: string;
}) {
  return (
    <li id={id} className="scroll-mt-6">
      <Link
        className="flex min-h-11 flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-inset focus-visible:ring-ring/25"
        href={href}
      >
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{title}</span>
        <span className="rounded-lg bg-accent px-2 py-0.5 font-mono text-[10px] font-semibold text-accent-foreground">
          {project.code}
        </span>
        {badges}
        <ArrowSquareOutIcon aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
      </Link>
      {children}
    </li>
  );
}

function StatusBadge({ value }: { value: string }) {
  return (
    <span className="rounded-full border border-border bg-muted px-2 py-0.5 text-[10px] font-semibold text-muted-foreground">
      {label(statusLabels, value)}
    </span>
  );
}

export function MyWorkView({
  identity,
  loggingOut,
  notifications,
  notificationState,
  onAcknowledge,
  onRetryNotifications,
  onLogout,
  today,
  work: initialWork,
}: {
  identity: WorkspaceIdentity;
  loggingOut: boolean;
  notifications: MyNotifications | null;
  notificationState: "loading" | "ready" | "error";
  onAcknowledge: (notificationId: string) => void;
  onRetryNotifications: () => void;
  onLogout: () => void;
  today: string;
  work: MyWork;
}) {
  const [findingReceipt, setFindingReceipt] = useState<AiFinding | null>(null);
  const [taskNotice, setTaskNotice] = useState<string | null>(null);
  const queue = useMyWorkQueue(initialWork);
  const work = queue.work;
  const [discussionFocus, setDiscussionFocus] = useState<{ projectId: string; runId: string } | null>(null);
  const [executionFocus,setExecutionFocus]=useState<MyWorkChangeExecution|null>(null);
  const [costFreezeFocus, setCostFreezeFocus] = useState<MyWorkCostFreeze | null>(null);
  const [takeoverFocus, setTakeoverFocus] = useState<MyWorkTaskTakeover | null>(null);
  const [riskResultFocus, setRiskResultFocus] = useState<MyWorkRiskFollowup | null>(null);
  const [idFocus, setIdFocus] = useState<MyWorkIdDesign | null>(null);
  async function refreshIdWork() { await queue.refresh(); }
  function paging(name: MyWorkCollection) {
    return {
      onLoadMore: queue.work.pages?.[name]?.next_offset != null ? () => void queue.loadMore(name) : undefined,
      onRefresh: () => void queue.refresh(name),
      loading: queue.busy === name,
      disabled: queue.busy !== null,
    };
  }
  const [notificationsExpanded, setNotificationsExpanded] = useState(false);
  const [crossFocus, setCrossFocus] = useState<{ projectId: string; proposalId: string } | null>(null);
  const counts = work.counts;
  const crossCount = (counts.cross_schedule_approvals ?? 0);
  const firedNotifications = notifications?.items.filter((notification) => notification.status === "fired") ?? [];
  const actionable =
    counts.tasks + counts.issues + counts.risks + counts.capa_actions + counts.gate_signoffs + crossCount + (counts.id_design_actions ?? 0) + (counts.change_execution_confirmations ?? 0) + (counts.risk_followup_actions ?? 0) + (counts.task_takeover_actions ?? 0) + (counts.cost_freeze_approvals ?? 0);
  const isPortfolioRole = ["owner", "admin", "project_manager"].includes(identity.user.role);

  return (
    <WorkspaceShell active="my-work" identity={identity} loggingOut={loggingOut} onLogout={onLogout}>
      <div className="flex flex-wrap items-end justify-between gap-4 border-b pb-4">
        <div>
          <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-primary">
            My Work
          </p>
          <h1 className="mt-1 text-lg font-semibold" data-testid="my-work-ready">今天由我负责什么</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            聚合分派给 {identity.user.display_name} 的项目执行与立项前工作、待验证及待签核事项。
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Button variant="outline" disabled={queue.busy !== null} onClick={() => void queue.refresh()}>{queue.busy === "refresh" ? "正在刷新…" : "刷新待办"}</Button>
          {isPortfolioRole ? (
            <Link className="inline-flex min-h-11 items-center text-sm font-medium text-primary" href="/">
              切换到组合视图
            </Link>
          ) : null}
          <dl className="flex overflow-hidden rounded-lg border bg-card text-center">
            <div className="min-w-24 px-3 py-2">
              <dt className="text-[10px] text-muted-foreground">项目待办</dt>
              <dd className="mt-0.5 font-mono text-base font-semibold">{actionable}</dd>
            </div>
            <div className="min-w-24 border-l px-3 py-2">
              <dt className="text-[10px] text-muted-foreground">AI 待办理</dt>
              <dd className="mt-0.5 font-mono text-base font-semibold">{counts.findings}</dd>
            </div>
          </dl>
        </div>
      </div>
      <WorkSearch today={today} handoffs={work.id_design_actions ?? []} onChanged={refreshIdWork}/>
      {actionable + counts.findings > 0 && <WorkPriorityIndex today={today} work={work}/>}
      <PreProjectWork />
      {findingReceipt && ["accepted", "rejected"].includes(findingReceipt.status) && <FindingReviewUndo key={findingReceipt.updated_at} items={[findingReceipt]} onRecorded={result => { setFindingReceipt(result.items[0] ?? null); setTaskNotice("已记录撤销裁决，正在刷新当前待办。"); void refreshIdWork(); }}/>}
      {findingReceipt?.status === "applied" && <div className="mt-3"><FindingAppliedReceipt finding={findingReceipt}/></div>}
      {taskNotice && <p role="status" className="mt-3 rounded-md border bg-muted/20 p-3 text-sm">{taskNotice}</p>}

      <FindingBatchReview projectNames={new Map([...work.tasks, ...work.issues, ...work.findings].map(item => [item.project.id, item.project.name]))} onRecorded={() => void refreshIdWork()}/>
      <ReminderPreferences/>
      {costFreezeFocus && <section className="space-y-2 rounded-md border p-3" aria-label="成本冻结待办办理"><div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">成本冻结待批 · {costFreezeFocus.title}</h2><Button type="button" size="sm" variant="ghost" onClick={() => setCostFreezeFocus(null)}>关闭办理</Button></div><CostFreezes key={costFreezeFocus.id} canEdit calculation={null} initialRequestId={costFreezeFocus.id} projectId={costFreezeFocus.project.id} onChanged={() => void queue.refresh()}/></section>}
      {takeoverFocus && <section className="space-y-2 rounded-md border p-3" aria-label="任务交接待办办理"><div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">{takeoverFocus.mode === "review" ? "交接待本人接收" : "交接待补齐"} · {takeoverFocus.title}</h2><Button type="button" size="sm" variant="ghost" onClick={() => setTakeoverFocus(null)}>关闭办理</Button></div><Link className="text-sm text-primary underline" href={`/projects?project=${takeoverFocus.project.id}&tab=work-items&entity_id=${takeoverFocus.task_id}`}>打开原任务与接手资料</Link><TaskTakeover key={takeoverFocus.task_id} initiallyOpen projectId={takeoverFocus.project.id} taskId={takeoverFocus.task_id} onChanged={() => void queue.refresh()}/></section>}
      {riskResultFocus && <RiskFollowupWork key={riskResultFocus.task_id} item={riskResultFocus} onClose={() => setRiskResultFocus(null)} onRecorded={() => void queue.refresh()}/>}
      {notificationState === "loading" ? <p className="mt-4 text-sm text-muted-foreground" aria-busy="true">正在加载站内通知…</p> : null}
      {notificationState === "error" ? (
        <section aria-label="通知加载状态" className="mt-4 rounded-lg border border-destructive/30 p-4" role="alert">
          <p className="text-sm text-destructive">站内通知暂不可用，个人待办仍可处理。</p>
          <Button className="mt-2" onClick={onRetryNotifications} variant="outline">重新加载通知</Button>
        </section>
      ) : null}
      {notificationState === "ready" && notifications && notifications.unread_count > 0 ? (
        <section aria-label="站内通知" className="mt-5 overflow-hidden rounded-lg border border-pending/30 bg-card">
          <header className="flex items-center gap-2 border-b bg-pending/5 px-4 py-3">
            <BellRingingIcon aria-hidden className="size-4 text-pending" />
            <h2 className="font-semibold">通知</h2>
            <span className="rounded-full bg-pending/15 px-2 py-0.5 font-mono text-xs font-semibold text-pending">
              未读 {notifications.unread_count}
            </span>
            <Button aria-expanded={notificationsExpanded} className="ml-auto" onClick={() => setNotificationsExpanded((current) => !current)} variant="outline">
              {notificationsExpanded ? "收起通知" : "展开通知"}
            </Button>
          </header>
          {notificationsExpanded ? <>
          <ol className="max-h-80 divide-y overflow-y-auto" role="list">
            {firedNotifications.map((notification) => (
                <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5" key={notification.id}>
                  <span className="min-w-0 flex-1 truncate text-sm">{notification.title}</span>
                  {notification.target_entity === "meeting" && <a className="text-sm text-primary underline" href={`/projects?project=${notification.project.id}&tab=decisions&meeting=${notification.target_entity_id}`}>查看会议当前安排</a>}
                  {notification.target_entity === "change_discussion" && <Button type="button" size="sm" variant="outline" onClick={() => setDiscussionFocus({ projectId: notification.project.id, runId: notification.target_entity_id })}>查看讨论与摘要</Button>}
                  <span className="rounded-lg bg-accent px-2 py-0.5 font-mono text-[10px] font-semibold text-accent-foreground">
                    {notification.project.code}
                  </span>
                  {notification.escalation_level > 0 ? (
                    <span className="rounded-full border border-destructive/30 bg-destructive/10 px-2 py-0.5 text-[10px] font-semibold text-destructive">
                      升级
                    </span>
                  ) : null}
                  <Button
                    className="h-11 sm:h-7"
                    onClick={() => onAcknowledge(notification.id)}
                    variant="outline"
                  >
                    知道了
                  </Button>
                </li>
              ))}
          </ol>
          {firedNotifications.length < notifications.unread_count ? <p className="border-t px-4 py-2 text-xs text-muted-foreground">共 {notifications.unread_count} 条未读，当前显示 {firedNotifications.length} 条。</p> : null}
          </> : null}
        </section>
      ) : null}

      {queue.error && <p role="alert" className="my-3 rounded-md border border-destructive/30 p-3 text-sm text-destructive">{queue.error} 已打开的工作卡暂时保留，办理时仍会核对当前业务状态。</p>}
      {discussionFocus && <section className="space-y-3 rounded-md border p-3" aria-label="原讨论与摘要办理"><div className="flex items-center justify-between gap-2"><h2 className="font-semibold">原讨论与人工核对</h2><Button type="button" size="sm" variant="ghost" onClick={() => setDiscussionFocus(null)}>关闭办理</Button></div><MyWorkDiscussion key={discussionFocus.runId} projectId={discussionFocus.projectId} runId={discussionFocus.runId}/></section>}
      {executionFocus&&<section className="space-y-2 rounded-md border p-3" aria-label="变更执行结果待办办理"><div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">{executionFocus.ecr_code} · {executionFocus.title} · 结果 v{executionFocus.revision_number}</h2><div className="flex gap-2"><Button type="button" variant="outline" size="sm" onClick={()=>void refreshIdWork()}>刷新待办</Button><Button type="button" variant="ghost" size="sm" onClick={()=>setExecutionFocus(null)}>关闭办理</Button></div></div><Link className="text-sm text-primary underline" href={`/projects?project=${executionFocus.project.id}&tab=engineering&change_ecr_id=${executionFocus.ecr_id}&change_task_id=${executionFocus.task_id}#ecr-${executionFocus.ecr_id}`}>打开原变更、批准范围及执行任务</Link><ChangeExecutionResults key={executionFocus.id} projectId={executionFocus.project.id} bindingId={executionFocus.binding_id} initiallyOpen focusResultId={executionFocus.id} onChanged={refreshIdWork}/></section>}
      {idFocus && <section className="space-y-2" aria-label="ID设计待办办理"><div className="flex items-center justify-between"><h2 className="font-semibold">{idFocus.kind === "freeze" ? "ID冻结待我确认" : "ID交付待我接收"}</h2><Button type="button" variant="ghost" size="sm" onClick={() => setIdFocus(null)}>关闭办理</Button></div><MyWorkIdDesignAction key={`${idFocus.kind}:${idFocus.id}`} item={idFocus} onChanged={() => void refreshIdWork()} /></section>}
      {crossFocus && <section className="space-y-2" aria-label="跨项目依赖办理"><div className="flex items-center justify-between"><h2 className="font-semibold">跨项目依赖待我确认</h2><Button type="button" variant="ghost" size="sm" onClick={() => setCrossFocus(null)}>关闭办理</Button></div><ProjectCrossDependencies key={`${crossFocus.projectId}:${crossFocus.proposalId}`} projectId={crossFocus.projectId} focusProposalId={crossFocus.proposalId} onChanged={() => void refreshIdWork()} /></section>}
      {actionable + counts.findings === 0 ? (
        <section
          className="mt-5 flex min-h-72 flex-col items-center justify-center rounded-lg border border-dashed bg-card px-6 text-center"
          role="status"
        >
          <CheckFatIcon aria-hidden className="size-9 text-success" />
          <h2 className="mt-3 font-semibold">当前没有分派给你的项目执行待办</h2>
          <p className="mt-1 max-w-lg text-sm leading-6 text-muted-foreground">
            新的任务、问题、验证或签核出现时会在这里聚合，并按到期日排序。
          </p>
          <Link className="mt-3 inline-flex min-h-11 items-center text-sm font-medium text-primary" href="/projects">
            浏览项目
          </Link>
        </section>
      ) : (
        <div className="mt-5 grid gap-4">
          <Section
            {...paging("tasks")}
            count={counts.tasks}
            icon={ClipboardTextIcon}
            title="任务"
            items={work.tasks.map((task) => (
              <Row
                badges={
                  <>
                    <StatusBadge value={task.status} />
                    <DueBadge due={task.due_date} today={today} />
                  </>
                }
                href={`/projects?project=${task.project.id}&tab=work-items&entity_id=${task.id}`}
                key={task.id}
                id={workCardAnchor("task", task.id)}
                project={task.project}
                title={task.title}
              ><TaskPreparation inlineActions onAction={setTaskNotice} projectId={task.project.id} taskId={task.id} handoffActions={work.id_design_actions ?? []} onChanged={() => void refreshIdWork()} /><WorkCardConversation projectId={task.project.id} kind="task" id={task.id}/></Row>
            ))}
          />
          <Section
            {...paging("issues")}
            count={counts.issues}
            icon={WarningCircleIcon}
            title="问题"
            items={work.issues.map((issue) => (
              <Row
                badges={
                  <>
                    <span className="rounded-full border border-destructive/30 bg-destructive/10 px-2 py-0.5 text-[10px] font-semibold text-destructive">
                      {label(severityLabels, issue.severity)}
                    </span>
                    <StatusBadge value={issue.status} />
                    <DueBadge due={issue.target_date} today={today} />
                  </>
                }
                href={`/projects?project=${issue.project.id}&tab=work-items&entity_id=${issue.id}`}
                key={issue.id}
                id={workCardAnchor("issue", issue.id)}
                project={issue.project}
                title={issue.title}
              ><IssueRiskWorkCard projectId={issue.project.id} itemId={issue.id} kind="issues" onChanged={refreshIdWork} onNotice={setTaskNotice}/><WorkCardConversation projectId={issue.project.id} kind="issue" id={issue.id}/></Row>
            ))}
          />
          <Section
            {...paging("risks")}
            count={counts.risks}
            icon={FlagIcon}
            title="风险"
            items={work.risks.map((risk) => (
              <Row
                badges={
                  <>
                    <span className="rounded-full border border-pending/30 bg-pending/10 px-2 py-0.5 font-mono text-[10px] font-semibold text-pending">
                      {risk.likelihood}×{risk.impact}
                    </span>
                    <StatusBadge value={risk.status} />
                    <DueBadge due={risk.target_date} today={today} />
                  </>
                }
                href={`/projects?project=${risk.project.id}&tab=work-items&entity_id=${risk.id}`}
                key={risk.id}
                id={workCardAnchor("risk", risk.id)}
                project={risk.project}
                title={risk.title}
              ><IssueRiskWorkCard projectId={risk.project.id} itemId={risk.id} kind="risks" onChanged={refreshIdWork} onNotice={setTaskNotice}/><WorkCardConversation projectId={risk.project.id} kind="risk" id={risk.id}/></Row>
            ))}
          />
          <Section
            {...paging("capa_actions")}
            count={counts.capa_actions}
            icon={WrenchIcon}
            title="CAPA 行动"
            items={work.capa_actions.map((capa) => (
              <Row
                badges={
                  <>
                    <span className="rounded-full border border-border bg-muted px-2 py-0.5 text-[10px] font-semibold text-muted-foreground">
                      {label(capaTypeLabels, capa.action_type)}
                    </span>
                    <StatusBadge value={capa.status} />
                    <DueBadge due={capa.due_date} today={today} />
                  </>
                }
                href={`/projects?project=${capa.project.id}&tab=quality&ncr=${capa.ncr_id}`}
                key={capa.id}
                id={workCardAnchor("capa", capa.id)}
                project={capa.project}
                title={capa.description}
              ><CapaWorkCard item={capa} onChanged={refreshIdWork} onNotice={setTaskNotice}/><WorkCardConversation projectId={capa.project.id} kind="capa" id={capa.id}/></Row>
            ))}
          />
          <Section
            {...paging("gate_signoffs")}
            count={counts.gate_signoffs}
            icon={ShieldCheckIcon}
            title="Gate 待我签核"
            items={work.gate_signoffs.map((signoff) => (
              <Row
                badges={
                  <>
                    <span className="rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary">
                      {label(slotLabels, signoff.slot)}席
                    </span>
                    <DueBadge due={signoff.review_due_at} today={today} />
                  </>
                }
                href={`/projects?project=${signoff.project.id}&tab=gates`}
                key={signoff.id}
                id={workCardAnchor("gate", signoff.id)}
                project={signoff.project}
                title={`${signoff.gate_name} · 第 ${signoff.round_number} 轮`}
              ><GateSignoffWorkCard item={signoff} onChanged={refreshIdWork} onNotice={setTaskNotice}/><WorkCardConversation projectId={signoff.project.id} kind="gate" id={signoff.gate_id}/></Row>
            ))}
          />
          <Section {...paging("cost_freeze_approvals")} count={counts.cost_freeze_approvals ?? 0} icon={ShieldCheckIcon} title="成本冻结待我批准" items={(work.cost_freeze_approvals ?? []).map(item => <li id={workCardAnchor("cost-freeze", item.id)} className="scroll-mt-6" key={item.id}><button type="button" className="flex min-h-11 w-full items-center justify-between gap-3 px-4 py-2.5 text-left text-sm hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/25" onClick={() => setCostFreezeFocus(item)}><span>{item.title}</span><span className="text-xs text-muted-foreground">{item.project.code} · 待本人批准</span></button></li>)}/>
          <Section {...paging("task_takeover_actions")} count={counts.task_takeover_actions ?? 0} icon={ClipboardTextIcon} title="任务交接待我办理" items={(work.task_takeover_actions ?? []).map(item => <li id={workCardAnchor("takeover", item.id)} className="scroll-mt-6" key={item.id}><button type="button" className="flex min-h-11 w-full flex-wrap items-center justify-between gap-3 px-4 py-2.5 text-left text-sm hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/25" onClick={() => setTakeoverFocus(item)}><span className="min-w-0 flex-1 break-words">{item.mode === "review" ? "待本人接收" : "退回／责任变化待补齐"} · {item.title}</span><span className="text-xs text-muted-foreground">{item.project.code} · 交接 v{item.revision}</span><DueBadge due={item.due_date} today={today}/></button></li>)}/>
          <Section {...paging("risk_followup_actions")} count={counts.risk_followup_actions ?? 0} icon={ShieldCheckIcon} title="风险处理结果待我办理" items={(work.risk_followup_actions ?? []).map(item => <li id={workCardAnchor("risk-result", item.id)} className="scroll-mt-6" key={item.id}><button type="button" className="flex min-h-11 w-full flex-wrap items-center justify-between gap-3 px-4 py-2.5 text-left text-sm hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/25" onClick={() => setRiskResultFocus(item)}><span className="min-w-0 flex-1 break-words">{item.mode === "review" ? "待本人接收" : "待提交／补齐结果"} · {item.title}</span><span className="text-xs text-muted-foreground">{item.project.code}</span></button></li>)}/>
          <Section {...paging("change_execution_confirmations")} count={counts.change_execution_confirmations??0} icon={ShieldCheckIcon} title="变更执行结果待我确认" items={(work.change_execution_confirmations??[]).map(item=><li id={workCardAnchor("change", item.id)} className="scroll-mt-6" key={item.id}><button type="button" className="flex min-h-11 w-full items-center justify-between gap-3 px-4 py-2.5 text-left text-sm hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/25" onClick={()=>setExecutionFocus(item)}><span>{{retest:"复验",rereview:"复审",recertification:"复认证",coordination:"协同"}[item.action]} · {item.ecr_code} · {item.title}<span className="ml-2 text-xs text-muted-foreground">结果 v{item.revision_number}</span></span><span className="text-xs text-muted-foreground">{item.project.code}</span></button></li>)}/>
          <Section {...paging("id_design_actions")} count={counts.id_design_actions ?? 0} icon={ShieldCheckIcon} title="ID设计待我确认 / 接收" items={(work.id_design_actions ?? []).map((item) => <li id={workCardAnchor(`id-${item.kind}`, item.id)} className="scroll-mt-6" key={`${item.kind}:${item.id}`}><button type="button" className="flex min-h-11 w-full items-center justify-between gap-3 px-4 py-2.5 text-left text-sm hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/25" onClick={() => setIdFocus(item)}><span>{item.kind === "freeze" ? "冻结确认" : "逐项接收"} · {item.title}</span><span className="text-xs text-muted-foreground">{item.project.code}</span></button></li>)} />
          <Section {...paging("cross_schedule_approvals")} count={crossCount} icon={ShieldCheckIcon} title="跨项目依赖待我确认" items={(work.cross_schedule_approvals ?? []).map((item) => <li id={workCardAnchor("cross", item.id, item.project.id)} className="scroll-mt-6" key={`${item.project.id}:${item.id}`}><button type="button" className="flex min-h-11 w-full items-center justify-between gap-3 px-4 py-2.5 text-left text-sm hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/25" onClick={() => setCrossFocus({ projectId: item.project.id, proposalId: item.id })}><span>{item.operation === "remove" ? "解除依赖" : item.operation === "replace" ? "转接依赖" : "依赖确认"} · {item.title}</span><span className="text-xs text-muted-foreground">{item.project.code}</span></button></li>)} />
          <Section
            {...paging("findings")}
            count={counts.findings}
            icon={TrayIcon}
            title="AI 建议待审／待应用"
            items={work.findings.map((finding) => (
              <Row
                badges={<StatusBadge value={finding.status ?? "pending_review"} />}
                href={`/ai-review?finding=${finding.id}`}
                key={finding.id}
                id={workCardAnchor("finding", finding.id)}
                project={finding.project}
                title={finding.title}
              ><div className="mx-4 mb-3"><ConversationFinding showUndo={false} findingId={finding.id} onRecorded={result => { setFindingReceipt(result); setTaskNotice(result.status === "accepted" ? "建议已接受，请继续核对并独立应用。" : result.status === "applied" ? "建议已应用，实际业务回执已保留在本页。" : "已记录本次裁决。"); void refreshIdWork(); }}/></div></Row>
            ))}
          />
        </div>
      )}
    </WorkspaceShell>
  );
}
