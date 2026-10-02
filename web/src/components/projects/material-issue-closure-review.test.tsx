import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WorkItemRequestError } from "./project-work-item-api";
import { MaterialIssueClosureForm, linkedMaterialReference, materialClosureContext, materialSelectionReady } from "./material-issue-closure-review";
import type { ProjectIssue } from "./project-work-item-types";

const issue: ProjectIssue = { id: "issue", project_id: "project", title: "样机物料不足", description: null, stage_id: null, owner_user_id: "owner", verifier_user_id: "verifier", reported_by_user_id: "owner", issue_type: "supplier", status: "verification", severity: "high", root_cause: null, resolution: "已到料并复核", closure_criteria: "齐备后复核", closure_evidence_ref: null, reopen_count: 0, target_date: "2026-09-30", closed_at: null, created_at: "2026-09-27T10:00:00Z", updated_at: "2026-09-27T10:00:00Z" };
const ref = { exception_id: "exception", review_id: "review-1", source_digest: "digest-1" };
const context = { required: true, ready: true, items: [{ exception_id: ref.exception_id, title: "控制器物料恢复", closure: { ready: true, reasons: [], reference: ref } }] };
const card = { item: issue, permissions: { verify: true }, actor_id: "verifier", verification_policy: {}, material_closure: context };
const choice = "我已核对以上全部来源，引用本次物料恢复记录";
afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.replaceState(null, "", "/"); });

async function readyForm(onSubmit = vi.fn().mockResolvedValue(true)) {
  const user = userEvent.setup();
  render(<MaterialIssueClosureForm projectId="project" issue={issue} busy={false} onSubmit={onSubmit} onCancel={vi.fn()}/>);
  await screen.findByText("控制器物料恢复 · 当前复核可供关闭验证");
  await user.type(screen.getByLabelText(`关闭证据 ${issue.title}`), "报告 203");
  return { user, onSubmit };
}

