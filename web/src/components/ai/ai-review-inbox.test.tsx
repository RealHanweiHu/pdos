import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AiReviewInbox } from "./ai-review-inbox";
import { FINDING_TYPES, FINDING_TYPE_LABELS } from "./ai-types";

const { routerReplace } = vi.hoisted(() => ({ routerReplace: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: routerReplace }) }));

function jsonResponse(body: object, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const identity = {
  tenant: { id: "tenant-1", slug: "beepump", name: "Beehive Technology" },
  user: { id: "user-1", tenant_id: "tenant-1", username: "engineer", display_name: "Engineer", role: "engineer", email: null, is_active: true },
};

const stages = [{ id: "stage-1", code: "evt", name: "EVT", description: null, sequence: 1 }];
const project = {
  id: "project-1",
  development_case_id: "case-1",
  customer_id: null,
  workflow: { id: "workflow-1", code: "npd", name: "NPD", description: null, version: 1, is_active: true, stages },
  current_stage: stages[0],
  owner_user_id: "user-1",
  code: "PRJ-001",
  name: "Pump platform",
  description: null,
  status: "active",
  start_date: null,
  target_date: null,
  created_at: "2026-08-11T16:00:00Z",
  updated_at: "2026-08-11T16:00:00Z",
};

const finding = {
  id: "finding-1",
  project_id: "project-1",
  run_id: "run-1",
  model_invocation_id: "invocation-1",
  agent_key: "project_intelligence",
  finding_type: "risk_suggestion",
  origin_key: "run-1:risk",
  status: "pending_review",
  title: "电机交付可能影响 EVT",
  summary: "供应商延期事件支持登记项目风险。",
  proposed_payload: {
    title: "电机交付风险",
    description: "交付延迟",
    likelihood: 4,
    impact: 5,
    mitigation_plan: "准备替代料",
    contingency_plan: null,
    target_date: null,
  },
  accepted_payload: null,
  evidence_event_ids: [41],
  evidence: [{ event_row_id: 41, label: "事件 #41", href: "/projects?project=project-1&tab=timeline&event_id=41" }],
  confidence_basis_points: 8200,
  preflight_version: "finding-preflight-v2",
  reviewed_by_user_id: null,
  reviewed_at: null,
  review_comment: null,
  applied_by_user_id: null,
  applied_at: null,
  applied_entity_type: null,
  applied_entity_id: null,
  created_at: "2026-08-11T16:00:00Z",
  updated_at: "2026-08-11T16:00:00Z",
};

const emptyDigest = { groups: [], finding_count: 1, risk_candidate_count: 0, import_batch_count: 0, archived_count: 0 };

const candidate = (projectId: string) => ({ id: `candidate-${projectId}`, project_id: projectId, title: `候选 ${projectId}`, description: null, likelihood: 3, impact: 4, score: 12, created_at: "2026-09-08T12:00:00Z", updated_at: "2026-09-08T12:00:00Z" });

describe("AiReviewInbox", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    fetchMock.mockReset();
    window.history.replaceState({}, "", "/ai-review");
    routerReplace.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("does not imply that the Agent is healthy when the Finding queue is empty", async () => {
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/ai/findings/archive-policy") return jsonResponse({ automatic_enabled: false, ttl_days: 14, batch_size: 200 });
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path === "/api/ai/findings" && !init?.method) return jsonResponse({ items: [] });
      throw new Error(`unexpected request: ${path}`);
    });

    render(<AiReviewInbox />);

    expect(await screen.findByRole("heading", { name: "当前没有 Finding" })).toBeInTheDocument();
    expect(screen.getByText(/队列为空不代表模型或 Agent 可用/)).toBeInTheDocument();
    expect(screen.queryByText("Agent 正在值守")).not.toBeInTheDocument();
  });

  it("starts four scoped reads in parallel after one identity check and keeps slow extras separate", async () => {
    let resolveProjects!: (response: Response) => void;
    let resolveDigest!: (response: Response) => void;
    const projectResponse = new Promise<Response>((resolve) => { resolveProjects = resolve; });
    const digestResponse = new Promise<Response>((resolve) => { resolveDigest = resolve; });
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/ai/findings/archive-policy") return jsonResponse({ automatic_enabled: false, ttl_days: 14, batch_size: 200 });
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return projectResponse;
      if (path === "/api/ai/findings") return jsonResponse({ items: [finding] });
      if (path === "/api/ai/review-inbox") return digestResponse;
      if (path === "/api/ai/risk-candidates") return jsonResponse({ items: [candidate("project-1"), candidate("project-2")] });
      throw new Error(`unexpected request: ${path}`);
    });
    render(<AiReviewInbox />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(5));
    expect(screen.queryByTestId("ai-review-ready")).not.toBeInTheDocument();
    await act(async () => { resolveProjects(jsonResponse({ items: [project, { ...project, id: "project-2", code: "PRJ-002" }] })); });
    expect(await screen.findByRole("button", { name: /接受建议/ })).toBeEnabled();
    expect(screen.getByTestId("review-extras")).toHaveAttribute("data-state", "loading");
    await act(async () => { resolveDigest(jsonResponse({ ...emptyDigest, risk_candidate_count: 2 })); });
    await userEvent.click(await screen.findByRole("button", { name: /^展开候选/ }));
    expect(await screen.findByLabelText("选择候选 候选 project-1")).toBeInTheDocument();
    expect(screen.getByLabelText("选择候选 候选 project-2")).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith("risk-candidates"))).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/api/session/me")).toHaveLength(1);
  });

  it.each(["/api/ai/review-inbox", "/api/ai/risk-candidates"])("shows a failed supplemental read %s and retries without blocking or reloading the Finding", async (failedPath) => {
    let unavailable = true;
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/ai/findings/archive-policy") return jsonResponse({ automatic_enabled: false, ttl_days: 14, batch_size: 200 });
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path === "/api/ai/findings") return jsonResponse({ items: [finding] });
      if (path === failedPath && unavailable) return jsonResponse({}, 503);
      if (path === "/api/ai/review-inbox") return jsonResponse(emptyDigest);
      if (path === "/api/ai/risk-candidates") return jsonResponse({ items: [candidate("project-1")] });
      throw new Error(`unexpected request: ${path}`);
    });
    render(<AiReviewInbox />);
    expect(await screen.findByRole("button", { name: /接受建议/ })).toBeEnabled();
    expect(screen.getByTestId("review-extras")).toHaveAttribute("data-state", "error");
    expect(screen.getByRole("alert")).toHaveTextContent("尚未确认是否有待处理事项");
    unavailable = false;
    await userEvent.click(screen.getByRole("button", { name: "重新加载候选与摘要" }));
    await userEvent.click(await screen.findByRole("button", { name: /^展开候选/ }));
    expect(await screen.findByLabelText("选择候选 候选 project-1")).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/api/ai/findings")).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/api/projects")).toHaveLength(1);
  });

  it("does not request internal queues for an external identity", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ...identity, user: { ...identity.user, role: "customer" } }));
    render(<AiReviewInbox />);
    expect(await screen.findByRole("heading", { name: "此工作区仅供内部成员" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps batch confirmation undo available after refreshing an empty candidate queue", async () => {
    let confirmed = false;
    let requestId = "";
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/ai/findings/archive-policy") return jsonResponse({ automatic_enabled: false, ttl_days: 14, batch_size: 200 });
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path === "/api/ai/findings") return jsonResponse({ items: [finding] });
      if (path === "/api/ai/review-inbox") return jsonResponse({ ...emptyDigest, risk_candidate_count: confirmed ? 0 : 1 });
      if (path === "/api/ai/risk-candidates") return jsonResponse({ items: confirmed ? [] : [candidate("project-1")] });
      if (path.includes("/risk-candidates/batches")) {
        if (init?.method === "POST") { confirmed = true; requestId = JSON.parse(String(init.body)).request_id; }
        return jsonResponse({ request_id: requestId, project_id: "project-1", actor_user_id: "user-1", created_at: "2026-09-08T13:00:00Z", replayed: false,
          results: [{ risk_id: "candidate-project-1", title: "候选 project-1", description: null, score: 12, updated_at: "2026-09-08T13:00:00Z" }],
          current: [{ id: "candidate-project-1", draft_state: confirmed ? "confirmed" : "draft", status: "open", updated_at: "2026-09-08T13:00:00Z" }],
        });
      }
      if (path.endsWith("/unconfirm")) { confirmed = false; return jsonResponse({}); }
      throw new Error(`unexpected request: ${path}`);
    });
    render(<AiReviewInbox />);
    await userEvent.click(await screen.findByRole("button", { name: "展开候选（1）" }));
    await userEvent.click(screen.getByLabelText("选择候选 候选 project-1"));
    await userEvent.click(screen.getByRole("button", { name: "批量确认（1）" }));
    await userEvent.click(screen.getByRole("button", { name: "确认写入" }));
    const undo = await screen.findByRole("button", { name: "撤销本组未变更的确认（1）" });
    await waitFor(() => expect(undo).toBeEnabled());
    expect(screen.queryByLabelText("选择候选 候选 project-1")).not.toBeInTheDocument();
    await userEvent.click(undo);
    expect(await screen.findByLabelText("选择候选 候选 project-1")).toBeInTheDocument();
  });

  it.each(["success", "failure"])("ignores an earlier extras %s that settles after a successful full-page retry", async (lateResult) => {
    let resolveOldDigest!: (response: Response) => void;
    const oldDigest = new Promise<Response>((resolve) => { resolveOldDigest = resolve; });
    let findingCalls = 0;
    let digestCalls = 0;
    let candidateCalls = 0;
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/ai/findings/archive-policy") return jsonResponse({ automatic_enabled: false, ttl_days: 14, batch_size: 200 });
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path === "/api/ai/findings") return ++findingCalls === 1 ? jsonResponse({}, 503) : jsonResponse({ items: [finding] });
      if (path === "/api/ai/review-inbox") return ++digestCalls === 1 ? oldDigest : jsonResponse(emptyDigest);
      if (path === "/api/ai/risk-candidates") return jsonResponse({ items: [{ ...candidate("project-1"), title: ++candidateCalls === 1 ? "旧候选" : "新候选" }] });
      throw new Error(`unexpected request: ${path}`);
    });
    render(<AiReviewInbox />);
    await userEvent.click(await screen.findByRole("button", { name: "重新加载" }));
    await userEvent.click(await screen.findByRole("button", { name: "展开候选（1）" }));
    expect(screen.getByLabelText("选择候选 新候选")).toBeInTheDocument();
    await act(async () => { resolveOldDigest(lateResult === "failure" ? jsonResponse({}, 503) : jsonResponse(emptyDigest)); });
    expect(screen.getByTestId("review-extras")).toHaveAttribute("data-state", "ready");
    expect(screen.getByLabelText("选择候选 新候选")).toBeInTheDocument();
    expect(screen.queryByLabelText("选择候选 旧候选")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps a long summary expandable while placing selected details before the queue on mobile", async () => {
    const longSummary = "供应商延期需要复核。".repeat(100);
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/ai/findings/archive-policy") return jsonResponse({ automatic_enabled: false, ttl_days: 14, batch_size: 200 });
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path === "/api/ai/findings") return jsonResponse({ items: [{ ...finding, summary: longSummary }] });
      if (path === "/api/ai/review-inbox") return jsonResponse(emptyDigest);
      if (path === "/api/ai/risk-candidates") return jsonResponse({ items: [] });
      throw new Error(`unexpected request: ${path}`);
    });
    render(<AiReviewInbox />);
    const expand = await screen.findByRole("button", { name: "展开完整说明" });
    expect(screen.getByText(longSummary)).toHaveClass("line-clamp-3");
    expect(screen.getByRole("article", { name: "Finding 详情" })).toHaveClass("order-first");
    expect(screen.getByRole("article", { name: "Finding 详情" })).toHaveClass("lg:max-h-[min(700px,calc(100svh-20rem))]", "overflow-y-auto");
    expect(screen.getByRole("complementary", { name: "Finding 队列" })).toHaveClass("order-last");
    expect(screen.getByRole("button", { name: /接受建议/ })).toBeEnabled();
    await userEvent.click(expand);
    expect(screen.getByText(longSummary)).not.toHaveClass("line-clamp-3");
    await userEvent.click(screen.getByRole("button", { name: "收起说明" }));
    expect(screen.getByText(longSummary)).toHaveClass("line-clamp-3");
    const filters = screen.getByRole("group", { name: "Finding 类型筛选" });
    expect(filters).toHaveClass("flex-nowrap", "overflow-x-auto", "sm:flex-wrap");
    const filterButtons = within(filters).getAllByRole("button");
    expect(filterButtons).toHaveLength(FINDING_TYPES.length + 1);
    for (const kind of FINDING_TYPES) expect(within(filters).getByRole("button", { name: FINDING_TYPE_LABELS[kind] })).toBeInTheDocument();
    expect(filterButtons.every((button) => button.classList.contains("shrink-0"))).toBe(true);
    const lastFilter = within(filters).getByRole("button", { name: "组合例外简报" });
    lastFilter.focus();
    await userEvent.keyboard(" ");
    expect(lastFilter).toHaveAttribute("aria-pressed", "true");
  });

  it("keeps accept and Apply as two independent human actions with evidence links", async () => {
    const user = userEvent.setup();
    const accepted = {
      ...finding,
      status: "accepted",
      accepted_payload: finding.proposed_payload,
      reviewed_by_user_id: "user-1",
      reviewed_at: "2026-08-11T16:05:00Z",
    };
    const applied = {
      ...accepted,
      status: "applied",
      applied_by_user_id: "user-1",
      applied_at: "2026-08-11T16:06:00Z",
      applied_entity_type: "risk",
      applied_entity_id: "risk-1",
    };
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/ai/findings/archive-policy") return jsonResponse({ automatic_enabled: false, ttl_days: 14, batch_size: 200 });
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path === "/api/ai/findings" && !init?.method) return jsonResponse({ items: [finding] });
      if (path.endsWith("/review")) return jsonResponse(accepted);
      if (path.endsWith("/apply")) return jsonResponse({ finding: applied, risk_id: "risk-1", idempotent_replay: false });
      throw new Error(`unexpected request: ${path}`);
    });

    render(<AiReviewInbox />);

    expect(await screen.findByRole("heading", { name: "AI Review 收件箱" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看事件" })).toHaveAttribute(
      "href",
      "/projects?project=project-1&tab=timeline&event_id=41",
    );
    await user.click(screen.getByRole("button", { name: /接受建议/ }));

    expect(await screen.findByRole("status")).toHaveTextContent("尚未写入业务对象");
    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/apply"))).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "应用到业务对象" }));
    expect(screen.getByRole("region", { name: "最终写入预览" })).toHaveTextContent("电机交付风险");
    await user.click(screen.getByRole("button", { name: "确认应用" }));

    await waitFor(() => expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/apply"))).toHaveLength(1));
    expect(await screen.findByRole("link", { name: /查看已应用 Risk/ })).toHaveAttribute(
      "href",
      "/projects?project=project-1&tab=work-items",
    );
  });

  it("requires one of the explicit rejection reasons before submission", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/ai/findings/archive-policy") return jsonResponse({ automatic_enabled: false, ttl_days: 14, batch_size: 200 });
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path === "/api/ai/findings" && !init?.method) return jsonResponse({ items: [finding] });
      if (path.endsWith("/review")) {
        return jsonResponse({ ...finding, status: "rejected", reviewed_by_user_id: "user-1", reviewed_at: "2026-08-11T16:05:00Z", review_comment: "证据不足" });
      }
      throw new Error(`unexpected request: ${path}`);
    });
    render(<AiReviewInbox />);
    await user.click(await screen.findByRole("button", { name: /拒绝/ }));
    const confirm = screen.getByRole("button", { name: "确认拒绝" });
    expect(confirm).toBeDisabled();
    await user.selectOptions(screen.getByLabelText("拒绝原因（必选）"), "证据不足");
    await user.click(confirm);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/ai/findings/finding-1/review",
      expect.objectContaining({ body: JSON.stringify({ decision: "rejected", comment: "证据不足" }) }),
    ));
  });

  it("surfaces Phase 2 Engineering and Quality findings through the same review contract", async () => {
    const user = userEvent.setup();
    const qualityFinding = {
      ...finding,
      id: "finding-quality-1",
      agent_key: "quality_intelligence",
      finding_type: "capa_suggestion",
      title: "复核客诉 CAPA 响应",
      summary: "项目内客诉证据支持质量团队复核纠正与预防建议。",
      proposed_payload: {
        title: "复核 CAPA 响应",
        description: "相关性不是已批准根因。",
        likelihood: 3,
        impact: 5,
        mitigation_plan: "确认围堵并完成根因分析",
        contingency_plan: "根因批准后复核预防控制",
      },
    };
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/ai/findings/archive-policy") return jsonResponse({ automatic_enabled: false, ttl_days: 14, batch_size: 200 });
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path === "/api/ai/findings" && !init?.method) {
        return jsonResponse({ items: [finding, qualityFinding] });
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<AiReviewInbox />);
    await user.click(await screen.findByRole("button", { name: "CAPA 建议" }));

    expect(screen.getByText("Quality Intelligence")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "复核客诉 CAPA 响应" })).toBeInTheDocument();
    expect(screen.getByText("根因批准后复核预防控制")).toBeInTheDocument();
  });

  it("applies an accepted knowledge Finding only as an unverified Memory draft", async () => {
    const user = userEvent.setup();
    const accepted = {
      ...finding,
      agent_key: "knowledge_lite",
      finding_type: "knowledge_draft",
      status: "accepted",
      proposed_payload: {
        title: "Connector lesson",
        draft_text: "Validate connector mapping before DVT.",
        applicability: "Connector projects",
      },
      accepted_payload: {
        title: "Connector lesson",
        draft_text: "Validate connector mapping before DVT.",
        applicability: "Connector projects",
      },
      reviewed_by_user_id: "user-1",
      reviewed_at: "2026-08-11T16:05:00Z",
    };
    const applied = {
      ...accepted,
      status: "applied",
      applied_by_user_id: "user-1",
      applied_at: "2026-08-11T16:06:00Z",
      applied_entity_type: "memory",
      applied_entity_id: "memory-1",
    };
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/ai/findings/archive-policy") return jsonResponse({ automatic_enabled: false, ttl_days: 14, batch_size: 200 });
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path === "/api/ai/findings" && !init?.method) return jsonResponse({ items: [accepted] });
      if (path.endsWith("/apply")) {
        return jsonResponse({
          finding: applied,
          applied_entity_type: "memory",
          applied_entity_id: "memory-1",
          risk_id: null,
          memory_id: "memory-1",
          idempotent_replay: false,
        });
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<AiReviewInbox />);
    await user.click(await screen.findByRole("button", { name: "创建 Memory 草稿" }));
    expect(screen.getByRole("region", { name: "最终写入预览" })).toHaveTextContent(
      "不会进入检索",
    );
    await user.click(screen.getByRole("button", { name: "确认应用" }));

    expect(await screen.findByRole("status")).toHaveTextContent("未验证 Memory 草稿");
    expect(screen.getByRole("link", { name: "查看 Memory 草稿" })).toHaveAttribute(
      "href",
      "/knowledge?project=project-1&memory=memory-1",
    );
  });
});
