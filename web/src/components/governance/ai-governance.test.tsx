import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AiGovernance } from "./ai-governance";

const { routerReplace } = vi.hoisted(() => ({ routerReplace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: routerReplace }),
  usePathname: () => "/governance/ai",
}));

const api = vi.hoisted(() => ({
  requestAiUsage: vi.fn(),
  requestCapabilities: vi.fn(),
  requestTouchpoints: vi.fn(),
}));
vi.mock("@/components/ai/ai-api", () => api);

const projectApi = vi.hoisted(() => ({ requestProjects: vi.fn() }));
vi.mock("@/components/projects/project-api", () => projectApi);

const identity = (role: string) => ({
  tenant: { id: "tenant-1", slug: "beepump", name: "Beehive Technology" },
  user: {
    id: "user-1",
    tenant_id: "tenant-1",
    username: "owner",
    display_name: "Owner",
    role,
    email: null,
    is_active: true,
  },
});

describe("AiGovernance", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders usage, touchpoints with manual paths, and the capability contract", async () => {
    projectApi.requestProjects.mockResolvedValue({ identity: identity("owner"), projects: [] });
    api.requestAiUsage.mockResolvedValue({
      daily_token_budget: 2000000,
      used_tokens_today: 1500,
      remaining_tokens_today: 1998500,
      budget_exhausted: false,
      rows: [
        {
          agent_key: "project_intelligence",
          prompt_version: "project-intelligence-v1",
          invocation_count: 4,
          succeeded_count: 4,
          total_tokens: 1500,
        },
      ],
    });
    api.requestTouchpoints.mockResolvedValue([
      {
        key: "ai_chat",
        label: "AI 问答",
        state: "disabled",
        reason_code: "BUDGET_EXCEEDED",
        manual_alternative: "查看项目时间线、工作项与知识库检索",
      },
      {
        key: "test_report_import",
        label: "测试报告 AI 导入",
        state: "degraded",
        reason_code: "BUDGET_EXCEEDED",
        manual_alternative: "已识别过的模板仍可零模型复用映射",
      },
    ]);
    api.requestCapabilities.mockResolvedValue([
      {
        capability_key: "project_intelligence.risk_suggestion",
        agent_key: "project_intelligence",
        zone: "hard_gate",
        rollout: "live",
        prompt_version: "project-intelligence-v1",
        finding_types: ["risk_suggestion"],
        projections: [],
        tools: ["read_project_context"],
        quality_control: "finding_quality_control",
        controls: [{ agent_key: "project_intelligence", finding_type: "risk_suggestion", status: "narrowed", minimum_review_count: 5, acceptance_threshold_basis_points: 2000, reviewed_count: 5, accepted_count: 0, applied_count: 0, acceptance_rate_basis_points: 0, narrowed_at: "2026-08-20T02:00:00Z", narrowed_reason: "低接受率" }],
      },
      {
        capability_key: "supplier_intelligence.supplier_delay_risk",
        agent_key: "supplier_intelligence",
        zone: "hard_gate",
        rollout: "shadow",
        prompt_version: "supplier-intelligence-v1",
        finding_types: ["supplier_delay_risk"],
        projections: [],
        tools: ["read_project_context"],
        quality_control: "finding_quality_control",
        controls: [],
      },
    ]);

    render(<AiGovernance />);
    await waitFor(() => expect(screen.getByText("AI 治理看板")).toBeInTheDocument());

    expect(screen.getByText("用量与预算")).toBeInTheDocument();
    expect(screen.getAllByText("1,500").length).toBeGreaterThan(0);
    expect(screen.getByText("失能")).toBeInTheDocument();
    expect(screen.getByText("降级")).toBeInTheDocument();
    expect(
      screen.getByText(/人工替代：查看项目时间线、工作项与知识库检索/),
    ).toBeInTheDocument();
    expect(screen.getByText("project_intelligence.risk_suggestion")).toBeInTheDocument();
    expect(screen.getByText("已熔断（narrowed）")).toBeInTheDocument();
    expect(screen.getByText("Shadow")).toBeInTheDocument();
  });

  it("locks non-admin roles out", async () => {
    projectApi.requestProjects.mockResolvedValue({
      identity: identity("engineer"),
      projects: [],
    });
    render(<AiGovernance />);
    await waitFor(() =>
      expect(screen.getByText("仅管理员可查看 AI 治理")).toBeInTheDocument(),
    );
    expect(api.requestAiUsage).not.toHaveBeenCalled();
  });
});
