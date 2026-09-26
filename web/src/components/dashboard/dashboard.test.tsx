import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
    project: { id: projectId, code: projectId === "project-1" ? "PRJ-001" : "PRJ-002", name: "Pump platform" },
  };
}

function riskSnapshot(items: ReturnType<typeof risk>[], visibleProjects: { id: string }[]) {
  return {
    items,
    total: items.length,
    projects: visibleProjects.map((project) => {
      const projectRisks = items.filter((risk) => risk.project_id === project.id);
      return { project_id: project.id, open_risk_count: projectRisks.length, max_score: Math.max(0, ...projectRisks.map((risk) => risk.score)) };
    }),
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

  it("loads one aggregate request for multiple projects and displays server-ranked open risks", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: projects });
      if (path === "/api/ai/brief") return jsonResponse(emptyBrief);
      if (path === "/api/dashboard/risks") return jsonResponse(riskSnapshot([
        risk("risk-2", "project-2", "Motor validation", 20),
        risk("risk-1", "project-1", "Supplier slip", 15),
      ], projects));
      throw new Error(`unexpected request: ${path}`);
    });

    render(<Dashboard />);

    expect(await screen.findByRole("heading", { name: "驾驶舱" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "项目组合" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "跨项目风险" })).toBeInTheDocument();
    expect(screen.getByText(/尚无 Finding，不能据此判断 Agent 是否可用/)).toBeInTheDocument();
    expect(screen.queryByText("Agent 正在值守")).not.toBeInTheDocument();
    const rankedRisks = screen.getAllByTestId("dashboard-risk");
    expect(rankedRisks[0]).toHaveTextContent("Motor validation");
    expect(rankedRisks[1]).toHaveTextContent("Supplier slip");
    expect(screen.getByRole("link", { name: "打开项目 PRJ-002" })).toHaveAttribute("href", "/projects?project=project-2");
    expect(within(rankedRisks[0]).getByRole("link")).toHaveAttribute("href", "/projects?project=project-2&tab=work-items");
    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/risks"))).toEqual([
      ["/api/dashboard/risks", { cache: "no-store", credentials: "same-origin" }],
    ]);
  });

  it("keeps an aggregation failure visible and retries just the aggregate", async () => {
    let unavailable = true;
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: projects });
      if (path === "/api/ai/brief") return jsonResponse(emptyBrief);
      if (path === "/api/dashboard/risks") return unavailable ? jsonResponse({}, 503) : jsonResponse(riskSnapshot([], projects));
      throw new Error(`unexpected request: ${path}`);
    });

    render(<Dashboard />);
    expect(await screen.findByText("风险聚合暂不可用")).toBeInTheDocument();
    expect(screen.queryByText("当前没有开放风险。")).not.toBeInTheDocument();
    expect(screen.getAllByText("风险待确认")).toHaveLength(2);
    unavailable = false;
    await userEvent.click(screen.getByRole("button", { name: "重新汇总" }));
    expect(await screen.findByText("当前没有开放风险。")).toBeInTheDocument();
    expect(screen.getAllByText("开放风险 0")).toHaveLength(2);
    expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/api/dashboard/risks")).toHaveLength(2);
    expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/api/projects")).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/api/ai/brief")).toHaveLength(1);
  });

  it("uses complete project summaries for counts and color even outside the top eight", async () => {
    const visibleProjects = [...projects, project("project-3", "PRJ-003")];
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: visibleProjects });
      if (path === "/api/ai/brief") return jsonResponse(emptyBrief);
      if (path === "/api/dashboard/risks") return jsonResponse({
        items: Array.from({ length: 8 }, (_, index) => risk(`risk-${index}`, "project-1", `Top risk ${index}`, 20)),
        total: 14,
        projects: [
          { project_id: "project-1", open_risk_count: 11, max_score: 20 },
          { project_id: "project-2", open_risk_count: 3, max_score: 15 },
          { project_id: "project-3", open_risk_count: 0, max_score: 0 },
        ],
      });
      throw new Error(`unexpected request: ${path}`);
    });

    render(<Dashboard />);
    expect(await screen.findByText("Top 8 · 共 14 项")).toBeInTheDocument();
    expect(screen.getAllByTestId("dashboard-risk")).toHaveLength(8);
    const firstCard = screen.getByRole("link", { name: "打开项目 PRJ-001" });
    const outsideRankingCard = screen.getByRole("link", { name: "打开项目 PRJ-002" });
    const emptyCard = screen.getByRole("link", { name: "打开项目 PRJ-003" });
    expect(within(firstCard).getByText("开放风险 11")).toBeInTheDocument();
    expect(within(outsideRankingCard).getByText("开放风险 3")).toBeInTheDocument();
    expect(outsideRankingCard.querySelector("[aria-hidden='true']")).toHaveClass("bg-destructive");
    expect(within(emptyCard).getByText("开放风险 0")).toBeInTheDocument();
    expect(emptyCard.querySelector("[aria-hidden='true']")).toHaveClass("bg-success");
    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/risks"))).toHaveLength(1);
  });

  it("does not turn a missing project summary into a green zero-risk project", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: projects });
      if (path === "/api/ai/brief") return jsonResponse(emptyBrief);
      if (path === "/api/dashboard/risks") return jsonResponse(riskSnapshot([], projects.slice(0, 1)));
      throw new Error(`unexpected request: ${path}`);
    });

    render(<Dashboard />);
    await screen.findByText("当前没有开放风险。");
    const missingCard = screen.getByRole("link", { name: "打开项目 PRJ-002" });
    expect(within(missingCard).getByText("风险待确认")).toBeInTheDocument();
    expect(missingCard.querySelector("[aria-hidden='true']")).toHaveClass("bg-muted-foreground/35");
  });

  it("renders an imported historical project without a Development Case", async () => {
    const importedProject = { ...project("project-history", "HIST-001"), development_case_id: null };
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [importedProject] });
      if (path === "/api/ai/brief") return jsonResponse(emptyBrief);
      if (path === "/api/dashboard/risks") return jsonResponse(riskSnapshot([], [importedProject]));
      throw new Error(`unexpected request: ${path}`);
    });

    render(<Dashboard />);

    expect(await screen.findByRole("link", { name: "打开项目 HIST-001" })).toBeInTheDocument();
    expect(screen.queryByText("驾驶舱暂不可用")).not.toBeInTheDocument();
  });

  it.each(["customer", "supplier"])("does not request engineering risks or AI brief for external role %s", async (role) => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse({ ...identity, user: { ...identity.user, role } });
      if (path === "/api/projects") return jsonResponse({ items: projects });
      throw new Error(`unexpected request: ${path}`);
    });

    render(<Dashboard />);
    expect(await screen.findByText("外部成员不具备工程风险视图权限。")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/risks"))).toBe(false));
    expect(fetchMock.mock.calls.some(([input]) => String(input) === "/api/ai/brief")).toBe(false);
  });

  it.each(["engineer", "quality"])("lands %s on My Work without loading dashboard risks", async (role) => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse({ ...identity, user: { ...identity.user, role } });
      if (path === "/api/projects") return jsonResponse({ items: projects });
      throw new Error(`unexpected request: ${path}`);
    });

    render(<Dashboard />);
    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith("/my-work"));
    expect(screen.queryByRole("heading", { name: "驾驶舱" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input) === "/api/dashboard/risks" || String(input) === "/api/ai/brief")).toBe(false);
  });
});
