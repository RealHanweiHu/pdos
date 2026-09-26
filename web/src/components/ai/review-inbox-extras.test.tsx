import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewInboxExtras } from "./review-inbox-extras";
import type { AiFinding, ReviewInboxDigest, RiskCandidate } from "./ai-types";

const api = vi.hoisted(() => ({
  archiveStaleFindings: vi.fn(),

  dismissRiskCandidate: vi.fn(),
  restoreFinding: vi.fn(),
  unconfirmRiskCandidate: vi.fn(),
}));

vi.mock("./ai-api", () => api);
const batch = vi.hoisted(() => ({ riskBatch: vi.fn(), rescanRiskCandidates: vi.fn() }));
vi.mock("./risk-candidate-batch-api", async (importOriginal) => ({ ...await importOriginal<typeof import("./risk-candidate-batch-api")>(), ...batch }));

const digest: ReviewInboxDigest = {
  groups: [],
  finding_count: 1,
  risk_candidate_count: 2,
  import_batch_count: 0,
  archived_count: 1,
};

const candidate = (id: string, title: string): RiskCandidate => ({
  id,
  project_id: "project-1",
  title,
  description: "来源任务已逾期",
  likelihood: 3,
  impact: 4,
  score: 12,
  created_at: "2026-08-20T02:00:00Z",
  updated_at: "2026-08-20T02:00:00Z",
});

const archivedFinding = {
  id: "finding-archived",
  title: "旧的风险建议",
  agent_key: "project_intelligence",
  status: "archived",
} as unknown as AiFinding;

describe("ReviewInboxExtras", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/ai-review");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ automatic_enabled: false, ttl_days: 14, batch_size: 200 })));
  });
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  function renderExtras(overrides: Partial<Parameters<typeof ReviewInboxExtras>[0]> = {}) {
    const onNotice = vi.fn();
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    render(
      <ReviewInboxExtras
        archived={overrides.archived ?? []}
        candidatesByProject={
          overrides.candidatesByProject ?? {
            "project-1": [candidate("risk-1", "任务逾期：手板加工"), candidate("risk-2", "任务逾期：夹具设计")],
          }
        }
        digest={overrides.digest ?? digest}
        onNotice={onNotice}
        onRefresh={onRefresh}
        projectNames={{ "project-1": "气泵 A1" }}
      />,
    );
    return { onNotice, onRefresh };
  }

  it("shows the digest counters", () => {
    renderExtras();
    expect(screen.getByText("待审 Finding")).toBeInTheDocument();
    expect(screen.getByText("规则风险候选")).toBeInTheDocument();
    expect(screen.getByText("已归档")).toBeInTheDocument();
  });

  it("does not mount 75 candidate and 25 archive rows until expanded, while preserving counts", async () => {
    renderExtras({
      candidatesByProject: { "project-1": Array.from({ length: 75 }, (_, index) => candidate(`risk-${index}`, `候选 ${index}`)) },
      archived: Array.from({ length: 25 }, (_, index) => ({ ...archivedFinding, id: `archived-${index}`, title: `归档 ${index}` })),
      digest: { ...digest, risk_candidate_count: 75, archived_count: 25 },
    });
    expect(screen.getByRole("button", { name: "展开候选（75）" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: "展开归档（25）" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "恢复" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "展开候选（75）" }));
    expect(screen.getAllByRole("checkbox")).toHaveLength(75);
    await userEvent.click(screen.getByRole("button", { name: "展开归档（25）" }));
    expect(screen.getAllByRole("button", { name: "恢复" })).toHaveLength(25);
  });

  it("previews the diff before batch confirm and supports undo of the batch", async () => {
    let undone = false;
    batch.riskBatch.mockImplementation(async (_projectId, request) => ({
      request_id: typeof request === "string" ? request : request.request_id,
      project_id: "project-1", actor_user_id: "user-1", created_at: "2026-08-20T03:00:00Z", replayed: false,
      results: ["risk-1", "risk-2"].map(risk_id => ({ risk_id, title: risk_id, description: null, score: 12, updated_at: "2026-08-20T03:00:00Z" })),
      current: ["risk-1", "risk-2"].map(id => ({ id, draft_state: undone ? "draft" : "confirmed", status: "open", updated_at: "2026-08-20T03:00:00Z" })),
    }));
    api.unconfirmRiskCandidate.mockImplementation(async () => { undone = true; });
    const user = userEvent.setup();
    const { onRefresh } = renderExtras();

    await user.click(screen.getByRole("button", { name: "展开候选（2）" }));
    await user.click(screen.getByLabelText("选择候选 任务逾期：手板加工"));
    await user.click(screen.getByLabelText("选择候选 任务逾期：夹具设计"));
    await user.click(screen.getByRole("button", { name: "批量确认（2）" }));

    expect(screen.getByRole("dialog", { name: "批量确认预览" })).toBeInTheDocument();
    expect(screen.getAllByText(/草稿 → 已确认/)).toHaveLength(2);
    expect(batch.riskBatch).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "确认写入" }));
    await waitFor(() =>
      expect(batch.riskBatch).toHaveBeenCalledWith("project-1", {
        request_id: expect.any(String), items: [
          { risk_id: "risk-1", expected_updated_at: "2026-08-20T02:00:00Z" },
          { risk_id: "risk-2", expected_updated_at: "2026-08-20T02:00:00Z" },
        ],
      }),
    );
    expect(onRefresh).toHaveBeenCalled();
    expect(screen.getByLabelText("风险批量确认回执")).toHaveTextContent("已确认 2 条");

    await user.click(screen.getByRole("button", { name: "撤销本组未变更的确认（2）" }));
    await waitFor(() => expect(api.unconfirmRiskCandidate).toHaveBeenCalledTimes(2));
    expect(api.unconfirmRiskCandidate).toHaveBeenCalledWith("project-1", "risk-1", "2026-08-20T03:00:00Z");
    expect(api.unconfirmRiskCandidate).toHaveBeenCalledWith("project-1", "risk-2", "2026-08-20T03:00:00Z");
  });

  it("dismisses a single candidate from the free zone", async () => {
    api.dismissRiskCandidate.mockResolvedValue(undefined);
    const user = userEvent.setup();
    const { onNotice } = renderExtras();

    await user.click(screen.getByRole("button", { name: "展开候选（2）" }));
    await user.click(screen.getAllByRole("button", { name: "忽略" })[0]);
    await waitFor(() =>
      expect(api.dismissRiskCandidate).toHaveBeenCalledWith("project-1", "risk-1"),
    );
    await waitFor(() => expect(onNotice).toHaveBeenCalledWith({ status: "候选已忽略" }));
  });

  it("archives stale findings and restores archived ones", async () => {
    api.archiveStaleFindings.mockResolvedValue([archivedFinding]);
    api.restoreFinding.mockResolvedValue(archivedFinding);
    const user = userEvent.setup();
    const { onNotice } = renderExtras({ archived: [archivedFinding] });

    await user.click(screen.getByRole("button", { name: "归档 14 天以上未处理" }));
    await waitFor(() => expect(api.archiveStaleFindings).toHaveBeenCalled());
    expect(onNotice).toHaveBeenCalledWith({ status: "已归档 1 条过期 Finding，可随时恢复" });

    await user.click(screen.getByRole("button", { name: "展开归档（1）" }));
    await user.click(screen.getByRole("button", { name: "恢复" }));
    await waitFor(() => expect(api.restoreFinding).toHaveBeenCalledWith("finding-archived"));
    expect(onNotice).toHaveBeenCalledWith({ status: "Finding 已恢复到待审队列" });
  });
});
