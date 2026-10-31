import type { ProjectStage } from "./project-types";
import type {
  ProjectMember,
  ProjectTask,
  TaskUpdateInput,
  WorkItemPriority,
} from "./project-work-item-types";

export type TaskStatusFilter = "open" | "closed" | "all";
export type TaskSort = "due" | "updated";

/** `assignee` is "all", "me", "unassigned" or a member user id; `stage` is "all", "none" or a stage id. */
export type TaskView = {
  status: TaskStatusFilter;
  assignee: string;
  stage: string;
  sort: TaskSort;
};

export const defaultTaskView: TaskView = { status: "open", assignee: "all", stage: "all", sort: "due" };

export type TaskFormValues = {
  title: string;
  description: string;
  priority: WorkItemPriority;
  assignee_user_id: string;
  stage_id: string;
  start_date: string;
  due_date: string;
  dependency_task_ids: string[];
};

const terminalStatuses = new Set<ProjectTask["status"]>(["done", "skipped"]);
const priorityRank: Record<WorkItemPriority, number> = { critical: 0, high: 1, medium: 2, low: 3 };

/** Calendar date in the viewer's own time zone, matching how due dates are entered. */
export function localIsoDate(now = new Date()) {
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

export function isTaskOpen(task: ProjectTask) {
  return !terminalStatuses.has(task.status);
}

export function isTaskOverdue(task: ProjectTask, today: string) {
  return isTaskOpen(task) && task.due_date !== null && task.due_date < today;
}

/** Whole days a due date has slipped, e.g. due 2026-10-20 seen on 2026-10-31 → 11. */
export function overdueDays(dueDate: string, today: string) {
  return Math.round((Date.parse(today) - Date.parse(dueDate)) / 86_400_000);
}

function matchesView(task: ProjectTask, view: TaskView, currentUserId: string) {
  if (view.status === "open" && !isTaskOpen(task)) return false;
  if (view.status === "closed" && isTaskOpen(task)) return false;
  if (view.assignee === "me" && task.assignee_user_id !== currentUserId) return false;
  if (view.assignee === "unassigned" && task.assignee_user_id !== null) return false;
  if (!["all", "me", "unassigned"].includes(view.assignee) && task.assignee_user_id !== view.assignee) {
    return false;
  }
  if (view.stage === "none" && task.stage_id !== null) return false;
  if (!["all", "none"].includes(view.stage) && task.stage_id !== view.stage) return false;
  return true;
}

function byRecentUpdate(left: ProjectTask, right: ProjectTask) {
  return right.updated_at.localeCompare(left.updated_at);
}

function byDueDate(today: string) {
  return (left: ProjectTask, right: ProjectTask) => {
    const openOrder = Number(!isTaskOpen(left)) - Number(!isTaskOpen(right));
    if (openOrder !== 0) return openOrder;
    const overdueOrder = Number(isTaskOverdue(right, today)) - Number(isTaskOverdue(left, today));
    if (overdueOrder !== 0) return overdueOrder;
    if (left.due_date !== right.due_date) {
      if (left.due_date === null) return 1;
      if (right.due_date === null) return -1;
      return left.due_date.localeCompare(right.due_date);
    }
    const priorityOrder = priorityRank[left.priority] - priorityRank[right.priority];
    return priorityOrder !== 0 ? priorityOrder : byRecentUpdate(left, right);
  };
}

export function applyTaskView(tasks: ProjectTask[], view: TaskView, currentUserId: string, today: string) {
  return tasks
    .filter((task) => matchesView(task, view, currentUserId))
    .sort(view.sort === "due" ? byDueDate(today) : byRecentUpdate);
}

export function memberLabel(members: ProjectMember[], userId: string | null, currentUserId: string) {
  if (userId === null) return "未分配";
  const member = members.find((candidate) => candidate.user_id === userId);
  if (!member) return userId === currentUserId ? "我" : "未知成员";
  return userId === currentUserId ? `${member.display_name}（我）` : member.display_name;
}

/** Tasks that already wait on `taskId`, directly or transitively; picking one as a predecessor would form a cycle. */
export function dependentTaskIds(tasks: ProjectTask[], taskId: string) {
  const dependents = new Set<string>();
  const pending = [taskId];
  while (pending.length > 0) {
    const current = pending.pop()!;
    for (const candidate of tasks) {
      if (!dependents.has(candidate.id) && candidate.dependency_task_ids.includes(current)) {
        dependents.add(candidate.id);
        pending.push(candidate.id);
      }
    }
  }
  return dependents;
}

export function taskFormValues(task: ProjectTask): TaskFormValues {
  return {
    title: task.title,
    description: task.description ?? "",
    priority: task.priority,
    assignee_user_id: task.assignee_user_id ?? "",
    stage_id: task.stage_id ?? "",
    start_date: task.start_date ?? "",
    due_date: task.due_date ?? "",
    dependency_task_ids: task.dependency_task_ids,
  };
}

function sameIds(left: string[], right: string[]) {
  return left.length === right.length && [...left].sort().join("\n") === [...right].sort().join("\n");
}

/** Only fields that differ from the stored Task, so the PATCH and its audit diff stay minimal. */
export function buildTaskUpdate(task: ProjectTask, values: TaskFormValues): TaskUpdateInput {
  const update: TaskUpdateInput = {};
  const title = values.title.trim();
  if (title !== task.title) update.title = title;
  const description = values.description.trim() || null;
  if (description !== task.description) update.description = description;
  if (values.priority !== task.priority) update.priority = values.priority;
  const nullable = (value: string) => value || null;
  if (nullable(values.assignee_user_id) !== task.assignee_user_id) {
    update.assignee_user_id = nullable(values.assignee_user_id);
  }
  if (nullable(values.stage_id) !== task.stage_id) update.stage_id = nullable(values.stage_id);
  if (nullable(values.start_date) !== task.start_date) update.start_date = nullable(values.start_date);
  if (nullable(values.due_date) !== task.due_date) update.due_date = nullable(values.due_date);
  if (!sameIds(values.dependency_task_ids, task.dependency_task_ids)) {
    update.dependency_task_ids = values.dependency_task_ids;
  }
  return update;
}

export type StageSchedule = { tone: "ok" | "late" | "pending" | "none"; label: string };

/**
 * Plan-vs-actual status of one stage. Finished stages compare their exit date with the
 * planned end; the current stage compares today; later stages show their planned start.
 */
export function stageSchedule(stage: ProjectStage, currentSequence: number, today: string): StageSchedule {
  const plannedEnd = stage.planned_end_date ?? null;
  if (stage.sequence < currentSequence) {
    const exited = stage.exited_at ? localIsoDate(new Date(stage.exited_at)) : null;
    if (!plannedEnd || !exited) return { tone: "none", label: "已完成" };
    const late = overdueDays(plannedEnd, exited);
    return late > 0 ? { tone: "late", label: `延期 ${late} 天完成` } : { tone: "ok", label: "按期完成" };
  }
  if (stage.sequence === currentSequence) {
    if (!plannedEnd) return { tone: "none", label: "未设计划" };
    const late = overdueDays(plannedEnd, today);
    return late > 0
      ? { tone: "late", label: `阶段逾期 ${late} 天` }
      : { tone: "pending", label: late === 0 ? "今天计划结束" : `剩余 ${-late} 天` };
  }
  return stage.planned_start_date
    ? { tone: "pending", label: `计划 ${stage.planned_start_date} 开始` }
    : { tone: "none", label: "未设计划" };
}
