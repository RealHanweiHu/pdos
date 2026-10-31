import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

const specification = {
  id: "specification-1",
  project_id: "project-1",
  created_by_user_id: "user-1",
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

const members = [
  { user_id: "user-1", display_name: "Initial Owner", role: "owner", is_active: true, assignable: true },
  { user_id: "user-2", display_name: "Erin Engineer", role: "engineer", is_active: true, assignable: true },
  { user_id: "user-3", display_name: "Sam Supplier", role: "supplier", is_active: true, assignable: false },
];

function workItemResponse(path: string) {
  if (path.endsWith("/tasks")) return jsonResponse({ items: [waitingTask] });
  if (path.endsWith("/issues")) return jsonResponse({ items: [openIssue] });
  if (path.endsWith("/risks")) return jsonResponse({ items: [openRisk] });
  if (path.endsWith("/members")) return jsonResponse({ items: members });
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

    expect(await screen.findAllByRole("tab")).toHaveLength(10);
    expect(screen.getByRole("tab", { name: "AI 对话" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "产品工程" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "质量 / CAPA" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "概览" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("1", { selector: "[data-metric='task']" })).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "任务" }));
    expect(screen.getAllByText("Integrate validation fixture")).toHaveLength(2);
    expect(screen.getByText("等待前置")).toBeInTheDocument();
    expect(screen.queryByText("已阻塞", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "开始任务" })).not.toBeInTheDocument();
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

    await user.click(screen.getByRole("tab", { name: "Gate" }));
    expect(await screen.findByRole("heading", { name: "2 个例外需要处理" })).toBeInTheDocument();
    expect(screen.getByText("确认概念评审材料")).toBeInTheDocument();
    expect(screen.queryByText("供应商交期风险")).not.toBeVisible();
    await user.click(screen.getByRole("button", { name: "展开其余 1 项" }));
    expect(screen.getByText("供应商交期风险")).toBeVisible();

    await user.click(screen.getByRole("tab", { name: "文档" }));
    expect(await screen.findByText("concept-review.pdf")).toBeInTheDocument();
    expect(screen.getByText(/已抽取/)).toBeInTheDocument();
    expect(screen.queryByText(/object_key/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "上传并抽取" })).toBeDisabled();
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
    await user.click(screen.getByRole("tab", { name: "Gate" }));
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
      if (path.endsWith("/quality/complaints/complaint-1/ncrs")) {
        return jsonResponse({ items: [ncr] });
      }
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

    await user.click(screen.getByRole("tab", { name: "质量 / CAPA" }));
    await user.click(await screen.findByRole("button", { name: /CMP-C4S/ }));

    expect(await screen.findByRole("heading", { name: "CAPA 执行链" })).toBeInTheDocument();
    expect(screen.getByText("NCR-C4S")).toBeInTheDocument();
    expect(screen.getAllByText("根因分析")).toHaveLength(2);
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

    await user.click(screen.getByRole("tab", { name: "产品工程" }));
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
    await user.click(screen.getByRole("tab", { name: "产品工程" }));

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
    await user.click(screen.getByRole("tab", { name: "产品工程" }));
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
    await screen.findByRole("tab", { name: "任务" });
    await user.click(screen.getByRole("tab", { name: "任务" }));
    await user.type(screen.getByLabelText("任务标题"), "Review DVT report");
    await user.click(screen.getByRole("button", { name: "创建任务" }));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/project-1/tasks",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          title: "Review DVT report",
          priority: "medium",
          dependency_task_ids: [],
          stage_id: "stage-1",
        }),
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

  it("plans tasks with owner, stage and due date, surfaces overdue work, and edits minimally", async () => {
    const user = userEvent.setup();
    const overdueTask = {
      ...foundationTask,
      assignee_user_id: "user-2",
      stage_id: "stage-1",
      due_date: "2000-01-03",
    };
    const laterTask = {
      ...waitingTask,
      assignee_user_id: "user-1",
      stage_id: "stage-2",
      due_date: "2999-12-31",
    };
    const doneTask = {
      ...foundationTask,
      id: "task-4",
      title: "Archive concept notes",
      status: "done",
      readiness: "complete",
      due_date: "2000-01-01",
    };
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path.endsWith("/tasks") && !init?.method) {
        return jsonResponse({ items: [laterTask, overdueTask, doneTask] });
      }
      if (path.endsWith("/tasks") && init?.method === "POST") {
        return jsonResponse({ ...laterTask, id: "task-5", title: "Book EMC lab", due_date: "2026-12-01" }, 201);
      }
      if (path === "/api/projects/project-1/tasks/task-1" && init?.method === "PATCH") {
        return jsonResponse({ ...overdueTask, assignee_user_id: "user-1", due_date: "2999-01-15" });
      }
      const response = workItemResponse(path);
      if (response) return response;
      throw new Error(`unexpected request: ${path}`);
    });

    render(<ProjectWorkspace />);
    await user.click(await screen.findByRole("button", { name: "打开项目 PRJ-001" }));
    expect(await screen.findByText("其中 1 项任务已逾期")).toBeInTheDocument();
    expect(screen.getByText("2", { selector: "[data-metric='task']" })).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "任务" }));
    const taskSection = screen.getByRole("region", { name: "项目任务" });
    let rows = within(taskSection).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Prepare motor validation fixture");
    expect(rows[0]).toHaveTextContent(/逾期 \d+ 天/);
    expect(rows[0]).toHaveTextContent("负责人：Erin Engineer");
    expect(rows[0]).toHaveTextContent("阶段：概念阶段");
    expect(rows[1]).toHaveTextContent("负责人：Initial Owner（我）");
    expect(rows[1]).not.toHaveTextContent("逾期");
    expect(screen.getByTestId("task-visible-count")).toHaveTextContent("显示 2 / 3");

    await user.selectOptions(screen.getByLabelText("负责人筛选"), "me");
    rows = within(taskSection).getAllByRole("listitem");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("Integrate validation fixture");
    await user.selectOptions(screen.getByLabelText("负责人筛选"), "all");
    await user.selectOptions(screen.getByLabelText("状态"), "closed");
    rows = within(taskSection).getAllByRole("listitem");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("Archive concept notes");
    expect(rows[0]).not.toHaveTextContent("逾期");
    expect(within(rows[0]).queryByRole("button", { name: /编辑任务/ })).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("状态"), "open");

    const assignee = screen.getByLabelText("负责人");
    expect(within(assignee).getByRole("option", { name: "Erin Engineer" })).toBeInTheDocument();
    expect(within(assignee).queryByRole("option", { name: "Sam Supplier" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("所属阶段")).toHaveValue("stage-1");

    await user.type(screen.getByLabelText("任务标题"), "Book EMC lab");
    await user.selectOptions(assignee, "user-2");
    fireEvent.change(screen.getByLabelText("开始日期"), { target: { value: "2026-12-05" } });
    fireEvent.change(screen.getByLabelText("截止日期"), { target: { value: "2026-12-01" } });
    await user.click(screen.getByRole("button", { name: "创建任务" }));
    expect(screen.getByRole("alert")).toHaveTextContent("截止日期不能早于开始日期。");
    expect(fetchMock).not.toHaveBeenCalledWith("/api/projects/project-1/tasks", expect.objectContaining({ method: "POST" }));

    fireEvent.change(screen.getByLabelText("开始日期"), { target: { value: "" } });
    await user.click(screen.getByRole("button", { name: "创建任务" }));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/project-1/tasks",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          title: "Book EMC lab",
          priority: "medium",
          dependency_task_ids: [],
          assignee_user_id: "user-2",
          stage_id: "stage-1",
          due_date: "2026-12-01",
        }),
      }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("任务已创建");

    await user.click(screen.getByRole("button", { name: "编辑任务 Prepare motor validation fixture" }));
    const editForm = screen.getByRole("form", { name: "编辑任务 Prepare motor validation fixture" });
    expect(within(editForm).getByLabelText("任务标题")).toHaveValue("Prepare motor validation fixture");
    expect(within(editForm).getByText("Archive concept notes")).toBeInTheDocument();
    expect(within(editForm).queryByText("Integrate validation fixture")).not.toBeInTheDocument();
    await user.selectOptions(within(editForm).getByLabelText("负责人"), "user-1");
    fireEvent.change(within(editForm).getByLabelText("截止日期"), { target: { value: "2999-01-15" } });
    await user.click(within(editForm).getByRole("button", { name: "保存任务" }));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/project-1/tasks/task-1",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ assignee_user_id: "user-1", due_date: "2999-01-15" }),
      }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("任务已更新");
    expect(screen.queryByRole("form", { name: "编辑任务 Prepare motor validation fixture" })).not.toBeInTheDocument();
    expect(within(taskSection).queryByText(/逾期 \d+ 天/)).not.toBeInTheDocument();
  });

  it("manages project members with confirmation and explains blocked removals", async () => {
    const user = userEvent.setup();
    let currentMembers = members;
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path === "/api/projects/project-1/members/candidates") {
        return jsonResponse({ items: [{ user_id: "user-4", display_name: "Quinn Quality", role: "quality" }] });
      }
      if (path === "/api/projects/project-1/members" && init?.method === "POST") {
        currentMembers = [...currentMembers, { user_id: "user-4", display_name: "Quinn Quality", role: "quality", is_active: true, assignable: true }];
        return jsonResponse({ items: currentMembers }, 201);
      }
      if (path === "/api/projects/project-1/members/user-2" && init?.method === "DELETE") {
        return jsonResponse({ detail: { code: "PROJECT_MEMBER_HAS_OPEN_WORK", message: "x", open_work: { tasks: 2, risks: 1 } } }, 409);
      }
      if (path.endsWith("/members")) return jsonResponse({ items: currentMembers });
      const response = workItemResponse(path);
      if (response) return response;
      throw new Error(`unexpected request: ${path}`);
    });

    render(<ProjectWorkspace />);
    await user.click(await screen.findByRole("button", { name: "打开项目 PRJ-001" }));
    const card = await screen.findByRole("region", { name: "项目成员" });
    expect(within(card).getByText("3 人")).toBeInTheDocument();
    expect(within(card).getByText("项目负责人")).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "移除成员 Initial Owner" })).not.toBeInTheDocument();

    const picker = within(card).getByLabelText("添加成员");
    await waitFor(() => expect(within(picker).getByRole("option", { name: "Quinn Quality · 质量" })).toBeInTheDocument());
    await user.selectOptions(picker, "user-4");
    await user.click(within(card).getByRole("button", { name: "添加" }));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/project-1/members",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ user_id: "user-4" }) }),
    );
    expect(await within(card).findByText("4 人")).toBeInTheDocument();
    expect(within(card).getByRole("status")).toHaveTextContent("成员已添加");

    await user.click(within(card).getByRole("button", { name: "移除成员 Erin Engineer" }));
    expect(fetchMock).not.toHaveBeenCalledWith("/api/projects/project-1/members/user-2", expect.anything());
    await user.click(within(card).getByRole("button", { name: "确认移除" }));
    expect(await within(card).findByRole("alert")).toHaveTextContent("该成员仍负责未完成的工作（任务 2、风险 1），请先转交后再移除。");
    expect(within(card).getByText("4 人")).toBeInTheDocument();
  });

  it("edits the stage plan, flags a late stage, and cancels only with a reason", async () => {
    const user = userEvent.setup();
    const plannedStages = stages.map((stage, index) =>
      index === 0
        ? { ...stage, planned_start_date: "2000-01-01", planned_end_date: "2000-01-10", entered_at: "2000-01-01T08:00:00Z", exited_at: null }
        : { ...stage, planned_start_date: null, planned_end_date: null, entered_at: null, exited_at: null },
    );
    const activeProject = {
      ...project,
      status: "active",
      workflow: { ...project.workflow, stages: plannedStages },
      current_stage: plannedStages[0],
    };
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [activeProject] });
      if (path === "/api/projects/project-1/stage-plan" && init?.method === "PUT") {
        const body = JSON.parse(String(init.body)) as { stages: { stage_id: string; planned_start_date: string | null; planned_end_date: string | null }[] };
        const updatedStages = plannedStages.map((stage, index) => ({ ...stage, ...body.stages[index] }));
        return jsonResponse({ ...activeProject, workflow: { ...activeProject.workflow, stages: updatedStages }, current_stage: updatedStages[0] });
      }
      if (path === "/api/projects/project-1/transitions" && init?.method === "POST") {
        return jsonResponse({ ...activeProject, status: "cancelled" });
      }
      const response = workItemResponse(path);
      if (response) return response;
      throw new Error(`unexpected request: ${path}`);
    });

    render(<ProjectWorkspace />);
    await user.click(await screen.findByRole("button", { name: "打开项目 PRJ-001" }));
    expect(await screen.findByText(/阶段逾期 \d+ 天/, { selector: "[data-metric='stage-schedule']" })).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "时间线" }));
    expect(screen.getByTestId("stage-dates-concept")).toHaveTextContent("计划01-01 → 01-10");
    expect(screen.getByTestId("stage-schedule-concept")).toHaveTextContent(/阶段逾期 \d+ 天/);
    expect(screen.getByTestId("stage-schedule-planning")).toHaveTextContent("未设计划");
    await user.click(screen.getByRole("button", { name: "编辑阶段计划" }));
    const planForm = screen.getByRole("form", { name: "编辑阶段计划" });
    fireEvent.change(within(planForm).getByLabelText("规划阶段计划开始"), { target: { value: "2999-02-01" } });
    fireEvent.change(within(planForm).getByLabelText("规划阶段计划结束"), { target: { value: "2999-01-01" } });
    await user.click(within(planForm).getByRole("button", { name: "保存阶段计划" }));
    expect(within(planForm).getByRole("alert")).toHaveTextContent("规划阶段的结束日期早于开始日期。");
    fireEvent.change(within(planForm).getByLabelText("规划阶段计划结束"), { target: { value: "2999-03-01" } });
    await user.click(within(planForm).getByRole("button", { name: "保存阶段计划" }));
    const planCall = fetchMock.mock.calls.find(([input, init]) => String(input).endsWith("/stage-plan") && init?.method === "PUT");
    const sentStages = (JSON.parse(String(planCall?.[1]?.body)) as { stages: unknown[] }).stages;
    expect(sentStages).toHaveLength(7);
    expect(sentStages[1]).toEqual({ stage_id: "stage-2", planned_start_date: "2999-02-01", planned_end_date: "2999-03-01" });
    expect(await screen.findByTestId("stage-schedule-planning")).toHaveTextContent("计划 2999-02-01 开始");
    expect(screen.queryByRole("form", { name: "编辑阶段计划" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "概览" }));
    await user.click(screen.getByRole("button", { name: "取消项目" }));
    const cancelForm = screen.getByRole("form", { name: "取消项目" });
    expect(within(cancelForm).getByRole("button", { name: "确认取消项目" })).toBeDisabled();
    await user.type(within(cancelForm).getByLabelText("取消原因"), "客户撤回需求");
    await user.click(within(cancelForm).getByRole("button", { name: "确认取消项目" }));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/project-1/transitions",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ to_status: "cancelled", reason: "客户撤回需求" }) }),
    );
    expect(await screen.findByText("项目已取消，阶段计划已锁定；可归档留存。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "归档项目" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "取消项目" })).not.toBeInTheDocument();
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
    expect(screen.getByRole("tab", { name: "时间线" })).toHaveAttribute("aria-selected", "true");
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
});
