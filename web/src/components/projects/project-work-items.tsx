"use client";

import { CalendarBlankIcon, PencilSimpleIcon, StackIcon, UserCircleIcon } from "@phosphor-icons/react";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import {
  applyTaskView,
  buildTaskUpdate,
  defaultTaskView,
  dependentTaskIds,
  isTaskOpen,
  isTaskOverdue,
  localIsoDate,
  memberLabel,
  taskFormValues,
  type TaskFormValues,
  type TaskSort,
  type TaskStatusFilter,
  type TaskView,
} from "./project-task-planning";
import type { ProjectStage } from "./project-types";
import type {
  IssueCreateInput,
  IssueStatus,
  ProjectIssue,
  ProjectMember,
  ProjectRisk,
  ProjectTask,
  RiskCreateInput,
  RiskStatus,
  TaskCreateInput,
  TaskStatus,
  TaskTransitionInput,
  TaskUpdateInput,
  WorkItemPriority,
} from "./project-work-item-types";

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

const taskStatusFilterLabels: Record<TaskStatusFilter, string> = {
  open: "未完成",
  closed: "已结束",
  all: "全部状态",
};

function daysBetween(fromIsoDate: string, toIsoDate: string) {
  return Math.round((Date.parse(toIsoDate) - Date.parse(fromIsoDate)) / 86_400_000);
}

function AssigneeOptions({
  currentUserId,
  keepUserId = null,
  members,
}: {
  currentUserId: string;
  keepUserId?: string | null;
  members: ProjectMember[];
}) {
  const assignable = members.filter((member) => member.assignable && member.is_active);
  const kept = keepUserId !== null && !assignable.some((member) => member.user_id === keepUserId) ? keepUserId : null;
  return (
    <>
      <option value="">未分配</option>
      {assignable.map((member) => (
        <option key={member.user_id} value={member.user_id}>{memberLabel(members, member.user_id, currentUserId)}</option>
      ))}
      {kept ? <option value={kept}>{memberLabel(members, kept, currentUserId)}</option> : null}
    </>
  );
}

function StageOptions({ stages }: { stages: ProjectStage[] }) {
  return (
    <>
      <option value="">未指定阶段</option>
      {stages.map((stage) => (
        <option key={stage.id} value={stage.id}>{`${stage.sequence}. ${stage.name}`}</option>
      ))}
    </>
  );
}

