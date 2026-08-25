"use client";

import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type {
  IssueCreateInput,
  IssueStatus,
  ProjectIssue,
  ProjectRisk,
  ProjectTask,
  RiskCreateInput,
  RiskStatus,
  TaskCreateInput,
  TaskStatus,
  TaskTransitionInput,
  WorkItemPriority,
} from "./project-work-item-types";
import type { ProjectStage } from "./project-types";

const controlClass =
  "min-h-11 w-full min-w-0 rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 disabled:opacity-60";

const priorityLabels: Record<WorkItemPriority, string> = {
  low: "低",
  medium: "中",
  high: "高",
  critical: "关键",
};

const taskStatusLabels: Record<TaskStatus, string> = {
  todo: "待开始",
  in_progress: "进行中",
  blocked: "已阻塞",
  done: "已完成",
  skipped: "已跳过",
};

const readinessLabels: Record<ProjectTask["readiness"], string> = {
  ready: "可开始",
  waiting: "等待前置",
  blocked: "显式阻塞",
  complete: "已完成",
  waiting_approval: "待批准",
};

const issueStatusLabels: Record<IssueStatus, string> = {
  open: "待分析",
  analysis: "分析中",
  action: "行动中",
  verification: "待验证",
  closed: "已关闭",
};

const riskStatusLabels: Record<RiskStatus, string> = {
  open: "开放",
  mitigating: "缓解中",
  watching: "观察中",
  closed: "已关闭",
};

function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "pending" | "bad" | "ok" }) {
  return (
    <span
      className={cn(
        "inline-flex rounded-full border px-2 py-0.5 text-[11px] font-medium",
        tone === "neutral" && "bg-muted text-muted-foreground",
        tone === "pending" && "border-pending/25 bg-pending/10 text-pending",
        tone === "bad" && "border-destructive/25 bg-destructive/10 text-destructive",
        tone === "ok" && "border-success/25 bg-success/10 text-success",
      )}
    >
      {children}
    </span>
  );
}

function PanelHeader({ count, description, title }: { count: number; description: string; title: string }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-2 border-b px-4 py-3">
      <div>
        <h3 className="font-semibold">{title}</h3>
        <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
      </div>
      <span className="font-mono text-xs text-muted-foreground">{count} 条</span>
    </div>
  );
}

function PriorityOptions() {
  return Object.entries(priorityLabels).map(([value, label]) => (
    <option key={value} value={value}>{label}</option>
  ));
}

function EmptyRow({ children }: { children: React.ReactNode }) {
  return <p className="px-4 py-10 text-center text-sm text-muted-foreground">{children}</p>;
}

