import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AiReviewInbox } from "./ai-review-inbox";

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

describe("AiReviewInbox", () => {
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
      "/projects?project=project-1&tab=risks",
    );
  });

  it("requires one of the explicit rejection reasons before submission", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
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
});
