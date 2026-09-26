import { afterEach, describe, expect, it, vi } from "vitest";

import {
  confirmRiskCandidatesBatch,
  requestAiUsage,
  requestCapabilities,
  requestReviewInbox,
  requestRiskCandidates,
  requestTouchpoints,
} from "./ai-api";
import { requestFindings } from "./ai-api";

function jsonResponse(body: object, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const baseFinding = {
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
  proposed_payload: { title: "电机交付风险" },
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

describe("ai-api finding list parsing", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("parses every backend-allowed finding type, including phase-3 agents", async () => {
    const items = [
      baseFinding,
      { ...baseFinding, id: "finding-2", agent_key: "supplier_intelligence", finding_type: "supplier_delay_risk" },
      { ...baseFinding, id: "finding-3", agent_key: "executive_intelligence", finding_type: "executive_portfolio_brief" },
    ];
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({ items })));

    const findings = await requestFindings();
    expect(findings.map((item) => item.finding_type)).toEqual([
      "risk_suggestion",
      "supplier_delay_risk",
      "executive_portfolio_brief",
    ]);
  });

  it("skips findings with unknown enum values instead of failing the whole list", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const items = [
      { ...baseFinding, id: "finding-x", finding_type: "finding_type_from_the_future" },
      baseFinding,
      { ...baseFinding, id: "finding-y", status: "status_from_the_future" },
    ];
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({ items })));

    const findings = await requestFindings();
    expect(findings.map((item) => item.id)).toEqual(["finding-1"]);
    expect(warn).toHaveBeenCalledTimes(2);
  });

  it("still rejects structurally broken finding payloads", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({ items: [{ id: "broken" }] })),
    );
    await expect(requestFindings()).rejects.toThrow("invalid Finding response");
  });
});

describe("ai-api A10/C2 governance surfaces", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("parses the review inbox digest with grouped mixed drafts", async () => {
    const digest = {
      groups: [
        {
          project_id: "project-1",
          project_name: "气泵 A1",
          items: [
            {
              kind: "finding",
              id: "finding-1",
              title: "电机交付可能影响 EVT",
              agent_key: "project_intelligence",
              finding_type: "risk_suggestion",
              confidence_basis_points: 8200,
              quality_acceptance_basis_points: 6600,
              href: "/ai-review?finding=finding-1",
              created_at: "2026-08-20T02:00:00Z",
            },
            {
              kind: "risk_candidate",
              id: "risk-1",
              title: "任务逾期：手板加工",
              agent_key: null,
              finding_type: null,
              confidence_basis_points: null,
              quality_acceptance_basis_points: null,
              href: "/projects?project=project-1&tab=work-items",
              created_at: "2026-08-21T02:00:00Z",
            },
          ],
        },
      ],
      finding_count: 1,
      risk_candidate_count: 1,
      import_batch_count: 0,
      archived_count: 2,
    };
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(digest)));

    const parsed = await requestReviewInbox();
    expect(parsed.archived_count).toBe(2);
    expect(parsed.groups[0].items.map((item) => item.kind)).toEqual([
      "finding",
      "risk_candidate",
    ]);
  });

  it("rejects inbox items with unsafe hrefs", async () => {
    const digest = {
      groups: [
        {
          project_id: "project-1",
          project_name: "气泵 A1",
          items: [
            {
              kind: "finding",
              id: "finding-1",
              title: "t",
              agent_key: null,
              finding_type: null,
              confidence_basis_points: null,
              quality_acceptance_basis_points: null,
              href: "https://evil.example/phish",
              created_at: "2026-08-20T02:00:00Z",
            },
          ],
        },
      ],
      finding_count: 1,
      risk_candidate_count: 0,
      import_batch_count: 0,
      archived_count: 0,
    };
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(digest)));
    await expect(requestReviewInbox()).rejects.toThrow("invalid review inbox item");
  });

  it("parses touchpoints, usage, capabilities, and candidate batch outcomes", async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          items: [
            {
              key: "ai_chat",
              label: "AI 问答",
              state: "disabled",
              reason_code: "BUDGET_EXCEEDED",
              manual_alternative: "查看项目时间线",
            },
          ],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
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
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          items: [
            {
              capability_key: "project_intelligence.risk_suggestion",
              agent_key: "project_intelligence",
              zone: "hard_gate",
              rollout: "live",
              prompt_version: "project-intelligence-v1",
              finding_types: ["risk_suggestion"],
              projections: ["project_context"],
              tools: ["read_project_context"],
              quality_control: "finding_quality_control",
              controls: [],
            },
          ],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ items: [] }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ confirmed: ["risk-1"], already: [], not_found: ["risk-9"] }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const touchpoints = await requestTouchpoints();
    expect(touchpoints[0].state).toBe("disabled");
    expect(touchpoints[0].manual_alternative).toContain("时间线");

    const usage = await requestAiUsage();
    expect(usage.rows[0].total_tokens).toBe(1500);

    const capabilities = await requestCapabilities();
    expect(capabilities[0].zone).toBe("hard_gate");

    const candidates = await requestRiskCandidates("project-1");
    expect(candidates).toEqual([]);

    const outcome = await confirmRiskCandidatesBatch("project-1", ["risk-1", "risk-9"]);
    expect(outcome.confirmed).toEqual(["risk-1"]);
    expect(outcome.not_found).toEqual(["risk-9"]);
  });
});
