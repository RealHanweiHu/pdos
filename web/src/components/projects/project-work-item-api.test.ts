import { describe, expect, it, vi } from "vitest";

import {
  createIssue,
  createRisk,
  createTask,
  requestProjectWorkItems,
  transitionIssue,
  transitionRisk,
  transitionTask,
} from "./project-work-item-api";

function jsonResponse(body: object, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const timestamps = {
  created_at: "2026-08-11T16:00:00Z",
  updated_at: "2026-08-11T16:00:00Z",
};

const task = {
  id: "task-1",
  project_id: "project-1",
  stage_id: null,
  parent_task_id: null,
  assignee_user_id: null,
  title: "Verify motor sample",
  description: null,
  status: "todo",
  blocked_reason: null,
  priority: "high",
  start_date: null,
  due_date: null,
  completed_at: null,
  dependency_task_ids: [],
  unresolved_dependency_ids: [],
  readiness: "ready",
  kind: "task",
  source_entity: null,
  source_entity_id: null,
  expected_output: null,
  completion_evidence_ref: null,
  ...timestamps,
};

const issue = {
  id: "issue-1",
  project_id: "project-1",
  stage_id: null,
  owner_user_id: null,
  reported_by_user_id: "user-1",
  verifier_user_id: null,
  issue_type: "engineering",
  closure_criteria: null,
  closure_evidence_ref: null,
  reopen_count: 0,
  title: "Thermal drift",
  description: null,
  status: "open",
  severity: "critical",
  root_cause: null,
  resolution: null,
  target_date: null,
  closed_at: null,
  ...timestamps,
};

const risk = {
  id: "risk-1",
  project_id: "project-1",
  owner_user_id: null,
  title: "Supplier slip",
  description: null,
  status: "open",
  likelihood: 4,
  impact: 5,
  score: 20,
  mitigation_plan: null,
  contingency_plan: null,
  target_date: null,
  closed_at: null,
  ...timestamps,
};

describe("project work-item API", () => {
  it("loads and validates all three project-scoped collections", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      if (path.endsWith("/tasks")) return jsonResponse({ items: [task] });
      if (path.endsWith("/issues")) return jsonResponse({ items: [issue] });
      if (path.endsWith("/risks")) return jsonResponse({ items: [risk] });
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(requestProjectWorkItems("project/with spaces")).resolves.toEqual({
      tasks: [task],
      issues: [issue],
      risks: [risk],
    });
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual([
      "/api/projects/project%2Fwith%20spaces/tasks",
      "/api/projects/project%2Fwith%20spaces/issues",
      "/api/projects/project%2Fwith%20spaces/risks",
    ]);
    vi.unstubAllGlobals();
  });

  it("sends minimal create and explicit lifecycle bodies", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      if (path.includes("/tasks")) return jsonResponse(task, 201);
      if (path.includes("/issues")) return jsonResponse(issue, 201);
      return jsonResponse(risk, 201);
    });
    vi.stubGlobal("fetch", fetchMock);

    await createTask("project-1", { title: task.title, priority: "high", dependency_task_ids: [] });
    await createIssue("project-1", { title: issue.title, severity: "critical" });
    await createRisk("project-1", { title: risk.title, likelihood: 4, impact: 5 });
    await transitionTask("project-1", "task-1", {
      to_status: "blocked",
      blocked_reason: "Motor sample delayed",
    });
    await transitionIssue("project-1", "issue-1", "analysis");
    await transitionRisk("project-1", "risk-1", "mitigating");

    expect(fetchMock.mock.calls.map(([, init]) => init?.body)).toEqual([
      JSON.stringify({ title: task.title, priority: "high", dependency_task_ids: [] }),
      JSON.stringify({ title: issue.title, severity: "critical" }),
      JSON.stringify({ title: risk.title, likelihood: 4, impact: 5 }),
      JSON.stringify({ to_status: "blocked", blocked_reason: "Motor sample delayed" }),
      JSON.stringify({ to_status: "analysis" }),
      JSON.stringify({ to_status: "mitigating" }),
    ]);
    vi.unstubAllGlobals();
  });

  it("parses pending_approval tasks and skips rows with unknown enum values", async () => {
    const approvalTask = { ...task, id: "task-2", status: "pending_approval", readiness: "waiting_approval" };
    const futureTask = { ...task, id: "task-3", status: "some_future_status" };
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      if (path.endsWith("/tasks")) return jsonResponse({ items: [task, approvalTask, futureTask] });
      if (path.endsWith("/issues")) return jsonResponse({ items: [issue] });
      if (path.endsWith("/risks")) return jsonResponse({ items: [risk] });
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const workItems = await requestProjectWorkItems("project-1");
    expect(workItems.tasks.map((item) => item.id)).toEqual(["task-1", "task-2"]);
    expect(workItems.tasks[1]?.status).toBe("pending_approval");
    expect(warn).toHaveBeenCalledOnce();
    warn.mockRestore();
    vi.unstubAllGlobals();
  });

  it("rejects malformed success payloads and exposes bounded server errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockImplementation(async () => jsonResponse({ items: [{ id: "broken" }] })),
    );
    await expect(requestProjectWorkItems("project-1")).rejects.toThrow("invalid Task list response");

    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        jsonResponse({ detail: { code: "TASK_DEPENDENCIES_INCOMPLETE", message: "Task is waiting for predecessors" } }, 409),
      ),
    );
    await expect(transitionTask("project-1", "task-1", { to_status: "in_progress" })).rejects.toThrow(
      "Task is waiting for predecessors",
    );
    vi.unstubAllGlobals();
  });
});
