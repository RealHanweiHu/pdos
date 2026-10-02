import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ProjectIssue } from "./project-work-item-types";

vi.mock("./issue-intake-source", () => ({ IssueIntakeSource: () => null }));
vi.mock("./material-exceptions", () => ({ MaterialExceptions: () => null }));
vi.mock("./decision-intake-source", () => ({ DecisionSourceRows: () => null }));
vi.mock("./supplier-notice-links", () => ({ SupplierNoticeLinks: () => null }));
vi.mock("./cost-gaps", () => ({ CostGaps: () => null }));
vi.mock("./issue-template-fields", () => ({ IssueTemplateFields: () => null }));
vi.mock("@/components/quality/issue-quality-links", () => ({ IssueQualityLinks: () => null }));

import { IssuePanel } from "./project-work-items";
const issue: ProjectIssue = { id: "issue", project_id: "project", title: "样机振动异常", description: null, stage_id: null, owner_user_id: null, verifier_user_id: null, reported_by_user_id: null, created_by_ai_principal_id: "55555555-5555-4555-8555-555555555555", ai_writer_name: "PDOS Agent", issue_type: "test_failure", status: "open", severity: "medium", root_cause: null, resolution: null, closure_criteria: null, closure_evidence_ref: null, reopen_count: 0, target_date: null, closed_at: null, created_at: "2026-09-27T10:00:00Z", updated_at: "2026-09-27T10:00:00Z" };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
describe("issue creator attribution", () => {
  it("shows independent AI creation without assigning it to a human responsibility or adding fake actions", () => {
    render(<IssuePanel projectId="project" busy={false} issues={[issue]} onCreate={async () => false} onTransition={async () => false} />);
    expect(screen.getByText("PDOS Agent · AI 创建")).toBeVisible();
    expect(screen.queryByRole("button", { name: /撤回/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /PDOS Agent/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/负责人.*PDOS Agent/)).not.toBeInTheDocument();
  });
  it("preserves an old human card without adding an AI label", () => {
    const human = { ...issue, reported_by_user_id: "user", created_by_ai_principal_id: undefined, ai_writer_name: undefined };
    render(<IssuePanel projectId="project" busy={false} issues={[human]} onCreate={async () => false} onTransition={async () => false} />);
    expect(screen.getByText("样机振动异常")).toBeVisible();
    expect(screen.queryByText(/AI 创建/)).not.toBeInTheDocument();
  });
  it("shows withdrawn cards without the analysis action", () => {
    render(<IssuePanel projectId="project" busy={false} issues={[{ ...issue, withdrawn_at: "2026-09-27T16:00:00Z", ai_withdrawal_id: "88888888-8888-4888-8888-888888888888" }]} onCreate={async () => false} onTransition={async () => false} />);
    expect(screen.getByText("PDOS Agent · AI 创建 · 已撤回")).toBeVisible();
    expect(screen.queryByRole("button", { name: "进入分析" })).not.toBeInTheDocument();
  });
  it("loads a withdrawn deep link as separate read-only history without adding to the current list", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ ...issue, withdrawn_at: "2026-09-27T16:00:00Z", ai_withdrawal_id: "88888888-8888-4888-8888-888888888888", description: "原测试振动超标说明" }));
    vi.stubGlobal("fetch", fetcher);
    render(<IssuePanel projectId="project" focusedIssueId="issue" busy={false} issues={[]} onCreate={async () => false} onTransition={async () => false} />);
    expect(await screen.findByText("PDOS Agent · AI 创建 · 已撤回")).toBeVisible();
    expect(screen.getByText("原问题历史 · 不计入当前问题数")).toBeVisible(); expect(screen.getByText("还没有问题。")).toBeVisible();
    expect(screen.getByText("原测试振动超标说明")).toBeVisible(); expect(screen.queryByRole("button", { name: "进入分析" })).not.toBeInTheDocument();
    expect(fetcher.mock.calls[0][0]).toBe("/api/projects/project/issues/issue");
  });

  it("does not leave an Issue error or loading panel for another kind of work-item deep link", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(Response.json({ detail: "未找到问题" }, { status: 404 })));
    render(<IssuePanel projectId="project" focusedIssueId="task" busy={false} issues={[]} onCreate={async () => false} onTransition={async () => false} />);
    await waitFor(() => expect(screen.queryByLabelText("原问题历史")).not.toBeInTheDocument());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

});
