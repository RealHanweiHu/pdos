import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Dashboard } from "./dashboard";

const { routerReplace } = vi.hoisted(() => ({ routerReplace: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: routerReplace }) }));

function jsonResponse(body: object, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const identity = {
  tenant: { id: "tenant-1", slug: "beepump", name: "Beehive Technology" },
  user: { id: "user-1", tenant_id: "tenant-1", username: "owner", display_name: "Initial Owner", role: "owner", email: null, is_active: true },
};

const emptyBrief = {
  status: "active",
  error_code: null,
  pending_review_count: 0,
  latest_finding_at: null,
  reviewed_count: 0,
  accepted_count: 0,
  applied_count: 0,
  acceptance_rate_basis_points: null,
  narrowed_output_count: 0,
  quality_controls: [],
  items: [],
};

const stages = [
  ["stage-1", "concept", "概念阶段", 1],
  ["stage-2", "planning", "规划阶段", 2],
  ["stage-3", "design", "设计阶段", 3],
  ["stage-4", "evt", "EVT 工程验证", 4],
  ["stage-5", "dvt", "DVT 设计验证", 5],
  ["stage-6", "pvt", "PVT 试产验证", 6],
  ["stage-7", "mp", "量产稳定与移交", 7],
].map(([id, code, name, sequence]) => ({ id: String(id), code: String(code), name: String(name), description: null, sequence: Number(sequence) }));

function project(id: string, code: string, currentStage = 1) {
  return {
    id,
    development_case_id: `case-${id}`,
    customer_id: null,
    workflow: { id: `workflow-${id}`, code: `npd-${id}`, name: `NPD · ${code}`, description: null, version: 1, is_active: true, stages },
    current_stage: stages[currentStage - 1],
    owner_user_id: "user-1",
    code,
    name: `${code} pump platform`,
    description: null,
    status: "active",
    start_date: "2026-08-11",
    target_date: "2027-03-31",
    created_at: "2026-08-11T16:00:00Z",
    updated_at: "2026-08-11T16:00:00Z",
  };
}

function risk(id: string, projectId: string, title: string, score: number) {
  return {
    id,
    project_id: projectId,
    owner_user_id: null,
    title,
    description: null,
    status: "open",
    likelihood: score === 20 ? 4 : 3,
    impact: 5,
    score,
    mitigation_plan: null,
    contingency_plan: null,
    target_date: null,
    closed_at: null,
    created_at: "2026-08-11T16:00:00Z",
    updated_at: "2026-08-11T16:00:00Z",
  };
}

describe("Dashboard", () => {
  const fetchMock = vi.fn<typeof fetch>();
  const projects = [project("project-1", "PRJ-001", 4), project("project-2", "PRJ-002", 2)];

  beforeEach(() => {
    fetchMock.mockReset();
    routerReplace.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders the two-card dashboard and ranks open risks by score", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: projects });
      if (path === "/api/ai/brief") return jsonResponse(emptyBrief);
      if (path === "/api/portfolio/risks") {
        return jsonResponse({
          items: [risk("risk-1", "project-1", "Supplier slip", 15), risk("risk-2", "project-2", "Motor validation", 20)],
        });
      }
      if (path === "/api/portfolio/my-tasks") return jsonResponse({ items: [] });
      throw new Error(`unexpected request: ${path}`);
    });

    render(<Dashboard />);

    expect(await screen.findByRole("heading", { name: "驾驶舱" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "项目组合" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "跨项目风险" })).toBeInTheDocument();
    const rankedRisks = screen.getAllByTestId("dashboard-risk");
    expect(rankedRisks[0]).toHaveTextContent("Motor validation");
    expect(rankedRisks[1]).toHaveTextContent("Supplier slip");
    expect(screen.getByRole("link", { name: "打开项目 PRJ-002" })).toHaveAttribute("href", "/projects?project=project-2");
    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/risks"))).toHaveLength(1);
    expect(screen.getByText("当前没有分配给你的未完成任务。")).toBeInTheDocument();
  });

  it("lists my unfinished tasks across projects and flags overdue ones", async () => {
    const base = {
      project_id: "project-2",
      stage_id: null,
      parent_task_id: null,
      assignee_user_id: "user-1",
      description: null,
      blocked_reason: null,
      priority: "high",
      start_date: null,
      completed_at: null,
      dependency_task_ids: [],
      unresolved_dependency_ids: [],
      readiness: "ready",
      created_at: "2026-08-11T16:00:00Z",
      updated_at: "2026-08-11T16:00:00Z",
    };
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: projects });
      if (path === "/api/ai/brief") return jsonResponse(emptyBrief);
      if (path === "/api/portfolio/risks") return jsonResponse({ items: [] });
      if (path === "/api/portfolio/my-tasks") {
        return jsonResponse({
          items: [
            { ...base, id: "task-1", title: "Late motor test", status: "in_progress", due_date: "2000-01-01" },
            { ...base, id: "task-2", project_id: "project-1", title: "Draft EMC plan", status: "todo", due_date: null },
          ],
        });
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<Dashboard />);
    const items = await screen.findAllByTestId("dashboard-my-task");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Late motor test");
    expect(items[0]).toHaveTextContent("PRJ-002 · 进行中");
    expect(items[0]).toHaveTextContent(/逾期 \d+ 天/);
    expect(items[1]).toHaveTextContent("无截止");
    expect(items[0].querySelector("a")).toHaveAttribute("href", "/projects?project=project-2&tab=tasks");
    expect(screen.getByText(/未完成 2/)).toHaveTextContent("未完成 2 · 逾期 1");
  });

  it("keeps a risk aggregation failure visible instead of showing zero", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: projects });
      if (path === "/api/ai/brief") return jsonResponse(emptyBrief);
      if (path.endsWith("/risks")) return jsonResponse({}, 503);
      if (path === "/api/portfolio/my-tasks") return jsonResponse({}, 503);
      throw new Error(`unexpected request: ${path}`);
    });

    render(<Dashboard />);
    expect(await screen.findByText("风险聚合暂不可用")).toBeInTheDocument();
    expect(screen.queryByText("当前没有开放风险")).not.toBeInTheDocument();
    expect(await screen.findByText("我的任务暂不可用")).toBeInTheDocument();
  });

  it("does not request engineering risks for external roles", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse({ ...identity, user: { ...identity.user, role: "customer" } });
      if (path === "/api/projects") return jsonResponse({ items: projects });
      throw new Error(`unexpected request: ${path}`);
    });

    render(<Dashboard />);
    expect(await screen.findByText("外部成员不具备工程风险视图权限。")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/risks"))).toBe(false));
    expect(screen.getByText("外部成员不具备工程任务视图权限。")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/my-tasks"))).toBe(false);
  });
});
