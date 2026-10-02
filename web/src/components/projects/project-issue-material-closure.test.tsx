import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";

vi.mock("./issue-intake-source", () => ({ IssueIntakeSource: () => null }));
vi.mock("./material-exceptions", () => ({ MaterialExceptions: () => null }));
vi.mock("./decision-intake-source", () => ({ DecisionSourceRows: () => null }));
vi.mock("./supplier-notice-links", () => ({ SupplierNoticeLinks: () => null }));
vi.mock("./cost-gaps", () => ({ CostGaps: () => null }));
vi.mock("./issue-template-fields", () => ({ IssueTemplateFields: () => null }));
vi.mock("@/components/quality/issue-quality-links", () => ({ IssueQualityLinks: () => null }));

import { IssuePanel } from "./project-work-items";
import { transitionIssue } from "./project-work-item-api";
import type { ProjectIssue } from "./project-work-item-types";

const issue: ProjectIssue = { id: "issue", project_id: "project", title: "线束恢复验证", description: null, stage_id: null, owner_user_id: "owner", verifier_user_id: "verifier", reported_by_user_id: "owner", issue_type: "supplier", status: "verification", severity: "low", root_cause: null, resolution: "线束补齐", closure_criteria: "数量核对一致", closure_evidence_ref: null, reopen_count: 0, target_date: "2026-09-30", closed_at: null, created_at: "2026-09-27T10:00:00Z", updated_at: "2026-09-27T10:00:00Z" };
const reference = { exception_id: "exception", review_id: "review", source_digest: "source" };
const card = { item: issue, actor_id: "verifier", permissions: { verify: true }, verification_policy: {}, material_closure: { required: true, ready: true, items: [{ exception_id: reference.exception_id, title: "线束到料", closure: { ready: true, reasons: [], reference } }] } };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("opens current source verification in the project IssuePanel before allowing low Issue closure", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(card)));
  const onTransition = vi.fn().mockResolvedValue(true);
  const user = userEvent.setup();
  render(<IssuePanel projectId="project" busy={false} issues={[issue]} onCreate={vi.fn()} onTransition={onTransition}/>);
  await user.click(screen.getByRole("button", { name: "验证通过并关闭" }));
  await screen.findByText("线束到料 · 当前复核可供关闭验证");
  expect(onTransition).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "确认关闭" })).toBeDisabled();
  await user.click(screen.getByRole("checkbox", { name: "我已核对以上全部来源，引用本次物料恢复记录" }));
  await user.click(screen.getByRole("button", { name: "确认关闭" }));
  expect(onTransition).toHaveBeenCalledWith(issue, "closed", { expected_updated_at: issue.updated_at, material_closures: [reference] });
});

it("carries typed sources and the original version through the real Issue API helper", async () => {
  const fetcher = vi.fn().mockResolvedValue(Response.json({ ...issue, status: "closed" }));
  vi.stubGlobal("fetch", fetcher);
  await transitionIssue("project", "issue", "closed", { expected_updated_at: issue.updated_at, material_closures: [reference] });
  expect(fetcher.mock.calls[0][0]).toBe("/api/projects/project/issues/issue/transitions");
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ to_status: "closed", expected_updated_at: issue.updated_at, material_closures: [reference] });
});
