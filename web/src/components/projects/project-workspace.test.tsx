import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectWorkspace } from "./project-workspace";

const { routerReplace } = vi.hoisted(() => ({ routerReplace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: routerReplace }),
}));

function jsonResponse(body: object, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const identity = {
  tenant: { id: "tenant-1", slug: "beepump", name: "Beehive Technology" },
  user: {
    id: "user-1",
    tenant_id: "tenant-1",
    username: "owner",
    display_name: "Initial Owner",
    role: "owner",
    email: null,
    is_active: true,
  },
};

const stages = [
  ["stage-1", "concept", "概念阶段", 1],
  ["stage-2", "planning", "规划阶段", 2],
  ["stage-3", "design", "设计阶段", 3],
  ["stage-4", "evt", "EVT 工程验证", 4],
  ["stage-5", "dvt", "DVT 设计验证", 5],
  ["stage-6", "pvt", "PVT 试产验证", 6],
  ["stage-7", "mp", "量产稳定与移交", 7],
].map(([id, code, name, sequence]) => ({
  id: String(id),
  code: String(code),
  name: String(name),
  description: `${String(name)}说明`,
  sequence: Number(sequence),
}));

const project = {
  id: "project-1",
  development_case_id: "case-1",
  customer_id: null,
  workflow: {
    id: "workflow-1",
    code: "npd-project-1",
    name: "NPD · PRJ-001",
    description: "新产品开发七阶段基线",
    version: 1,
    is_active: true,
    stages,
  },
  current_stage: stages[0],
  owner_user_id: "user-1",
  code: "PRJ-001",
  name: "Next pump platform",
  description: "Project description",
  status: "draft",
  start_date: "2026-08-15",
  target_date: "2027-03-31",
  created_at: "2026-08-11T16:00:00Z",
  updated_at: "2026-08-11T16:00:00Z",
};

const workItemTimestamps = {
  created_at: "2026-08-11T16:00:00Z",
  updated_at: "2026-08-11T16:00:00Z",
};

const waitingTask = {
  id: "task-2",
  project_id: "project-1",
  stage_id: null,
  parent_task_id: null,
  assignee_user_id: null,
  title: "Integrate validation fixture",
  description: null,
  status: "todo",
  blocked_reason: null,
  priority: "high",
  start_date: null,
  due_date: null,
  completed_at: null,
  dependency_task_ids: ["task-1"],
  unresolved_dependency_ids: ["task-1"],
  readiness: "waiting",
  ...workItemTimestamps,
};

const foundationTask = {
  ...waitingTask,
  id: "task-1",
  title: "Prepare motor validation fixture",
  priority: "high",
  dependency_task_ids: [],
  unresolved_dependency_ids: [],
  readiness: "ready",
};

const openIssue = {
  id: "issue-1",
  project_id: "project-1",
  stage_id: null,
  owner_user_id: null,
  reported_by_user_id: "user-1",
  title: "Thermal drift",
  description: null,
  status: "open",
  severity: "critical",
  root_cause: null,
  resolution: null,
  target_date: null,
  closed_at: null,
  ...workItemTimestamps,
};

const openRisk = {
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
  ...workItemTimestamps,
};

function workItemResponse(path: string) {
  if (path.endsWith("/tasks")) return jsonResponse({ items: [waitingTask] });
  if (path.endsWith("/issues")) return jsonResponse({ items: [openIssue] });
  if (path.endsWith("/risks")) return jsonResponse({ items: [openRisk] });
  return null;
}

describe("ProjectWorkspace", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    fetchMock.mockReset();
    routerReplace.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    window.history.replaceState({}, "", "/");
    vi.unstubAllGlobals();
  });

  it("loads an accessible empty state", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [] });
      throw new Error(`unexpected request: ${path}`);
    });

    render(<ProjectWorkspace />);

    expect(await screen.findByRole("heading", { name: "项目工作区" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "还没有项目" })).toBeInTheDocument();
  });

  it("renders the seven-stage timeline and edits with a minimal PATCH", async () => {
    const user = userEvent.setup();
    const updated = { ...project, name: "Updated pump platform" };
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects" && !init?.method) {
        return jsonResponse({ items: [project] });
      }
      if (path === "/api/projects/project-1" && init?.method === "PATCH") {
        return jsonResponse(updated);
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<ProjectWorkspace />);
    await user.click(await screen.findByRole("button", { name: "打开项目 PRJ-001" }));

    await user.click(screen.getByRole("tab", { name: "时间线" }));
    expect(screen.getByRole("region", { name: "项目阶段 Timeline" })).toBeInTheDocument();
    for (const stage of stages) expect(screen.getAllByText(stage.name).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("tab", { name: "概览" }));
    const name = screen.getByLabelText("项目名称");
    await user.clear(name);
    await user.type(name, "Updated pump platform");
    await user.click(screen.getByRole("button", { name: "保存更改" }));

    expect(await screen.findByRole("status")).toHaveTextContent("项目已更新");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/project-1",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ name: "Updated pump platform" }),
      }),
    );
  });

  it("uses explicit status and adjacent-stage actions", async () => {
    const user = userEvent.setup();
    const active = { ...project, status: "active" };
    const planning = { ...active, current_stage: stages[1] };
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects" && !init?.method) return jsonResponse({ items: [project] });
      if (path.endsWith("/stage-transitions")) return jsonResponse(planning);
      if (path.endsWith("/transitions")) return jsonResponse(active);
      throw new Error(`unexpected request: ${path}`);
    });

    render(<ProjectWorkspace />);
    await user.click(await screen.findByRole("button", { name: "打开项目 PRJ-001" }));
    await user.click(screen.getByRole("button", { name: "提交立项" }));

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/project-1/transitions",
      expect.objectContaining({ body: JSON.stringify({ to_status: "proposed" }) }),
    );
    await user.click(screen.getByRole("button", { name: "推进到规划阶段" }));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/project-1/stage-transitions",
      expect.objectContaining({ body: JSON.stringify({ to_stage_id: "stage-2" }) }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("当前阶段已推进到规划阶段");
  });

  it("allows member viewers to inspect timeline without write controls", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") {
        return jsonResponse({ ...identity, user: { ...identity.user, role: "engineer" } });
      }
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      throw new Error(`unexpected request: ${path}`);
    });

    render(<ProjectWorkspace />);
    await user.click(await screen.findByRole("button", { name: "打开项目 PRJ-001" }));

    await user.click(screen.getByRole("tab", { name: "时间线" }));
    expect(screen.getByRole("region", { name: "项目阶段 Timeline" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "编辑项目" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "提交立项" })).not.toBeInTheDocument();
  });

  it("renders the five internal tabs and keeps dependency waiting distinct from blocked", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      const response = workItemResponse(path);
      if (response) return response;
      throw new Error(`unexpected request: ${path}`);
    });

    render(<ProjectWorkspace />);
    await user.click(await screen.findByRole("button", { name: "打开项目 PRJ-001" }));

    expect(await screen.findAllByRole("tab")).toHaveLength(5);
    expect(screen.getByRole("tab", { name: "概览" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("1", { selector: "[data-metric='task']" })).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "任务" }));
    expect(screen.getAllByText("Integrate validation fixture")).toHaveLength(2);
    expect(screen.getByText("等待前置")).toBeInTheDocument();
    expect(screen.queryByText("已阻塞", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "开始任务" })).not.toBeInTheDocument();
  });

  it("creates work items and advances only explicit lifecycle actions", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path.endsWith("/tasks") && init?.method === "POST") {
        return jsonResponse({ ...waitingTask, id: "task-3", title: "Review DVT report", dependency_task_ids: [], unresolved_dependency_ids: [], readiness: "ready" }, 201);
      }
      if (path.endsWith("/issues/issue-1/transitions")) {
        return jsonResponse({ ...openIssue, status: "analysis" });
      }
      const response = workItemResponse(path);
      if (response) return response;
      throw new Error(`unexpected request: ${path}`);
    });

    render(<ProjectWorkspace />);
    await user.click(await screen.findByRole("button", { name: "打开项目 PRJ-001" }));
    await screen.findByRole("tab", { name: "任务" });
    await user.click(screen.getByRole("tab", { name: "任务" }));
    await user.type(screen.getByLabelText("任务标题"), "Review DVT report");
    await user.click(screen.getByRole("button", { name: "创建任务" }));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/project-1/tasks",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ title: "Review DVT report", priority: "medium", dependency_task_ids: [] }),
      }),
    );

    await user.click(screen.getByRole("tab", { name: "问题" }));
    await user.click(screen.getByRole("button", { name: "进入分析" }));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/project-1/issues/issue-1/transitions",
      expect.objectContaining({ body: JSON.stringify({ to_status: "analysis" }) }),
    );
  });

  it("refreshes sibling readiness after a predecessor is completed", async () => {
    const user = userEvent.setup();
    let transitionCount = 0;
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path.endsWith("/tasks") && !init?.method) {
        const dependent = transitionCount === 2
          ? { ...waitingTask, unresolved_dependency_ids: [], readiness: "ready" }
          : waitingTask;
        const foundation = transitionCount === 0
          ? foundationTask
          : { ...foundationTask, status: transitionCount === 1 ? "in_progress" : "done", readiness: transitionCount === 1 ? "ready" : "complete" };
        return jsonResponse({ items: [dependent, foundation] });
      }
      if (path.endsWith("/issues")) return jsonResponse({ items: [] });
      if (path.endsWith("/risks")) return jsonResponse({ items: [] });
      if (path.endsWith("/tasks/task-1/transitions")) {
        transitionCount += 1;
        return jsonResponse({
          ...foundationTask,
          status: transitionCount === 1 ? "in_progress" : "done",
          readiness: transitionCount === 1 ? "ready" : "complete",
        });
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<ProjectWorkspace />);
    await user.click(await screen.findByRole("button", { name: "打开项目 PRJ-001" }));
    await user.click(await screen.findByRole("tab", { name: "任务" }));
    await user.click(screen.getByRole("button", { name: "开始任务" }));
    await user.click(await screen.findByRole("button", { name: "完成任务" }));

    await waitFor(() => expect(screen.queryByText("等待前置")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "开始任务" })).toBeInTheDocument();
  });

  it("does not expose or request work items for external project members", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") {
        return jsonResponse({ ...identity, user: { ...identity.user, role: "supplier" } });
      }
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      throw new Error(`unexpected request: ${path}`);
    });

    render(<ProjectWorkspace />);
    await user.click(await screen.findByRole("button", { name: "打开项目 PRJ-001" }));

    expect(screen.getAllByRole("tab")).toHaveLength(2);
    expect(screen.queryByRole("tab", { name: "任务" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => /\/(tasks|issues|risks)$/.test(String(input)))).toBe(false);
  });

  it("opens the project selected by the dashboard deep link", async () => {
    window.history.replaceState({}, "", "/projects?project=project-1");
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      const response = workItemResponse(path);
      if (response) return response;
      throw new Error(`unexpected request: ${path}`);
    });

    render(<ProjectWorkspace />);

    expect(await screen.findByRole("heading", { name: "Next pump platform" })).toBeInTheDocument();
    await waitFor(() => expect(fetchMock.mock.calls.filter(([input]) => /\/(tasks|issues|risks)$/.test(String(input)))).toHaveLength(3));
  });

  it("redirects expired sessions and retries load failures", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({}, 401));
    const first = render(<ProjectWorkspace />);
    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith("/login"));
    first.unmount();

    const user = userEvent.setup();
    let unavailable = true;
    fetchMock.mockReset();
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") {
        return unavailable ? jsonResponse({}, 503) : jsonResponse({ items: [] });
      }
      throw new Error(`unexpected request: ${path}`);
    });
    render(<ProjectWorkspace />);
    expect(await screen.findByRole("heading", { name: "项目暂不可用" })).toBeInTheDocument();
    unavailable = false;
    await user.click(screen.getByRole("button", { name: "重新加载" }));
    expect(await screen.findByRole("heading", { name: "项目工作区" })).toBeInTheDocument();
  });
});