export function TaskPanel({
  busy,
  onCreate,
  onTransition,
  stages,
  tasks,
}: {
  busy: boolean;
  onCreate: (input: TaskCreateInput) => Promise<boolean>;
  onTransition: (task: ProjectTask, input: TaskTransitionInput) => Promise<boolean>;
  stages: ProjectStage[];
  tasks: ProjectTask[];
}) {
  const [blockedReason, setBlockedReason] = useState<Record<string, string>>({});
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const optional = (name: string) => {
      const value = String(data.get(name) ?? "").trim();
      return value || null;
    };
    const created = await onCreate({
      title: String(data.get("title") ?? "").trim(),
      description: optional("description"),
      stage_id: optional("stage_id"),
      start_date: optional("start_date"),
      due_date: optional("due_date"),
      priority: String(data.get("priority") ?? "medium") as WorkItemPriority,
      dependency_task_ids: data.getAll("dependency_task_ids").map(String),
    });
    if (created) form.reset();
  }

  return (
    <section aria-label="项目任务" className="overflow-hidden rounded-lg border bg-card">
      <PanelHeader count={tasks.length} description="状态与 readiness 分开显示；等待前置不等于阻塞。" title="任务" />
      <form className="grid gap-3 border-b bg-muted/25 p-4 lg:grid-cols-[minmax(0,1fr)_140px_auto] lg:items-end" onSubmit={submit}>
        <label className="min-w-0 text-xs font-medium" htmlFor="task-title">
          任务标题
          <input className={`${controlClass} mt-1`} disabled={busy} id="task-title" maxLength={512} name="title" required />
        </label>
        <label className="text-xs font-medium" htmlFor="task-priority">
          优先级
          <select className={`${controlClass} mt-1`} defaultValue="medium" disabled={busy} id="task-priority" name="priority"><PriorityOptions /></select>
        </label>
        <Button className="h-11" disabled={busy} type="submit">创建任务</Button>
        <details className="lg:col-span-3">
          <summary className="min-h-11 py-3 text-xs font-medium text-muted-foreground">补充任务详情（说明、阶段、日期与前置任务）</summary>
          <div className="grid gap-3 rounded-lg border bg-background p-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-xs font-medium sm:col-span-2 lg:col-span-4" htmlFor="task-description">
              任务说明
              <textarea className={`${controlClass} mt-1 min-h-24 resize-y`} disabled={busy} id="task-description" maxLength={20_000} name="description" />
            </label>
            <label className="text-xs font-medium sm:col-span-2" htmlFor="task-stage">
              所属阶段
              <select className={`${controlClass} mt-1`} disabled={busy} id="task-stage" name="stage_id">
                <option value="">未指定</option>
                {stages.map((stage) => <option key={stage.id} value={stage.id}>{stage.name}</option>)}
              </select>
            </label>
            <label className="text-xs font-medium" htmlFor="task-start-date">
              开始日期
              <input className={`${controlClass} mt-1`} disabled={busy} id="task-start-date" name="start_date" type="date" />
            </label>
            <label className="text-xs font-medium" htmlFor="task-due-date">
              截止日期
              <input className={`${controlClass} mt-1`} disabled={busy} id="task-due-date" name="due_date" type="date" />
            </label>
            {tasks.length > 0 ? (
              <fieldset className="grid gap-2 border-t pt-3 sm:col-span-2 sm:grid-cols-2 lg:col-span-4">
                <legend className="text-xs font-medium">前置任务（可选）</legend>
                {tasks.map((task) => (
                  <label className="flex min-h-11 items-center gap-2 text-xs" key={task.id}>
                    <input className="size-4 accent-primary" disabled={busy} name="dependency_task_ids" type="checkbox" value={task.id} />
                    <span className="truncate">{task.title}</span>
                  </label>
                ))}
              </fieldset>
            ) : null}
          </div>
        </details>
      </form>
      {tasks.length === 0 ? <EmptyRow>还没有任务。创建第一条可执行工作。</EmptyRow> : (
        <ul className="divide-y" role="list">
          {tasks.map((task) => {
            const canStart = task.status === "todo" && task.readiness === "ready";
            const canBlock = task.status === "todo" || task.status === "in_progress";
            const expanded = expandedTaskId === task.id;
            const stageName = stages.find((stage) => stage.id === task.stage_id)?.name ?? "未指定";
            const dependencies = task.dependency_task_ids.map(
              (dependencyId) => tasks.find((item) => item.id === dependencyId)?.title ?? dependencyId,
            );
            return (
              <li key={task.id}>
                <button
                  aria-controls={`task-detail-${task.id}`}
                  aria-expanded={expanded}
                  aria-label={`${expanded ? "收起" : "查看"}任务详情 ${task.title}`}
                  className="flex min-h-16 w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/20"
                  onClick={() => setExpandedTaskId(expanded ? null : task.id)}
                  type="button"
                >
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">{task.title}</p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <Badge tone={task.status === "blocked" ? "bad" : task.status === "done" ? "ok" : "neutral"}>{taskStatusLabels[task.status]}</Badge>
                      <Badge tone={task.readiness === "waiting" ? "pending" : task.readiness === "blocked" ? "bad" : "neutral"}>{readinessLabels[task.readiness]}</Badge>
                      <Badge>{priorityLabels[task.priority]}优先级</Badge>
                      {task.dependency_task_ids.length > 0 ? <Badge>{task.unresolved_dependency_ids.length}/{task.dependency_task_ids.length} 前置未完成</Badge> : null}
                    </div>
                    {task.blocked_reason ? <p className="mt-2 text-xs text-destructive">阻塞原因：{task.blocked_reason}</p> : null}
                  </div>
                  <span className="shrink-0 pt-0.5 text-xs font-medium text-primary">{expanded ? "收起" : "详情"}</span>
                </button>
                {expanded ? (
                  <div className="border-t bg-muted/15 p-4" id={`task-detail-${task.id}`}>
                    <div className="grid gap-4 text-xs sm:grid-cols-2 lg:grid-cols-4">
                      <div className="sm:col-span-2 lg:col-span-4">
                        <p className="font-medium text-muted-foreground">任务说明</p>
                        <p className="mt-1 whitespace-pre-wrap text-sm leading-6">{task.description ?? "暂无任务说明"}</p>
                      </div>
                      <div><p className="text-muted-foreground">所属阶段</p><p className="mt-1 font-medium">{stageName}</p></div>
                      <div><p className="text-muted-foreground">计划日期</p><p className="mt-1 font-mono">{task.start_date ?? "未设置"} → {task.due_date ?? "未设置"}</p></div>
                      <div><p className="text-muted-foreground">负责人</p><p className="mt-1 font-medium">{task.assignee_user_id ? "已分配" : "未分配"}</p></div>
                      <div><p className="text-muted-foreground">前置任务</p><p className="mt-1 font-medium">{dependencies.length ? dependencies.join("、") : "无"}</p></div>
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2 border-t pt-4">
                      {canStart ? <Button className="h-11 sm:h-8" disabled={busy} onClick={() => void onTransition(task, { to_status: "in_progress" })}>开始任务</Button> : null}
                      {task.status === "in_progress" ? <Button className="h-11 sm:h-8" disabled={busy} onClick={() => void onTransition(task, { to_status: "done" })}>完成任务</Button> : null}
                      {task.status === "blocked" ? (
                        <>
                          <Button className="h-11 sm:h-8" disabled={busy} onClick={() => void onTransition(task, { to_status: "todo" })} variant="outline">解除阻塞</Button>
                          {task.unresolved_dependency_ids.length === 0 ? <Button className="h-11 sm:h-8" disabled={busy} onClick={() => void onTransition(task, { to_status: "in_progress" })}>解除并开始</Button> : null}
                        </>
                      ) : null}
                      {(task.status === "todo" || task.status === "blocked") ? <Button className="h-11 sm:h-8" disabled={busy} onClick={() => void onTransition(task, { to_status: "skipped" })} variant="outline">跳过任务</Button> : null}
                    </div>
                    {canBlock ? (
                      <form
                        className="mt-3 flex min-w-0 flex-col gap-2 rounded-lg border border-destructive/20 bg-destructive/5 p-2 sm:flex-row"
                        onSubmit={(event) => {
                          event.preventDefault();
                          const reason = (blockedReason[task.id] ?? "").trim();
                          if (reason) void onTransition(task, { to_status: "blocked", blocked_reason: reason });
                        }}
                      >
                        <label className="min-w-0 flex-1 text-xs font-medium">
                          <span className="sr-only">阻塞原因 {task.title}</span>
                          <input
                            aria-label={`阻塞原因 ${task.title}`}
                            className={controlClass}
                            disabled={busy}
                            maxLength={20_000}
                            onChange={(event) => setBlockedReason((current) => ({ ...current, [task.id]: event.target.value }))}
                            placeholder="填写真实阻塞原因"
                            required
                            value={blockedReason[task.id] ?? ""}
                          />
                        </label>
                        <Button className="h-11" disabled={busy} type="submit" variant="destructive">标记阻塞</Button>
                      </form>
                    ) : null}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

const nextIssueAction: Partial<Record<IssueStatus, { label: string; to: IssueStatus }>> = {
  open: { label: "进入分析", to: "analysis" },
  analysis: { label: "进入行动", to: "action" },
  action: { label: "提交验证", to: "verification" },
  verification: { label: "关闭问题", to: "closed" },
};

export function IssuePanel({ busy, issues, onCreate, onTransition }: {
  busy: boolean;
  issues: ProjectIssue[];
  onCreate: (input: IssueCreateInput) => Promise<boolean>;
  onTransition: (issue: ProjectIssue, toStatus: IssueStatus) => Promise<boolean>;
}) {
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const created = await onCreate({
      title: String(data.get("title") ?? "").trim(),
      severity: String(data.get("severity") ?? "medium") as WorkItemPriority,
    });
    if (created) form.reset();
  }
  return (
    <section aria-label="项目问题" className="overflow-hidden rounded-lg border bg-card">
      <PanelHeader count={issues.length} description="问题严格按 Open → Analysis → Action → Verification → Closed 推进。" title="问题" />
      <form className="grid gap-3 border-b bg-muted/25 p-4 lg:grid-cols-[minmax(0,1fr)_140px_auto] lg:items-end" onSubmit={submit}>
        <label className="min-w-0 text-xs font-medium" htmlFor="issue-title">问题标题<input className={`${controlClass} mt-1`} disabled={busy} id="issue-title" maxLength={512} name="title" required /></label>
        <label className="text-xs font-medium" htmlFor="issue-severity">严重度<select className={`${controlClass} mt-1`} defaultValue="medium" disabled={busy} id="issue-severity" name="severity"><PriorityOptions /></select></label>
        <Button className="h-11" disabled={busy} type="submit">创建问题</Button>
      </form>
      {issues.length === 0 ? <EmptyRow>还没有问题。</EmptyRow> : (
        <ul className="divide-y" role="list">
          {issues.map((issue) => {
            const action = nextIssueAction[issue.status];
            return (
              <li className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center" key={issue.id}>
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{issue.title}</p>
                  <div className="mt-2 flex flex-wrap gap-1.5"><Badge tone={issue.status === "closed" ? "ok" : "pending"}>{issueStatusLabels[issue.status]}</Badge><Badge tone={issue.severity === "critical" ? "bad" : "neutral"}>{priorityLabels[issue.severity]}</Badge></div>
                </div>
                {action ? <Button className="h-11 sm:h-8" disabled={busy} onClick={() => void onTransition(issue, action.to)}>{action.label}</Button> : null}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function riskActions(status: RiskStatus): { label: string; to: RiskStatus; variant?: "outline" }[] {
  if (status === "open") return [{ label: "开始缓解", to: "mitigating" }, { label: "转为观察", to: "watching", variant: "outline" }];
  if (status === "mitigating") return [{ label: "转为观察", to: "watching", variant: "outline" }, { label: "关闭风险", to: "closed" }];
  if (status === "watching") return [{ label: "开始缓解", to: "mitigating", variant: "outline" }, { label: "关闭风险", to: "closed" }];
  return [];
}

export function RiskPanel({ busy, onCreate, onTransition, risks }: {
  busy: boolean;
  onCreate: (input: RiskCreateInput) => Promise<boolean>;
  onTransition: (risk: ProjectRisk, toStatus: RiskStatus) => Promise<boolean>;
  risks: ProjectRisk[];
}) {
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const created = await onCreate({
      title: String(data.get("title") ?? "").trim(),
      likelihood: Number(data.get("likelihood") ?? 1),
      impact: Number(data.get("impact") ?? 1),
    });
    if (created) form.reset();
  }
  const scoreOptions = [1, 2, 3, 4, 5];
  return (
    <section aria-label="项目风险" className="overflow-hidden rounded-lg border bg-card">
      <PanelHeader count={risks.length} description="暴露分值由服务端稳定计算：likelihood × impact。" title="风险" />
      <form className="grid gap-3 border-b bg-muted/25 p-4 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_112px_112px_auto] lg:items-end" onSubmit={submit}>
        <label className="min-w-0 text-xs font-medium sm:col-span-2 lg:col-span-1" htmlFor="risk-title">风险标题<input className={`${controlClass} mt-1`} disabled={busy} id="risk-title" maxLength={512} name="title" required /></label>
        <label className="text-xs font-medium" htmlFor="risk-likelihood">可能性<select className={`${controlClass} mt-1`} defaultValue="1" disabled={busy} id="risk-likelihood" name="likelihood">{scoreOptions.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
        <label className="text-xs font-medium" htmlFor="risk-impact">影响<select className={`${controlClass} mt-1`} defaultValue="1" disabled={busy} id="risk-impact" name="impact">{scoreOptions.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
        <Button className="h-11" disabled={busy} type="submit">创建风险</Button>
      </form>
      {risks.length === 0 ? <EmptyRow>还没有风险。</EmptyRow> : (
        <ul className="divide-y" role="list">
          {risks.map((risk) => (
            <li className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center" key={risk.id}>
              <div className="min-w-0 flex-1">
                <p className="font-medium">{risk.title}</p>
                <div className="mt-2 flex flex-wrap gap-1.5"><Badge tone={risk.status === "closed" ? "ok" : risk.score >= 15 ? "bad" : "pending"}>{riskStatusLabels[risk.status]}</Badge><Badge tone={risk.score >= 15 ? "bad" : "neutral"}>暴露 {risk.score}</Badge><Badge>{risk.likelihood} × {risk.impact}</Badge></div>
              </div>
              <div className="flex flex-wrap gap-2">{riskActions(risk.status).map((action) => <Button className="h-11 sm:h-8" disabled={busy} key={action.to} onClick={() => void onTransition(risk, action.to)} variant={action.variant}>{action.label}</Button>)}</div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