function TaskEditForm({
  busy,
  currentUserId,
  members,
  onCancel,
  onSave,
  stages,
  task,
  tasks,
}: {
  busy: boolean;
  currentUserId: string;
  members: ProjectMember[];
  onCancel: () => void;
  onSave: (input: TaskUpdateInput) => Promise<boolean>;
  stages: ProjectStage[];
  task: ProjectTask;
  tasks: ProjectTask[];
}) {
  const [values, setValues] = useState<TaskFormValues>(() => taskFormValues(task));
  const [error, setError] = useState<string | null>(null);
  const idPrefix = `task-edit-${task.id}`;
  const dependents = dependentTaskIds(tasks, task.id);
  const dependencyCandidates = tasks.filter((candidate) => candidate.id !== task.id && !dependents.has(candidate.id));

  function set<K extends keyof TaskFormValues>(key: K, value: TaskFormValues[K]) {
    setValues((current) => ({ ...current, [key]: value }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!values.title.trim()) {
      setError("任务标题不能为空。");
      return;
    }
    if (values.start_date && values.due_date && values.due_date < values.start_date) {
      setError("截止日期不能早于开始日期。");
      return;
    }
    setError(null);
    const update = buildTaskUpdate(task, values);
    if (Object.keys(update).length === 0) {
      onCancel();
      return;
    }
    if (await onSave(update)) onCancel();
  }

  return (
    <form aria-label={`编辑任务 ${task.title}`} className="mt-3 grid gap-3 rounded-lg border bg-muted/25 p-3 sm:grid-cols-2 lg:grid-cols-4" onSubmit={submit}>
      <label className="min-w-0 text-xs font-medium sm:col-span-2 lg:col-span-3" htmlFor={`${idPrefix}-title`}>
        任务标题
        <input className={`${controlClass} mt-1`} disabled={busy} id={`${idPrefix}-title`} maxLength={512} onChange={(event) => set("title", event.target.value)} required value={values.title} />
      </label>
      <label className="text-xs font-medium" htmlFor={`${idPrefix}-priority`}>
        优先级
        <select className={`${controlClass} mt-1`} disabled={busy} id={`${idPrefix}-priority`} onChange={(event) => set("priority", event.target.value as WorkItemPriority)} value={values.priority}><PriorityOptions /></select>
      </label>
      <label className="text-xs font-medium" htmlFor={`${idPrefix}-assignee`}>
        负责人
        <select className={`${controlClass} mt-1`} disabled={busy} id={`${idPrefix}-assignee`} onChange={(event) => set("assignee_user_id", event.target.value)} value={values.assignee_user_id}>
          <AssigneeOptions currentUserId={currentUserId} keepUserId={task.assignee_user_id} members={members} />
        </select>
      </label>
      <label className="text-xs font-medium" htmlFor={`${idPrefix}-stage`}>
        所属阶段
        <select className={`${controlClass} mt-1`} disabled={busy} id={`${idPrefix}-stage`} onChange={(event) => set("stage_id", event.target.value)} value={values.stage_id}><StageOptions stages={stages} /></select>
      </label>
      <label className="text-xs font-medium" htmlFor={`${idPrefix}-start`}>
        开始日期
        <input className={`${controlClass} mt-1`} disabled={busy} id={`${idPrefix}-start`} onChange={(event) => set("start_date", event.target.value)} type="date" value={values.start_date} />
      </label>
      <label className="text-xs font-medium" htmlFor={`${idPrefix}-due`}>
        截止日期
        <input className={`${controlClass} mt-1`} disabled={busy} id={`${idPrefix}-due`} onChange={(event) => set("due_date", event.target.value)} type="date" value={values.due_date} />
      </label>
      <label className="min-w-0 text-xs font-medium sm:col-span-2 lg:col-span-4" htmlFor={`${idPrefix}-description`}>
        描述
        <textarea className={`${controlClass} mt-1 min-h-20`} disabled={busy} id={`${idPrefix}-description`} maxLength={20_000} onChange={(event) => set("description", event.target.value)} value={values.description} />
      </label>
      {dependencyCandidates.length > 0 ? (
        <fieldset className="grid gap-2 rounded-lg border bg-background p-3 sm:col-span-2 sm:grid-cols-2 lg:col-span-4">
          <legend className="px-1 text-xs font-medium">前置任务</legend>
          {dependencyCandidates.map((candidate) => (
            <label className="flex min-h-11 min-w-0 items-center gap-2 text-xs" key={candidate.id}>
              <input
                checked={values.dependency_task_ids.includes(candidate.id)}
                className="size-4 accent-primary"
                disabled={busy}
                onChange={(event) => set(
                  "dependency_task_ids",
                  event.target.checked
                    ? [...values.dependency_task_ids, candidate.id]
                    : values.dependency_task_ids.filter((id) => id !== candidate.id),
                )}
                type="checkbox"
              />
              <span className="truncate">{candidate.title}</span>
            </label>
          ))}
        </fieldset>
      ) : null}
      {error ? <p className="text-xs text-destructive sm:col-span-2 lg:col-span-4" role="alert">{error}</p> : null}
      <div className="flex flex-wrap gap-2 sm:col-span-2 lg:col-span-4">
        <Button className="h-11 sm:h-8" disabled={busy} type="submit">保存任务</Button>
        <Button className="h-11 sm:h-8" disabled={busy} onClick={onCancel} type="button" variant="outline">取消</Button>
      </div>
    </form>
  );
}

export function TaskPanel({
  busy,
  currentStageId,
  currentUserId,
  members,
  onCreate,
  onTransition,
  onUpdate,
  stages,
  tasks,
}: {
  busy: boolean;
  currentStageId: string;
  currentUserId: string;
  members: ProjectMember[];
  onCreate: (input: TaskCreateInput) => Promise<boolean>;
  onTransition: (task: ProjectTask, input: TaskTransitionInput) => Promise<boolean>;
  onUpdate: (task: ProjectTask, input: TaskUpdateInput) => Promise<boolean>;
  stages: ProjectStage[];
  tasks: ProjectTask[];
}) {
  const [blockedReason, setBlockedReason] = useState<Record<string, string>>({});
  const [view, setView] = useState<TaskView>(defaultTaskView);
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const today = localIsoDate();
  const visibleTasks = applyTaskView(tasks, view, currentUserId, today);
  const stageNames = new Map(stages.map((stage) => [stage.id, stage.name]));
  const filtered = view.status !== defaultTaskView.status || view.assignee !== "all" || view.stage !== "all";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const text = (name: string) => String(data.get(name) ?? "").trim();
    const startDate = text("start_date");
    const dueDate = text("due_date");
    if (startDate && dueDate && dueDate < startDate) {
      setCreateError("截止日期不能早于开始日期。");
      return;
    }
    setCreateError(null);
    const input: TaskCreateInput = {
      title: text("title"),
      priority: (text("priority") || "medium") as WorkItemPriority,
      dependency_task_ids: data.getAll("dependency_task_ids").map(String),
    };
    if (text("assignee_user_id")) input.assignee_user_id = text("assignee_user_id");
    if (text("stage_id")) input.stage_id = text("stage_id");
    if (startDate) input.start_date = startDate;
    if (dueDate) input.due_date = dueDate;
    const created = await onCreate(input);
    if (created) form.reset();
  }

  return (
    <section aria-label="项目任务" className="overflow-hidden rounded-lg border bg-card">
      <PanelHeader count={tasks.length} description="状态与 readiness 分开显示；等待前置不等于阻塞。" title="任务" />
      <form className="grid gap-3 border-b bg-muted/25 p-4 sm:grid-cols-2 lg:grid-cols-4 lg:items-end" onSubmit={submit}>
        <label className="min-w-0 text-xs font-medium sm:col-span-2" htmlFor="task-title">
          任务标题
          <input className={`${controlClass} mt-1`} disabled={busy} id="task-title" maxLength={512} name="title" required />
        </label>
        <label className="text-xs font-medium" htmlFor="task-priority">
          优先级
          <select className={`${controlClass} mt-1`} defaultValue="medium" disabled={busy} id="task-priority" name="priority"><PriorityOptions /></select>
        </label>
        <Button className="order-last h-11 lg:order-none" disabled={busy} type="submit">创建任务</Button>
        <label className="text-xs font-medium" htmlFor="task-assignee">
          负责人
          <select className={`${controlClass} mt-1`} defaultValue="" disabled={busy} id="task-assignee" name="assignee_user_id">
            <AssigneeOptions currentUserId={currentUserId} members={members} />
          </select>
        </label>
        <label className="text-xs font-medium" htmlFor="task-stage">
          所属阶段
          <select className={`${controlClass} mt-1`} defaultValue={currentStageId} disabled={busy} id="task-stage" name="stage_id"><StageOptions stages={stages} /></select>
        </label>
        <label className="text-xs font-medium" htmlFor="task-start-date">
          开始日期
          <input className={`${controlClass} mt-1`} disabled={busy} id="task-start-date" name="start_date" type="date" />
        </label>
        <label className="text-xs font-medium" htmlFor="task-due-date">
          截止日期
          <input className={`${controlClass} mt-1`} disabled={busy} id="task-due-date" name="due_date" type="date" />
        </label>
        {createError ? <p className="text-xs text-destructive sm:col-span-2 lg:col-span-4" role="alert">{createError}</p> : null}
        {tasks.length > 0 ? (
          <details className="sm:col-span-2 lg:col-span-4">
            <summary className="min-h-11 py-3 text-xs font-medium text-muted-foreground">选择前置任务（可选）</summary>
            <fieldset className="grid gap-2 rounded-lg border bg-background p-3 sm:grid-cols-2">
              <legend className="sr-only">前置任务</legend>
              {tasks.map((task) => (
                <label className="flex min-h-11 items-center gap-2 text-xs" key={task.id}>
                  <input className="size-4 accent-primary" disabled={busy} name="dependency_task_ids" type="checkbox" value={task.id} />
                  <span className="truncate">{task.title}</span>
                </label>
              ))}
            </fieldset>
          </details>
        ) : null}
      </form>
      {tasks.length > 0 ? (
        <div aria-label="任务筛选" className="grid grid-cols-2 gap-3 border-b px-4 py-3 lg:grid-cols-[repeat(4,minmax(0,1fr))_auto] lg:items-end" role="group">
          <label className="min-w-0 text-xs font-medium" htmlFor="task-filter-status">
            状态
            <select className={`${controlClass} mt-1`} id="task-filter-status" onChange={(event) => setView((current) => ({ ...current, status: event.target.value as TaskStatusFilter }))} value={view.status}>
              {Object.entries(taskStatusFilterLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label className="min-w-0 text-xs font-medium" htmlFor="task-filter-assignee">
            负责人筛选
            <select className={`${controlClass} mt-1`} id="task-filter-assignee" onChange={(event) => setView((current) => ({ ...current, assignee: event.target.value }))} value={view.assignee}>
              <option value="all">全部成员</option>
              <option value="me">我负责的</option>
              <option value="unassigned">未分配</option>
              {members.map((member) => <option key={member.user_id} value={member.user_id}>{memberLabel(members, member.user_id, currentUserId)}</option>)}
            </select>
          </label>
          <label className="min-w-0 text-xs font-medium" htmlFor="task-filter-stage">
            阶段筛选
            <select className={`${controlClass} mt-1`} id="task-filter-stage" onChange={(event) => setView((current) => ({ ...current, stage: event.target.value }))} value={view.stage}>
              <option value="all">全部阶段</option>
              <option value="none">未指定阶段</option>
              {stages.map((stage) => <option key={stage.id} value={stage.id}>{`${stage.sequence}. ${stage.name}`}</option>)}
            </select>
          </label>
          <label className="min-w-0 text-xs font-medium" htmlFor="task-sort">
            排序
            <select className={`${controlClass} mt-1`} id="task-sort" onChange={(event) => setView((current) => ({ ...current, sort: event.target.value as TaskSort }))} value={view.sort}>
              <option value="due">截止日期优先</option>
              <option value="updated">最近更新</option>
            </select>
          </label>
          <p className="col-span-2 font-mono text-xs text-muted-foreground lg:col-span-1 lg:pb-3" data-testid="task-visible-count">
            显示 {visibleTasks.length} / {tasks.length}
          </p>
        </div>
      ) : null}
      {tasks.length === 0 ? <EmptyRow>还没有任务。创建第一条可执行工作。</EmptyRow> : null}
      {tasks.length > 0 && visibleTasks.length === 0 ? (
        <div className="px-4 py-10 text-center text-sm text-muted-foreground">
          <p>没有符合筛选条件的任务。</p>
          {filtered ? (
            <Button className="mt-3 h-11 sm:h-8" onClick={() => setView((current) => ({ ...defaultTaskView, sort: current.sort }))} variant="outline">清除筛选</Button>
          ) : null}
        </div>
      ) : null}
      {visibleTasks.length > 0 ? (
        <ul className="divide-y" role="list">
          {visibleTasks.map((task) => {
            const canStart = task.status === "todo" && task.readiness === "ready";
            const canBlock = task.status === "todo" || task.status === "in_progress";
            const overdue = isTaskOverdue(task, today);
            const editing = editingTaskId === task.id;
            return (
              <li className="p-4" key={task.id}>
                <div className="flex flex-wrap items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">{task.title}</p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <Badge tone={task.status === "blocked" ? "bad" : task.status === "done" ? "ok" : "neutral"}>{taskStatusLabels[task.status]}</Badge>
                      <Badge tone={task.readiness === "waiting" ? "pending" : task.readiness === "blocked" ? "bad" : "neutral"}>{readinessLabels[task.readiness]}</Badge>
                      <Badge>{priorityLabels[task.priority]}优先级</Badge>
                      {task.dependency_task_ids.length > 0 ? <Badge>{task.unresolved_dependency_ids.length}/{task.dependency_task_ids.length} 前置未完成</Badge> : null}
                      {overdue && task.due_date ? <Badge tone="bad">逾期 {daysBetween(task.due_date, today)} 天</Badge> : null}
                    </div>
                    <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                      <span className="inline-flex min-w-0 items-center gap-1"><UserCircleIcon aria-hidden className="size-3.5 shrink-0" />负责人：{memberLabel(members, task.assignee_user_id, currentUserId)}</span>
                      <span className="inline-flex min-w-0 items-center gap-1"><StackIcon aria-hidden className="size-3.5 shrink-0" />阶段：{task.stage_id ? stageNames.get(task.stage_id) ?? "未知阶段" : "未指定"}</span>
                      <span className={cn("inline-flex min-w-0 items-center gap-1", overdue && "font-medium text-destructive")}>
                        <CalendarBlankIcon aria-hidden className="size-3.5 shrink-0" />截止：<span className="font-mono">{task.due_date ?? "未设置"}</span>
                      </span>
                    </div>
                    {task.description ? <p className="mt-2 whitespace-pre-line text-xs text-muted-foreground">{task.description}</p> : null}
                    {task.blocked_reason ? <p className="mt-2 text-xs text-destructive">阻塞原因：{task.blocked_reason}</p> : null}
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {canStart ? <Button className="h-11 sm:h-8" disabled={busy} onClick={() => void onTransition(task, { to_status: "in_progress" })}>开始任务</Button> : null}
                  {task.status === "in_progress" ? <Button className="h-11 sm:h-8" disabled={busy} onClick={() => void onTransition(task, { to_status: "done" })}>完成任务</Button> : null}
                  {task.status === "blocked" ? (
                    <>
                      <Button className="h-11 sm:h-8" disabled={busy} onClick={() => void onTransition(task, { to_status: "todo" })} variant="outline">解除阻塞</Button>
                      {task.unresolved_dependency_ids.length === 0 ? <Button className="h-11 sm:h-8" disabled={busy} onClick={() => void onTransition(task, { to_status: "in_progress" })}>解除并开始</Button> : null}
                    </>
                  ) : null}
                  {(task.status === "todo" || task.status === "blocked") ? <Button className="h-11 sm:h-8" disabled={busy} onClick={() => void onTransition(task, { to_status: "skipped" })} variant="outline">跳过任务</Button> : null}
                  {isTaskOpen(task) ? (
                    <Button
                      aria-expanded={editing}
                      aria-label={`编辑任务 ${task.title}`}
                      className="h-11 sm:h-8"
                      disabled={busy}
                      onClick={() => setEditingTaskId(editing ? null : task.id)}
                      variant="outline"
                    >
                      <PencilSimpleIcon aria-hidden />编辑
                    </Button>
                  ) : null}
                </div>
                {editing ? (
                  <TaskEditForm
                    busy={busy}
                    currentUserId={currentUserId}
                    members={members}
                    onCancel={() => setEditingTaskId(null)}
                    onSave={(input) => onUpdate(task, input)}
                    stages={stages}
                    task={task}
                    tasks={tasks}
                  />
                ) : null}
                {canBlock && !editing ? (
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
              </li>
            );
          })}
        </ul>
      ) : null}
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
