import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectWorkspace } from "./project-workspace";
import { resolveTab } from "./project-workspace-view";

const { routerReplace } = vi.hoisted(() => ({ routerReplace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: routerReplace }),
  useSearchParams: () => new URLSearchParams(window.location.search),
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
  stage_id: "stage-2",
  parent_task_id: null,
  assignee_user_id: null,
  title: "Integrate validation fixture",
  description: "完成验证治具集成，并记录接口与验收结果。",
  status: "todo",
  blocked_reason: null,
  priority: "high",
  start_date: "2026-08-18",
  due_date: "2026-08-22",
  completed_at: null,
  dependency_task_ids: ["task-1"],
  unresolved_dependency_ids: ["task-1"],
  readiness: "waiting",
  kind: "task",
  source_entity: null,
  source_entity_id: null,
  expected_output: null,
  completion_evidence_ref: null,
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
  kind: "task",
  source_entity: null,
  source_entity_id: null,
  expected_output: null,
  completion_evidence_ref: null,
};

const openIssue = {
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

const specification = {
  id: "specification-1",
  project_id: "project-1",
  created_by_user_id: "user-1",
  requirement_id: null,
  owner_user_id: null,
  verification_method: null,
  acceptance_criteria: null,
  criticality: "standard",
  code: "SPEC-C4S",
  title: "C4s performance specification",
  version: 1,
  content: { rated_pressure_kpa: 1034 },
  ...workItemTimestamps,
};

const developmentBom = {
  id: "bom-1",
  project_id: "project-1",
  specification_id: "specification-1",
  created_by_user_id: "user-1",
  bom_type: "ebom",
  code: "C4S-EBOM",
  name: "C4s engineering BOM",
  version: 1,
  notes: null,
  items: [],
  ...workItemTimestamps,
};

const erpReference = {
  id: "erp-reference-1",
  project_id: "project-1",
  bom_id: "bom-1",
  reference_type: "routing",
  source_system: "ERP",
  external_id: "ROUTING-9001",
  external_url: null,
  metadata: {},
  created_at: workItemTimestamps.created_at,
};

const projectGate = {
  id: "gate-1",
  project_id: "project-1",
  stage: { id: "stage-1", code: "concept", name: "概念阶段", sequence: 1 },
  code: "concept",
  name: "Concept Gate",
  status: "preparing",
  review_due_at: null,
  decided_at: null,
  decided_by_user_id: null,
  is_current: true,
  round: null,
  readiness: {
    ready: false,
    blocker_keys: ["deliverable_check:1", "risk:1"],
    blockers: [
      { key: "deliverable_check:1", kind: "deliverable_check", label: "确认概念评审材料" },
      { key: "risk:1", kind: "risk", label: "供应商交期风险" },
    ],
    evaluated_at: "2026-08-12T16:00:00Z",
  },
  additions: [],
  grandfather_exemptions: [],
};

const projectDocument = {
  document_id: "document-1",
  project_id: "project-1",
  filename: "concept-review.pdf",
  media_type: "application/pdf",
  classification: "internal",
  size_bytes: 2048,
  sha256: "a".repeat(64),
  extraction_status: "extracted",
  created_at: "2026-08-12T16:00:00Z",
};

const complaint = {
  id: "complaint-1",
  project_id: "project-1",
  customer_id: null,
  reported_by_user_id: "user-1",
  verifier_user_id: null,
  issue_type: "engineering",
  closure_criteria: null,
  closure_evidence_ref: null,
  reopen_count: 0,
  owner_user_id: "user-1",
  closed_by_user_id: null,
  code: "CMP-C4S",
  title: "现场连接器间歇开路",
  description: "热循环后接触电阻超限。",
  source: "field",
  severity: "high",
  status: "triaged",
  occurred_at: "2026-08-12T08:00:00Z",
  reported_at: "2026-08-12T10:00:00Z",
  customer_reference: null,
  affected_scope: "Lot C4s",
  document_refs: [],
  resolution_summary: null,
  closed_at: null,
  ...workItemTimestamps,
};

const ncr = {
  id: "ncr-1",
  project_id: "project-1",
  complaint_id: "complaint-1",
  owner_user_id: "user-1",
  created_by_user_id: "user-1",
  preventive_disposition_approved_by_user_id: null,
  closed_by_user_id: null,
  code: "NCR-C4S",
  nonconformity: "接触电阻超限",
  requirement_reference: "SPEC-ELEC-04",
  severity: "high",
  status: "root_cause",
  target_date: "2026-08-22",
  containment_action: "隔离批次",
  containment_completed_at: "2026-08-12T11:00:00Z",
  affected_quantity: 24,
  affected_scope: "Lot C4s",
  preventive_not_applicable_reason: null,
  preventive_disposition_approved_at: null,
  effectiveness_criteria: null,
  observation_due_at: null,
  closed_at: null,
  ...workItemTimestamps,
};

function workItemResponse(path: string) {
  if (path.endsWith("/tasks")) return jsonResponse({
    items: [waitingTask, { ...foundationTask, status: "done", readiness: "complete", completed_at: "2026-08-17T16:00:00Z" }],
  });
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

    expect(window.location.search).toBe("?project=project-1&tab=overview");
    expect(screen.queryByLabelText("项目名称")).not.toBeInTheDocument();
    // The timeline is part of the control tower now, not a tab of its own.
    expect(screen.getByRole("region", { name: "项目阶段 Timeline" })).toBeInTheDocument();
    for (const stage of stages) expect(screen.getAllByText(stage.name).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "编辑项目" }));
    const name = screen.getByLabelText("项目名称");
    await user.clear(name);
    await user.type(name, "Updated pump platform");
    await user.click(screen.getByRole("button", { name: "保存更改" }));

    await waitFor(() =>
      expect(
        screen.getAllByRole("status").some((node) => node.textContent?.includes("项目已更新")),
      ).toBe(true),
    );
    expect(screen.queryByLabelText("项目名称")).not.toBeInTheDocument();
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
    await waitFor(() =>
      expect(
        screen
          .getAllByRole("status")
          .some((node) => node.textContent?.includes("当前阶段已推进到规划阶段")),
      ).toBe(true),
    );
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

    expect(screen.getByRole("region", { name: "项目阶段 Timeline" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "编辑项目" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "提交立项" })).not.toBeInTheDocument();
  });

  it("opens the implemented planning domain from the overview without loading unrelated work", async () => {
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
    expect(screen.queryByRole("region", { name: "计划与资源办理" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "办理计划与资源" }));
    expect(await screen.findByRole("region", { name: "计划与资源办理" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "计划·资源" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("heading", { name: "滚动预测与预测偏差" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "四时间对照与独立承诺" })).toBeInTheDocument();
    expect(screen.queryByText(/本域的数据面将在/)).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/execution/forecasts"))).toBe(false);
  });

  it("restores project and domain through browser history without refetching the project directory", async () => {
    window.history.replaceState({}, "", "/projects?project=project-1&tab=overview&event_id=41");
    const second = { ...project, id: "project-2", code: "PRJ-002", name: "Second project" };
    fetchMock.mockImplementation(async input => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project, second] });
      if (path.endsWith("/activity")) return jsonResponse({ items: [] });
      return workItemResponse(path) ?? jsonResponse({ items: [] });
    });
    render(<ProjectWorkspace />);
    await userEvent.click(await screen.findByRole("tab", { name: "计划·资源" }));
    expect(window.location.search).toBe("?project=project-1&tab=plan");
    await userEvent.click(screen.getByRole("button", { name: "切换项目（2）" }));
    await userEvent.click(screen.getByRole("button", { name: "打开项目 PRJ-002" }));
    expect(await screen.findByRole("heading", { name: "Second project" })).toBeInTheDocument();
    await act(async () => { window.history.back(); });
    await waitFor(() => expect(screen.getByRole("tab", { name: "计划·资源" })).toHaveAttribute("aria-selected", "true"));
    expect(screen.getByRole("heading", { name: project.name })).toBeInTheDocument();
    await act(async () => { window.history.back(); });
    await waitFor(() => expect(screen.getByRole("tab", { name: "概览·控制塔" })).toHaveAttribute("aria-selected", "true"));
    expect(new URLSearchParams(window.location.search).get("event_id")).toBe("41");
    await act(async () => { window.history.forward(); });
    await waitFor(() => expect(screen.getByRole("tab", { name: "计划·资源" })).toHaveAttribute("aria-selected", "true"));
    expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/api/projects")).toHaveLength(1);
  });

  it("follows a same-page deep link and removes stale project content for an unavailable target", async () => {
    window.history.replaceState({}, "", "/projects?project=project-1&tab=overview");
    fetchMock.mockImplementation(async input => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path.endsWith("/activity")) return jsonResponse({ items: [] });
      return workItemResponse(path) ?? jsonResponse({ items: [] });
    });
    const view = render(<ProjectWorkspace />);
    await screen.findByRole("region", { name: "项目概览" });
    window.history.pushState(null, "", "/projects?project=project-1&tab=work-items&entity_id=task-2");
    // Next's search-parameter subscription rerenders the mounted workspace.
    view.rerender(<ProjectWorkspace />);
    await waitFor(() => expect(screen.getByRole("tab", { name: "工作项" })).toHaveAttribute("aria-selected", "true"));
    expect(await screen.findByText("完成验证治具集成，并记录接口与验收结果。")).toBeVisible();
    window.history.pushState(null, "", "/projects?tab=plan");
    view.rerender(<ProjectWorkspace />);
    await waitFor(() => expect(screen.getByRole("tab", { name: "计划·资源" })).toHaveAttribute("aria-selected", "true"));
    expect(new URLSearchParams(window.location.search).get("project")).toBe(project.id);
    window.history.pushState(null, "", "/projects?project=unavailable&tab=work-items");
    view.rerender(<ProjectWorkspace />);
    await waitFor(() => expect(screen.queryByRole("region", { name: "项目详情" })).not.toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent("原链接的项目不存在或当前无权读取");
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/unavailable/"))).toBe(false);
  });

  it("resolves old planning references while preserving explicit unrelated tabs and legacy timeline", () => {
    const refs = ["forecast=x", "commitment_node=x", "cross_proposal=x", "schedule_responsibility_node=x", "resource_allocation_id=x", "resource_reservation_id=x", "reservation_node_id=x", "reservation_owner_id=x", "approval_request_kind=baseline&approval_request_id=x", "approval_policy_kind=commitment&approval_policy_id=x"];
    for (const ref of refs) {
      expect(resolveTab("overview", new URLSearchParams(ref))).toBe("plan");
      expect(resolveTab("quality", new URLSearchParams(ref))).toBe("quality");
    }
    expect(resolveTab("overview", new URLSearchParams(), "#schedule-forecasts")).toBe("plan");
    expect(resolveTab("overview", new URLSearchParams("intake_proposal=x"))).toBe("overview");
    expect(resolveTab("timeline", new URLSearchParams("event_id=1"))).toBe("overview");
    expect(resolveTab("unrecognized", new URLSearchParams("forecast=x"))).toBeNull();
  });

  it("renders the internal tabs and keeps dependency waiting distinct from blocked", async () => {
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

    // D9/D31: nine manufacturing domains, not one tab per table.
    expect(await screen.findAllByRole("tab")).toHaveLength(9);
    expect(screen.getByRole("tab", { name: "计划·资源" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "工程·变更" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "试制·测试·质量" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "概览·控制塔" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("1", { selector: "[data-metric='task']" })).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "工作项" }));
    expect(screen.getAllByText("Integrate validation fixture")).toHaveLength(2);
    expect(screen.getByText("等待前置")).toBeInTheDocument();
    expect(screen.queryByText("已阻塞", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "开始任务" })).not.toBeInTheDocument();

    expect(screen.queryByText("完成验证治具集成，并记录接口与验收结果。")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "查看任务详情 Integrate validation fixture" }));
    expect(screen.getByText("完成验证治具集成，并记录接口与验收结果。")).toBeInTheDocument();
    expect(screen.getAllByText("规划阶段").length).toBeGreaterThan(0);
    expect(screen.getByText("2026-08-18 → 2026-08-22")).toBeInTheDocument();
    expect(screen.getAllByText("Prepare motor validation fixture").length).toBeGreaterThan(0);
  });

  it("loads exception-first Gate readiness and private document metadata lazily", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path.endsWith("/gates")) return jsonResponse({ items: [projectGate] });
      if (path.endsWith("/documents")) return jsonResponse({ items: [projectDocument] });
      const response = workItemResponse(path);
      if (response) return response;
      throw new Error(`unexpected request: ${path}`);
    });

    render(<ProjectWorkspace />);
    await user.click(await screen.findByRole("button", { name: "打开项目 PRJ-001" }));
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/gates"))).toBe(false);

    await user.click(screen.getByRole("tab", { name: "Gate·交付物" }));
    expect(await screen.findByRole("heading", { name: "2 个例外需要处理" })).toBeInTheDocument();
    expect(screen.getByText("确认概念评审材料")).toBeInTheDocument();
    expect(screen.getByText("交付检查项")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "查看文档" })).toBeInTheDocument();
    expect(screen.queryByText("供应商交期风险")).not.toBeVisible();
    await user.click(screen.getByRole("button", { name: "展开其余 1 项" }));
    expect(screen.getByText("供应商交期风险")).toBeVisible();
    expect(screen.getByText("高风险")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "查看风险" }));
    expect(screen.getByRole("tab", { name: "工作项" })).toHaveAttribute("aria-selected", "true");

    await user.click(screen.getByRole("tab", { name: "Gate·交付物" }));

    await user.click(screen.getByRole("tab", { name: "文档·知识" }));
    expect(await screen.findByText("concept-review.pdf")).toBeInTheDocument();
    expect(screen.getByText(/已抽取/)).toBeInTheDocument();
    expect(screen.queryByText(/object_key/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存资料" })).toBeDisabled();
  });

  it("lets an authorized project owner open the missing Gate signoff round", async () => {
    const user = userEvent.setup();
    const roundMissingGate = {
      ...projectGate,
      readiness: {
        ...projectGate.readiness,
        blocker_keys: ["round:not_open"],
        blockers: [{ key: "round:not_open", kind: "round", label: "Gate signoff round is not open" }],
      },
    };
    const openedGate = {
      ...roundMissingGate,
      status: "reviewing",
      round: {
        id: "round-1",
        round_number: 1,
        status: "open",
        signoffs: [{ slot: "product", requirement: "required", status: "pending" }],
      },
      readiness: {
        ...roundMissingGate.readiness,
        blocker_keys: ["signoff:product"],
        blockers: [{ key: "signoff:product", kind: "signoff", label: "product signoff is incomplete" }],
      },
    };
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path.endsWith("/gates") && !init?.method) return jsonResponse({ items: [roundMissingGate] });
      if (path.endsWith("/gates/gate-1/rounds") && init?.method === "POST") {
        return jsonResponse(openedGate, 201);
      }
      const response = workItemResponse(path);
      if (response) return response;
      throw new Error(`unexpected request: ${path}`);
    });

    render(<ProjectWorkspace />);
    await user.click(await screen.findByRole("button", { name: "打开项目 PRJ-001" }));
    await user.click(screen.getByRole("tab", { name: "Gate·交付物" }));
    await user.click(await screen.findByRole("button", { name: "开启签核轮次" }));

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/project-1/gates/gate-1/rounds",
      expect.objectContaining({ method: "POST" }),
    );
    expect(await screen.findByText("专业签核")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "批准产品签核" })).toBeInTheDocument();
  });

  it("keeps Gate load failures explicit and retryable", async () => {
    const user = userEvent.setup();
    let unavailable = true;
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path.endsWith("/gates")) return unavailable ? jsonResponse({}, 503) : jsonResponse({ items: [] });
      const response = workItemResponse(path);
      if (response) return response;
      throw new Error(`unexpected request: ${path}`);
    });
    render(<ProjectWorkspace />);
    await user.click(await screen.findByRole("button", { name: "打开项目 PRJ-001" }));
    await user.click(screen.getByRole("tab", { name: "Gate·交付物" }));
    expect(await screen.findByRole("heading", { name: "Gate 就绪度暂不可用" })).toBeInTheDocument();
    expect(screen.queryByText("尚未实例化 Gate")).not.toBeInTheDocument();
    unavailable = false;
    await user.click(screen.getByRole("button", { name: "重新加载 Gate" }));
    expect(await screen.findByRole("heading", { name: "尚未实例化 Gate" })).toBeInTheDocument();
  });

  it("loads Complaint and CAPA history lazily inside the project workspace", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path.endsWith("/quality/complaints")) return jsonResponse({ items: [complaint] });
      if (path.endsWith("/npi")) return jsonResponse({});
      if (path.endsWith("/quality/complaints/complaint-1/ncrs")) {
        return jsonResponse({ items: [ncr] });
      }
      if (path.endsWith("/quality/ncrs/ncr-1/workspace")) return jsonResponse({ ncr, digest: "a".repeat(64), actor_id: "user-1", people: {}, root_causes: [], actions: [], reviews: [], receipts: [], record_evidence: {}, can_manage: true, can_execute: true });
      if (path.endsWith("/quality/ncrs/ncr-1/detail")) {
        return jsonResponse({
          ncr,
          root_causes: [],
          actions: [],
          effectiveness_reviews: [],
        });
      }
      const response = workItemResponse(path);
      if (response) return response;
      throw new Error(`unexpected request: ${path}`);
    });

    render(<ProjectWorkspace />);
    await user.click(await screen.findByRole("button", { name: "打开项目 PRJ-001" }));
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/quality/"))).toBe(false);

    await user.click(screen.getByRole("tab", { name: "试制·测试·质量" }));
    expect(await screen.findByText("测试计划与用例")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: /CMP-C4S/ }));

    expect(await screen.findByRole("heading", { name: "CAPA 实际办理 · 根因调查与审核" })).toBeInTheDocument();
    expect(screen.getByText("NCR-C4S")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存调查 / 根因修订" })).toBeInTheDocument();
  });

  it("loads the product register lazily and creates a specification and typed BOM", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path.endsWith("/product-engineering/specifications")) {
        if (init?.method === "POST") return jsonResponse(specification, 201);
        return jsonResponse({ items: [] });
      }
      if (path.endsWith("/product-engineering/boms")) {
        if (init?.method === "POST") return jsonResponse(developmentBom, 201);
        return jsonResponse({ items: [] });
      }
      if (path.endsWith("/product-engineering/erp-references")) {
        return jsonResponse({ items: [] });
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<ProjectWorkspace />);
    await user.click(await screen.findByRole("button", { name: "打开项目 PRJ-001" }));
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("product-engineering"))).toBe(false);

    await user.click(screen.getByRole("tab", { name: "工程·变更" }));
    expect(await screen.findByRole("heading", { name: "尚未建立产品规格" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "尚未建立开发 BOM" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "EBOM" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Prototype BOM" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Cost BOM" })).toBeInTheDocument();

    await user.type(screen.getByLabelText("规格编号"), "SPEC-C4S");
    await user.type(screen.getByLabelText("规格标题"), "C4s performance specification");
    await user.click(screen.getByRole("button", { name: "创建规格" }));
    expect(await screen.findByText("规格已创建")).toBeInTheDocument();
    expect(screen.getByText("C4s performance specification")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/project-1/product-engineering/specifications",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          code: "SPEC-C4S",
          title: "C4s performance specification",
          version: 1,
          content: {},
        }),
      }),
    );

    await user.type(screen.getByLabelText("BOM 编号"), "C4S-EBOM");
    await user.type(screen.getByLabelText("BOM 名称"), "C4s engineering BOM");
    await user.click(screen.getByRole("button", { name: "创建 BOM" }));
    expect(await screen.findByText("BOM 已创建")).toBeInTheDocument();
    expect(screen.getByText("C4s engineering BOM")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/project-1/product-engineering/boms",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          specification_id: "specification-1",
          bom_type: "ebom",
          code: "C4S-EBOM",
          name: "C4s engineering BOM",
          version: 1,
          notes: null,
        }),
      }),
    );
  });

  it("keeps the product register read-only for Quality", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") {
        return jsonResponse({ ...identity, user: { ...identity.user, role: "quality" } });
      }
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path.endsWith("/product-engineering/specifications")) {
        return jsonResponse({ items: [specification] });
      }
      if (path.endsWith("/product-engineering/boms")) {
        return jsonResponse({ items: [developmentBom] });
      }
      if (path.endsWith("/product-engineering/erp-references")) {
        return jsonResponse({ items: [erpReference] });
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<ProjectWorkspace />);
    await user.click(await screen.findByRole("button", { name: "打开项目 PRJ-001" }));
    await user.click(screen.getByRole("tab", { name: "工程·变更" }));

    expect(await screen.findByText("C4s performance specification")).toBeInTheDocument();
    expect(screen.getByText("C4s engineering BOM")).toBeInTheDocument();
    expect(screen.getByText("ROUTING-9001")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "创建规格" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "创建 BOM" })).not.toBeInTheDocument();
  });

  it("shows a retryable product-engineering error without presenting zero counts", async () => {
    const user = userEvent.setup();
    let unavailable = true;
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path.includes("/product-engineering/")) {
        return unavailable ? jsonResponse({}, 503) : jsonResponse({ items: [] });
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<ProjectWorkspace />);
    await user.click(await screen.findByRole("button", { name: "打开项目 PRJ-001" }));
    await user.click(screen.getByRole("tab", { name: "工程·变更" }));
    expect(await screen.findByRole("heading", { name: "产品工程数据暂不可用" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "尚未建立产品规格" })).not.toBeInTheDocument();

    unavailable = false;
    await user.click(screen.getByRole("button", { name: "重新加载产品工程数据" }));
    expect(await screen.findByRole("heading", { name: "尚未建立产品规格" })).toBeInTheDocument();
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
    await screen.findByRole("tab", { name: "工作项" });
    await user.click(screen.getByRole("tab", { name: "工作项" }));
    await user.type(screen.getByLabelText("任务标题"), "Review DVT report");
    await user.click(screen.getByText("补充任务详情（说明、阶段、日期与前置任务）"));
    await user.type(screen.getByLabelText("任务说明"), "核对 DVT 报告结论与遗留项。");
    await user.selectOptions(screen.getByLabelText("所属阶段"), "stage-2");
    await user.type(screen.getByLabelText("开始日期"), "2026-08-20");
    await user.type(screen.getByLabelText("截止日期"), "2026-08-25");
    await user.click(screen.getByRole("button", { name: "创建任务" }));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/project-1/tasks",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          title: "Review DVT report",
          description: "核对 DVT 报告结论与遗留项。",
          stage_id: "stage-2",
          start_date: "2026-08-20",
          due_date: "2026-08-25",
          priority: "medium",
          dependency_task_ids: [],
        }),
      }),
    );

    await user.click(screen.getByRole("tab", { name: "工作项" }));
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
    await user.click(await screen.findByRole("tab", { name: "工作项" }));
    await user.click(screen.getByRole("button", { name: "查看任务详情 Prepare motor validation fixture" }));
    await user.click(screen.getByRole("button", { name: "开始任务" }));
    await user.click(await screen.findByRole("button", { name: "完成任务" }));

    await waitFor(() => expect(screen.queryByText("等待前置")).not.toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "查看任务详情 Integrate validation fixture" }));
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

    expect(screen.getAllByRole("tab")).toHaveLength(1);
    expect(screen.queryByRole("tab", { name: "工作项" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => /\/(tasks|issues|risks)$/.test(String(input)) || String(input).includes("product-engineering"))).toBe(false);
  });

  it("opens the project selected by the dashboard deep link", async () => {
    window.history.replaceState({}, "", "/projects?project=project-1&tab=timeline&event_id=41");
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path.endsWith("/activity")) return jsonResponse({ items: [{ id: 41, event_type: "TEST_FAILED", entity: "test_report", entity_id: "report-1", timestamp: "2026-08-11T16:00:00Z" }] });
      const response = workItemResponse(path);
      if (response) return response;
      throw new Error(`unexpected request: ${path}`);
    });

    render(<ProjectWorkspace />);

    expect(await screen.findByRole("heading", { name: "Next pump platform" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "概览·控制塔" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("TEST_FAILED")).toBeInTheDocument();
    expect(screen.getByText("TEST_FAILED").closest("li")).toHaveAttribute("aria-current", "true");
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

  it("keeps a selected project above the folded 25-project list and preserves navigation", async () => {
    window.history.replaceState({}, "", "/projects?project=project-1&tab=overview");
    const projects = Array.from({ length: 25 }, (_, index) => ({ ...project, id: `project-${index + 1}`, code: `PRJ-${String(index + 1).padStart(3, "0")}` }));
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: projects });
      if (path.endsWith("/activity")) return jsonResponse({ items: [] });
      const response = workItemResponse(path);
      if (response) return response;
      throw new Error(`unexpected request: ${path}`);
    });
    render(<ProjectWorkspace />);
    const toggle = await screen.findByRole("button", { name: "切换项目（25）" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("region", { name: "项目列表" })).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "项目概览" })).toBeInTheDocument();
    await userEvent.click(toggle);
    expect(screen.getAllByRole("button", { name: /^打开项目/ })).toHaveLength(25);
    const previousCount = fetchMock.mock.calls.length;
    await userEvent.click(screen.getByRole("button", { name: "打开项目 PRJ-001" }));
    expect(fetchMock).toHaveBeenCalledTimes(previousCount);
    await userEvent.click(screen.getByRole("button", { name: "切换项目（25）" }));
    await userEvent.click(screen.getByRole("button", { name: "打开项目 PRJ-002" }));
    expect(window.location.search).toBe("?project=project-2&tab=overview");
    expect(screen.queryByRole("region", { name: "项目列表" })).not.toBeInTheDocument();
  });

  it.each(["plan", "materials", "engineering", "decisions", "gates", "quality", "documents"])("does not fetch work-item details or activity for a %s deep link", async (tab) => {
    window.history.replaceState({}, "", `/projects?project=project-1&tab=${tab}`);
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path === "/api/projects/project-1/decisions/options") return jsonResponse({ members: [], tasks: [], gates: [] });
      if (path.startsWith("/api/projects/project-1/")) return jsonResponse({ items: [] });
      throw new Error(`unexpected request: ${path}`);
    });
    render(<ProjectWorkspace />);
    expect(await screen.findByRole("region", { name: "项目详情" })).toBeInTheDocument();
    expect(document.querySelector(`#project-tab-${tab}`)).toHaveAttribute("aria-selected", "true");
    expect(fetchMock.mock.calls.filter(([input]) => /\/(activity|tasks|issues|risks)$/.test(String(input)))).toHaveLength(0);
  });

  it("keeps external members on the permitted overview even with an internal-tab deep link", async () => {
    window.history.replaceState({}, "", "/projects?project=project-1&tab=engineering");
    fetchMock.mockImplementation(async (input) => {
      if (String(input) === "/api/session/me") return jsonResponse({ ...identity, user: { ...identity.user, role: "supplier" } });
      if (String(input) === "/api/projects") return jsonResponse({ items: [project] });
      throw new Error(`unexpected internal request: ${String(input)}`);
    });
    render(<ProjectWorkspace />);
    expect(await screen.findByRole("tab", { name: "概览·控制塔" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getAllByRole("tab")).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("loads work items and activity when their tabs first open and reuses an empty activity result", async () => {
    window.history.replaceState({}, "", "/projects?project=project-1&tab=documents");
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path.endsWith("/documents") || path.endsWith("/activity")) return jsonResponse({ items: [] });
      const response = workItemResponse(path);
      if (response) return response;
      throw new Error(`unexpected request: ${path}`);
    });
    render(<ProjectWorkspace />);
    await userEvent.click(await screen.findByRole("tab", { name: "工作项" }));
    expect(await screen.findByLabelText("任务标题")).toBeEnabled();
    expect(fetchMock.mock.calls.filter(([input]) => /\/(tasks|issues|risks)$/.test(String(input)))).toHaveLength(3);
    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/activity"))).toHaveLength(0);
    await userEvent.click(screen.getByRole("tab", { name: "概览·控制塔" }));
    expect(await screen.findByText("还没有项目活动。")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "工作项" }));
    await userEvent.click(screen.getByRole("tab", { name: "概览·控制塔" }));
    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/activity"))).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([input]) => /\/(tasks|issues|risks)$/.test(String(input)))).toHaveLength(3);
  });
});
