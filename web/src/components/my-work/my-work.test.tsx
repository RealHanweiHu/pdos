import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MyWork } from "./my-work";

const { routerReplace } = vi.hoisted(() => ({ routerReplace: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: routerReplace }) }));

function jsonResponse(body: object, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const identity = {
  tenant: { id: "tenant-1", slug: "beepump", name: "Beehive Technology" },
  user: {
    id: "user-1",
    tenant_id: "tenant-1",
    username: "engineer",
    display_name: "Engineer",
    role: "engineer",
    email: null,
    is_active: true,
  },
};

const alpha = { id: "project-1", code: "PRJ-001", name: "Pump platform" };
const beta = { id: "project-2", code: "PRJ-002", name: "Charger platform" };

const emptyCounts = {
  tasks: 0,
  issues: 0,
  risks: 0,
  capa_actions: 0,
  gate_signoffs: 0,
  findings: 0,
};

const emptyWork = {
  tasks: [],
  issues: [],
  risks: [],
  capa_actions: [],
  gate_signoffs: [],
  findings: [],
  counts: emptyCounts,
};

const populatedWork = {
  ...emptyWork,
  tasks: [
    {
      id: "task-1",
      project: beta,
      title: "Verify motor sample",
      status: "in_progress",
      priority: "high",
      due_date: "2020-01-01",
    },
    {
      id: "task-2",
      project: alpha,
      title: "Freeze requirements",
      status: "todo",
      priority: "medium",
      due_date: null,
    },
  ],
  issues: [
    {
      id: "issue-1",
      project: alpha,
      title: "Thermal drift",
      status: "verification",
      severity: "critical",
      target_date: "2099-09-05",
    },
  ],
  gate_signoffs: [
    {
      id: "signoff-1",
      project: alpha,
      gate_id: "gate-1",
      gate_code: "dvt-exit",
      gate_name: "DVT Exit",
      slot: "engineering",
      requirement: "required",
      round_number: 2,
      review_due_at: null,
    },
  ],
  findings: [
    {
      id: "finding-1",
      project: beta,
      finding_type: "supplier_delay_risk",
      title: "Register delivery risk",
      created_at: "2026-08-25T08:00:00Z",
    },
  ],
  counts: { ...emptyCounts, tasks: 3, issues: 1, gate_signoffs: 1, findings: 1 },
};

describe("MyWork", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    fetchMock.mockReset();
    routerReplace.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  const emptyNotifications = { items: [], unread_count: 0, digest: [] };

  function mockApis(work: object, workStatus = 200, notifications: object = emptyNotifications) {
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/product-work/my-work") return jsonResponse({ research: [], work_items: [], experiments: [], strategies: [], definitions: [] });
      if (path === "/api/me/work") return jsonResponse(work, workStatus);
      if (path === "/api/me/notifications" && !init?.method) return jsonResponse(notifications, workStatus);
      if (path.endsWith("/ack") && init?.method === "POST") return jsonResponse({});
      throw new Error(`unexpected request: ${path}`);
    });
  }

  it("renders assigned sections with exact deep links, priority anchors, badges, and loaded counts", async () => {
    mockApis(populatedWork);

    render(<MyWork />);

    expect(await screen.findByRole("heading", { name: "今天由我负责什么" })).toBeInTheDocument();
    const taskLink = within(screen.getByRole("region", { name: "任务" })).getByRole("link", { name: /Verify motor sample/ });
    expect(taskLink).toHaveAttribute("href", "/projects?project=project-2&tab=work-items&entity_id=task-1");
    expect(taskLink).toHaveTextContent("逾期");
    expect(screen.getByRole("region", { name: "立项前工作" }).closest("main")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "问题" })).getByRole("link", { name: /Thermal drift/ })).toHaveAttribute(
      "href",
      "/projects?project=project-1&tab=work-items&entity_id=issue-1",
    );
    expect(screen.getByRole("link", { name: /DVT Exit · 第 2 轮/ })).toHaveAttribute(
      "href",
      "/projects?project=project-1&tab=gates",
    );
    expect(within(screen.getByRole("region", { name: "AI 建议待审／待应用" })).getByRole("link", { name: /Register delivery risk/ })).toHaveAttribute(
      "href",
      "/ai-review?finding=finding-1",
    );
    expect(within(screen.getByRole("region", { name: "任务" })).getByText("共 3 条，已加载 2 条。")).toBeInTheDocument();
    const priorityLink = within(screen.getByRole("region", { name: "工作优先事项" })).getByRole("link", { name: /Verify motor sample/ });
    expect(priorityLink).toHaveAttribute("href", "#work-task-task-1");
    expect(taskLink.closest("li")).toHaveAttribute("id", "work-task-task-1");
    expect(screen.queryByRole("region", { name: "风险" })).not.toBeInTheDocument();
  });

  it("shows the guided empty state when nothing is assigned", async () => {
    mockApis(emptyWork);

    render(<MyWork />);

    expect(
      await screen.findByRole("heading", { name: "当前没有分派给你的项目执行待办" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "浏览项目" })).toHaveAttribute("href", "/projects");
  });

  it("keeps malformed rows out without failing the page", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    mockApis({
      ...populatedWork,
      tasks: [...populatedWork.tasks, { id: "broken" }],
    });

    render(<MyWork />);

    expect(within(await screen.findByRole("region", { name: "任务" })).getByRole("link", { name: /Verify motor sample/ })).toBeInTheDocument();
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it("shows fired notifications with acknowledge buttons", async () => {
    mockApis(emptyWork, 200, {
      items: [
        {
          id: "reminder-1",
          project: alpha,
          policy_key: "task_due_overdue3",
          target_entity: "task",
          target_entity_id: "task-1",
          title: "任务已逾期 3 天：Verify motor sample",
          status: "fired",
          escalation_level: 1,
          fire_at: "2026-09-13T00:00:00Z",
          fired_at: "2026-09-13T01:00:00Z",
          acknowledged_at: null,
        },
      ],
      unread_count: 1,
      digest: [{ policy_key: "task_due_overdue3", count: 1 }],
    });

    render(<MyWork />);

    await userEvent.click(await screen.findByRole("button", { name: "展开通知" }));
    expect(await screen.findByText("任务已逾期 3 天：Verify motor sample")).toBeInTheDocument();
    expect(screen.getByText("未读 1")).toBeInTheDocument();
    expect(screen.getByText("升级")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "知道了" })).toBeInTheDocument();
  });

  it("renders the restricted state for external roles", async () => {
    mockApis({ detail: { code: "MY_WORK_FORBIDDEN" } }, 403);

    render(<MyWork />);

    expect(
      await screen.findByRole("heading", { name: "此角色没有个人工作台" }),
    ).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/product-work/"))).toBe(false);
  });

  it("waits for work data but does not let slow notifications block actionable work", async () => {
    let resolveWork!: (response: Response) => void;
    let resolveNotifications!: (response: Response) => void;
    const workResponse = new Promise<Response>((resolve) => { resolveWork = resolve; });
    const notificationResponse = new Promise<Response>((resolve) => { resolveNotifications = resolve; });
    fetchMock.mockImplementation(async (input) => {
      if (String(input) === "/api/session/me") return jsonResponse(identity);
      if (String(input) === "/api/product-work/my-work") return jsonResponse({ research: [], work_items: [], experiments: [], strategies: [], definitions: [] });
      if (String(input) === "/api/me/work") return workResponse;
      if (String(input) === "/api/me/notifications") return notificationResponse;
      throw new Error("unexpected request");
    });
    render(<MyWork />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(screen.queryByTestId("my-work-ready")).not.toBeInTheDocument();
    await act(async () => { resolveWork(jsonResponse(populatedWork)); });
    expect(within(await screen.findByRole("region", { name: "任务" })).getByRole("link", { name: /Verify motor sample/ })).toBeInTheDocument();
    expect(screen.getByText("正在加载站内通知…")).toBeInTheDocument();
    await act(async () => { resolveNotifications(jsonResponse(emptyNotifications)); });
    expect(screen.queryByText("正在加载站内通知…")).not.toBeInTheDocument();
  });

  it("shows and retries a notification error without refetching identity or assigned work", async () => {
    let unavailable = true;
    fetchMock.mockImplementation(async (input) => {
      if (String(input) === "/api/session/me") return jsonResponse(identity);
      if (String(input) === "/api/product-work/my-work") return jsonResponse({ research: [], work_items: [], experiments: [], strategies: [], definitions: [] });
      if (String(input) === "/api/me/work") return jsonResponse(populatedWork);
      if (String(input) === "/api/me/notifications") return jsonResponse(emptyNotifications, unavailable ? 503 : 200);
      throw new Error("unexpected request");
    });
    render(<MyWork />);
    expect(within(await screen.findByRole("region", { name: "任务" })).getByRole("link", { name: /Verify motor sample/ })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("站内通知暂不可用");
    unavailable = false;
    await userEvent.click(screen.getByRole("button", { name: "重新加载通知" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/api/me/notifications")).toHaveLength(2);
    expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/api/me/work")).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/api/session/me")).toHaveLength(1);
  });

  it("does not claim readiness when assigned work fails even if notifications succeed", async () => {
    fetchMock.mockImplementation(async (input) => {
      if (String(input) === "/api/session/me") return jsonResponse(identity);
      if (String(input) === "/api/product-work/my-work") return jsonResponse({ research: [], work_items: [], experiments: [], strategies: [], definitions: [] });
      if (String(input) === "/api/me/work") return jsonResponse({}, 503);
      if (String(input) === "/api/me/notifications") return jsonResponse(emptyNotifications);
      throw new Error("unexpected request");
    });
    render(<MyWork />);
    expect(await screen.findByRole("heading", { name: "我的工作暂不可用" })).toBeInTheDocument();
    expect(screen.queryByTestId("my-work-ready")).not.toBeInTheDocument();
  });

  it("keeps 200 notifications folded with the full unread count while assigned tasks are reachable", async () => {
    mockApis(populatedWork, 200, {
      items: Array.from({ length: 200 }, (_, index) => ({ id: `reminder-${index}`, project: alpha, policy_key: "task_due", target_entity: "task", target_entity_id: `task-${index}`, title: `提醒 ${index}`, status: "fired", escalation_level: 0, fire_at: "2026-09-08T12:00:00Z", fired_at: "2026-09-08T12:00:00Z", acknowledged_at: null })),
      unread_count: 200,
      digest: [],
    });
    render(<MyWork />);
    expect(within(await screen.findByRole("region", { name: "任务" })).getByRole("link", { name: /Verify motor sample/ })).toBeInTheDocument();
    expect(screen.getByText("未读 200")).toBeInTheDocument();
    expect(screen.queryByText("提醒 0")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "展开通知" }));
    expect(screen.getAllByRole("button", { name: "知道了" })).toHaveLength(200);
    await userEvent.click(screen.getByRole("button", { name: "收起通知" }));
    expect(screen.queryByText("提醒 0")).not.toBeInTheDocument();
    expect(screen.getByText("未读 200")).toBeInTheDocument();
  });

  it.each(["success", "failure"])("ignores an earlier notification %s that settles after a successful full-page retry", async (lateResult) => {
    let resolveOldNotifications!: (response: Response) => void;
    const oldNotifications = new Promise<Response>((resolve) => { resolveOldNotifications = resolve; });
    let workCalls = 0;
    let notificationCalls = 0;
    fetchMock.mockImplementation(async (input) => {
      if (String(input) === "/api/session/me") return jsonResponse(identity);
      if (String(input) === "/api/product-work/my-work") return jsonResponse({ research: [], work_items: [], experiments: [], strategies: [], definitions: [] });
      if (String(input) === "/api/me/work") return ++workCalls === 1 ? jsonResponse({}, 503) : jsonResponse(populatedWork);
      if (String(input) === "/api/me/notifications") return ++notificationCalls === 1 ? oldNotifications : jsonResponse(emptyNotifications);
      throw new Error("unexpected request");
    });
    render(<MyWork />);
    await userEvent.click(await screen.findByRole("button", { name: "重新加载" }));
    expect(within(await screen.findByRole("region", { name: "任务" })).getByRole("link", { name: /Verify motor sample/ })).toBeInTheDocument();
    await act(async () => {
      resolveOldNotifications(lateResult === "failure" ? jsonResponse({}, 503) : jsonResponse({ items: [], unread_count: 99, digest: [] }));
    });
    expect(screen.queryByText("未读 99")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText("正在加载站内通知…")).not.toBeInTheDocument();
  });
});