describe("material closure references", () => {
  it("requires precise coverage of every current exception and rejects malformed or duplicate sources", () => {
    const second = { exception_id: "other", review_id: "review-2", source_digest: "digest-2" };
    const current = materialClosureContext({ ...context, items: [...context.items, { exception_id: second.exception_id, title: "线束恢复", closure: { ready: true, reasons: [], reference: second } }] });
    expect(materialSelectionReady(current, [ref])).toBe(false);
    expect(materialSelectionReady(current, [ref, second])).toBe(true);
    expect(materialSelectionReady(current, [ref, { ...second, source_digest: "old" }])).toBe(false);
    expect(materialClosureContext({ ...context, items: [...context.items, ...context.items] })).toBeNull();
    expect(materialClosureContext({ ...context, items: [] })).toBeNull();
  });

  it("binds a supplied URL reference only to its original project and Issue", () => {
    const search = "?project=project&entity_id=issue&material_exception_id=exception&material_review_id=review-1&material_source_digest=digest-1";
    expect(linkedMaterialReference("project", "issue", search)).toEqual(ref);
    expect(linkedMaterialReference("other", "issue", search)).toBeNull();
    expect(linkedMaterialReference("project", "other", search)).toBeNull();
  });

  it("requires explicit selection and sends the exact viewed sources with the original Issue version", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(card)));
    const { user, onSubmit } = await readyForm();
    expect(screen.getByRole("button", { name: "确认关闭" })).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: choice }));
    await user.click(screen.getByRole("button", { name: "确认关闭" }));
    expect(onSubmit).toHaveBeenCalledWith({ expected_updated_at: issue.updated_at, closure_evidence_ref: "报告 203", material_closures: [ref] });
  });

  it("keeps the old linked proof visible but never selects its replacement automatically", async () => {
    window.history.replaceState(null, "", "?project=project&entity_id=issue&material_exception_id=exception&material_review_id=old-review&material_source_digest=old-digest");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(card)));
    await readyForm();
    expect(screen.getByText(/供应入口带来的记录已过期/)).toBeVisible();
    expect(screen.getByText(/原核对记录：old-review/)).toBeVisible();
    expect(screen.getByRole("checkbox", { name: choice })).not.toBeChecked();
    expect(screen.getByRole("button", { name: "确认关闭" })).toBeDisabled();
  });

  it("clears rejected 409 references, preserves evidence and requires a fresh explicit selection", async () => {
    const next = { ...ref, review_id: "review-2", source_digest: "digest-2" };
    const fetcher = vi.fn().mockResolvedValueOnce(Response.json(card)).mockResolvedValueOnce(Response.json({ ...card, item: { ...issue, updated_at: "2026-09-30T12:00:00Z" }, material_closure: { ...context, items: [{ ...context.items[0], closure: { ready: true, reasons: [], reference: next } }] } }));
    vi.stubGlobal("fetch", fetcher);
    const onSubmit = vi.fn().mockRejectedValueOnce(new WorkItemRequestError("当前物料来源已变化", 409)).mockResolvedValueOnce(true);
    const { user } = await readyForm(onSubmit);
    await user.click(screen.getByRole("checkbox", { name: choice }));
    await user.click(screen.getByRole("button", { name: "确认关闭" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("当前物料来源已变化");
    expect(screen.getByRole("checkbox", { name: choice })).not.toBeChecked();
    expect(screen.getByLabelText(`关闭证据 ${issue.title}`)).toHaveValue("报告 203");
    expect(screen.getByRole("button", { name: "确认关闭" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "刷新当前关闭依据（保留填写内容）" }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    await screen.findByText("原问题资料已更新，请按本次读取的记录重新核对关闭条件。");
    expect(screen.getByRole("checkbox", { name: choice })).not.toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: choice }));
    await user.click(screen.getByRole("button", { name: "确认关闭" }));
    expect(onSubmit.mock.calls[1][0]).toMatchObject({ expected_updated_at: "2026-09-30T12:00:00Z", material_closures: [next], closure_evidence_ref: "报告 203" });
  });

  it("removes executable source details after 403 and does not leak denied source IDs on refresh", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(Response.json(card)).mockResolvedValueOnce(Response.json({ ...card, material_closure: { required: true, ready: false, items: [], access_denied: true, reason: "当前没有供给来源查看权限" } }));
    vi.stubGlobal("fetch", fetcher);
    const { user } = await readyForm(vi.fn().mockRejectedValue(new WorkItemRequestError("当前查看权限已变化", 403)));
    await user.click(screen.getByRole("checkbox", { name: choice }));
    await user.click(screen.getByRole("button", { name: "确认关闭" }));
    await screen.findByRole("alert");
    expect(screen.queryByRole("checkbox", { name: choice })).not.toBeInTheDocument();
    expect(screen.queryByText("控制器物料恢复 · 当前复核可供关闭验证")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "刷新当前关闭依据（保留填写内容）" }));
    expect(await screen.findByText("当前没有供给来源查看权限")).toBeVisible();
    expect(screen.queryByRole("checkbox", { name: choice })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认关闭" })).toBeDisabled();
    expect(screen.getByLabelText(`关闭证据 ${issue.title}`)).toHaveValue("报告 203");
  });

  it("retains the viewed reference and text when the network receipt is unknown", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(card)));
    const { user } = await readyForm(vi.fn().mockRejectedValue(new TypeError("网络回执未知")));
    await user.click(screen.getByRole("checkbox", { name: choice }));
    await user.click(screen.getByRole("button", { name: "确认关闭" }));
    await screen.findByRole("alert");
    expect(screen.getByRole("checkbox", { name: choice })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: choice })).toBeDisabled();
    expect(screen.getByLabelText(`关闭证据 ${issue.title}`)).toHaveValue("报告 203");
    expect(screen.getByRole("button", { name: "确认关闭" })).toBeDisabled();
  });

  it("keeps ordinary low Issue closure free of material references and mandatory evidence", async () => {
    const ordinary = { ...issue, severity: "low" as const };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ ...card, item: ordinary, material_closure: { required: false, ready: true, items: [] } })));
    const onSubmit = vi.fn().mockResolvedValue(true);
    const user = userEvent.setup();
    render(<MaterialIssueClosureForm projectId="project" issue={ordinary} busy={false} onSubmit={onSubmit} onCancel={vi.fn()}/>);
    await screen.findByText(`${issue.title} · 本次关闭验证`);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认关闭" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "确认关闭" }));
    expect(onSubmit).toHaveBeenCalledWith({ expected_updated_at: issue.updated_at });
  });

  it("honors the current low Issue four-eye policy and does not allow an owner to verify", async () => {
    const ordinary = { ...issue, severity: "low" as const };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ ...card, item: ordinary, actor_id: "owner", verification_policy: { issue_verify_low: true }, material_closure: { required: false, ready: true, items: [] } })));
    render(<MaterialIssueClosureForm projectId="project" issue={ordinary} busy={false} onSubmit={vi.fn()} onCancel={vi.fn()}/>);
    expect(await screen.findByText(/当前身份或问题状态不满足/)).toBeVisible();
    expect(screen.getByRole("button", { name: "确认关闭" })).toBeDisabled();
  });
});
