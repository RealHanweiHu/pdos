import { describe, expect, it } from "vitest";

import {
  applyTaskView,
  buildTaskUpdate,
  defaultTaskView,
  dependentTaskIds,
  isTaskOverdue,
  localIsoDate,
  memberLabel,
  taskFormValues,
} from "./project-task-planning";
import type { ProjectMember, ProjectTask } from "./project-work-item-types";

const base: ProjectTask = {
  id: "task-1",
  project_id: "project-1",
  stage_id: null,
  parent_task_id: null,
  assignee_user_id: null,
  title: "Base task",
  description: null,
  status: "todo",
  blocked_reason: null,
  priority: "medium",
  start_date: null,
  due_date: null,
  completed_at: null,
  dependency_task_ids: [],
  unresolved_dependency_ids: [],
  readiness: "ready",
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};

function task(overrides: Partial<ProjectTask>): ProjectTask {
  return { ...base, ...overrides };
}

const today = "2026-10-31";

describe("task planning helpers", () => {
  it("formats the viewer's local calendar date", () => {
    expect(localIsoDate(new Date(2026, 0, 5, 23, 59))).toBe("2026-01-05");
  });

  it("treats only unfinished tasks past their due date as overdue", () => {
    expect(isTaskOverdue(task({ due_date: "2026-10-30" }), today)).toBe(true);
    expect(isTaskOverdue(task({ due_date: today }), today)).toBe(false);
    expect(isTaskOverdue(task({ due_date: null }), today)).toBe(false);
    expect(isTaskOverdue(task({ due_date: "2026-10-01", status: "done" }), today)).toBe(false);
    expect(isTaskOverdue(task({ due_date: "2026-10-01", status: "skipped" }), today)).toBe(false);
  });

  it("orders overdue first, then by due date, priority and recency", () => {
    const tasks = [
      task({ id: "no-due-critical", priority: "critical" }),
      task({ id: "later", due_date: "2026-12-01" }),
      task({ id: "overdue", due_date: "2026-10-01" }),
      task({ id: "soon-low", due_date: "2026-11-02", priority: "low" }),
      task({ id: "soon-high", due_date: "2026-11-02", priority: "high" }),
      task({ id: "done", due_date: "2026-09-01", status: "done" }),
    ];

    expect(applyTaskView(tasks, { ...defaultTaskView, status: "all" }, "user-1", today).map((item) => item.id)).toEqual([
      "overdue",
      "soon-high",
      "soon-low",
      "later",
      "no-due-critical",
      "done",
    ]);
    expect(
      applyTaskView(tasks, { ...defaultTaskView, sort: "updated" }, "user-1", today).map((item) => item.id),
    ).not.toContain("done");
  });

  it("filters by status, assignee and stage", () => {
    const tasks = [
      task({ id: "mine", assignee_user_id: "user-1", stage_id: "stage-1" }),
      task({ id: "theirs", assignee_user_id: "user-2", stage_id: "stage-2" }),
      task({ id: "nobody" }),
      task({ id: "closed", assignee_user_id: "user-1", status: "skipped" }),
    ];
    const ids = (view: Partial<typeof defaultTaskView>) =>
      applyTaskView(tasks, { ...defaultTaskView, ...view }, "user-1", today).map((item) => item.id).sort();

    expect(ids({})).toEqual(["mine", "nobody", "theirs"]);
    expect(ids({ status: "closed" })).toEqual(["closed"]);
    expect(ids({ status: "all", assignee: "me" })).toEqual(["closed", "mine"]);
    expect(ids({ assignee: "unassigned" })).toEqual(["nobody"]);
    expect(ids({ assignee: "user-2" })).toEqual(["theirs"]);
    expect(ids({ stage: "stage-1" })).toEqual(["mine"]);
    expect(ids({ stage: "none" })).toEqual(["nobody"]);
  });

  it("finds direct and transitive dependents so the editor cannot offer a cycle", () => {
    const tasks = [
      task({ id: "a" }),
      task({ id: "b", dependency_task_ids: ["a"] }),
      task({ id: "c", dependency_task_ids: ["b"] }),
      task({ id: "d" }),
      task({ id: "e", dependency_task_ids: ["d", "c"] }),
    ];
    expect([...dependentTaskIds(tasks, "a")].sort()).toEqual(["b", "c", "e"]);
    expect([...dependentTaskIds(tasks, "d")]).toEqual(["e"]);
    expect(dependentTaskIds(tasks, "e").size).toBe(0);
  });

  it("labels assignees, including unknown and self", () => {
    const members: ProjectMember[] = [
      { user_id: "user-1", display_name: "Owner", role: "owner", is_active: true, assignable: true },
      { user_id: "user-2", display_name: "Engineer", role: "engineer", is_active: true, assignable: true },
    ];
    expect(memberLabel(members, null, "user-1")).toBe("未分配");
    expect(memberLabel(members, "user-1", "user-1")).toBe("Owner（我）");
    expect(memberLabel(members, "user-2", "user-1")).toBe("Engineer");
    expect(memberLabel(members, "user-9", "user-1")).toBe("未知成员");
    expect(memberLabel([], "user-1", "user-1")).toBe("我");
  });

  it("builds a minimal patch and clears fields with null", () => {
    const stored = task({
      title: "Validate pump",
      description: "Bench test",
      assignee_user_id: "user-2",
      stage_id: "stage-1",
      start_date: "2026-11-01",
      due_date: "2026-11-15",
      dependency_task_ids: ["task-a", "task-b"],
    });
    expect(buildTaskUpdate(stored, taskFormValues(stored))).toEqual({});
    expect(
      buildTaskUpdate(stored, {
        ...taskFormValues(stored),
        title: "  Validate pump  ",
        dependency_task_ids: ["task-b", "task-a"],
      }),
    ).toEqual({});
    expect(
      buildTaskUpdate(stored, {
        ...taskFormValues(stored),
        title: "Validate pump v2",
        description: "   ",
        priority: "critical",
        assignee_user_id: "",
        stage_id: "stage-2",
        start_date: "",
        due_date: "2026-11-20",
        dependency_task_ids: ["task-a"],
      }),
    ).toEqual({
      title: "Validate pump v2",
      description: null,
      priority: "critical",
      assignee_user_id: null,
      stage_id: "stage-2",
      start_date: null,
      due_date: "2026-11-20",
      dependency_task_ids: ["task-a"],
    });
  });
});
