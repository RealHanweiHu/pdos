import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { costClosureContext, costSelectionReady } from "./cost-issue-closure-review";
import { MaterialIssueClosureForm } from "./material-issue-closure-review";
import { WorkItemRequestError } from "./project-work-item-api";
import type { ProjectIssue } from "./project-work-item-types";

const issue = { id: "issue", project_id: "project", title: "成本超标", status: "verification", severity: "high", owner_user_id: "owner", verifier_user_id: "verifier", updated_at: "2026-10-01T10:00:00Z", closure_criteria: "同口径成本恢复", resolution: "已议价" } as ProjectIssue;
const reference = { case_id: "cost-case", observation_id: "observation-2", source_digest: "source-2" };
const context = { required: true, ready: true, items: [{ case_id: reference.case_id, title: "硬件 · 单位成本", closure: { ready: true, reasons: [], reference, comparison: { target: { value: "5" }, total: "4", gap: "-1" }, currency: "CNY" } }] };
const card = { item: issue, actor_id: "verifier", permissions: { verify: true }, verification_policy: {}, material_closure: { required: false, ready: true, items: [] }, cost_closure: context };
const choice = "我已核对全部成本来源，引用本次恢复记录";
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("current cost closure", () => {
  it("requires every latest case and rejects missing, duplicate or changed references", () => {
    const other = { ...reference, case_id: "other" };
    const value = costClosureContext({ ...context, items: [...context.items, { ...context.items[0], case_id: "other", closure: { ready: true, reasons: [], reference: other } }] });
    expect(costSelectionReady(value, [reference])).toBe(false);
    expect(costSelectionReady(value, [reference, other])).toBe(true);
    expect(costSelectionReady(value, [reference, { ...other, source_digest: "old" }])).toBe(false);
    expect(costClosureContext({ ...context, items: [...context.items, ...context.items] })).toBeNull();
    expect(costClosureContext({ ...context, items: [] })).toBeNull();
    expect(costSelectionReady(null, null)).toBe(false);
  });

  it("submits the explicitly viewed cost recovery with original Issue version and evidence", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(card)));
    const user = userEvent.setup(), submit = vi.fn().mockResolvedValue(true);
    render(<MaterialIssueClosureForm projectId="project" issue={issue} busy={false} onSubmit={submit} onCancel={vi.fn()}/>);
    await screen.findByRole("checkbox", { name: choice });
    await user.type(screen.getByLabelText(`关闭证据 ${issue.title}`), "独立验证报告");
    expect(screen.getByRole("button", { name: "确认关闭" })).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: choice }));
    await user.click(screen.getByRole("button", { name: "确认关闭" }));
    expect(submit).toHaveBeenCalledWith({ expected_updated_at: issue.updated_at, closure_evidence_ref: "独立验证报告", cost_closures: [reference] });
  });

  it("preserves evidence after a stale-source rejection and requires selection of the new observation", async () => {
    const next = { ...reference, observation_id: "observation-3", source_digest: "source-3" };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(Response.json(card)).mockResolvedValueOnce(Response.json({ ...card, cost_closure: { ...context, items: [{ ...context.items[0], closure: { ...context.items[0].closure, reference: next } }] } })));
    const user = userEvent.setup(), submit = vi.fn().mockRejectedValueOnce(new WorkItemRequestError("成本来源已变化", 409)).mockResolvedValueOnce(true);
    render(<MaterialIssueClosureForm projectId="project" issue={issue} busy={false} onSubmit={submit} onCancel={vi.fn()}/>);
    await screen.findByRole("checkbox", { name: choice });
    await user.type(screen.getByLabelText(`关闭证据 ${issue.title}`), "独立验证报告");
    await user.click(screen.getByRole("checkbox", { name: choice }));
    await user.click(screen.getByRole("button", { name: "确认关闭" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("成本来源已变化");
    expect(screen.getByRole("checkbox", { name: choice })).not.toBeChecked();
    expect(screen.getByLabelText(`关闭证据 ${issue.title}`)).toHaveValue("独立验证报告");
    await user.click(screen.getByRole("button", { name: "刷新当前关闭依据（保留填写内容）" }));
    await screen.findByRole("checkbox", { name: choice });
    expect(screen.getByRole("button", { name: "确认关闭" })).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: choice }));
    await user.click(screen.getByRole("button", { name: "确认关闭" }));
    expect(submit.mock.calls[1][0].cost_closures).toEqual([next]);
  });

  it("blocks closure when the verifier cannot read cost evidence", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ ...card, cost_closure: { required: true, ready: false, items: [], access_denied: true, reason: "当前无权读取成本来源" } })));
    render(<MaterialIssueClosureForm projectId="project" issue={issue} busy={false} onSubmit={vi.fn()} onCancel={vi.fn()}/>);
    await screen.findByText("当前无权读取成本来源");
    expect(screen.getByRole("button", { name: "确认关闭" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: choice })).toBeDisabled();
  });
});
