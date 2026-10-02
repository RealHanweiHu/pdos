import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/projects/cost-gaps", () => ({ CostGaps: () => null }));
vi.mock("@/components/projects/risk-template-fields", () => ({ RiskTemplateFields: () => null }));
vi.mock("@/components/projects/risk-business-references", () => ({ RiskBusinessReferences: () => null }));
vi.mock("@/components/projects/issue-template-fields", () => ({ IssueTemplateFields: () => null }));
vi.mock("@/components/projects/material-exceptions", () => ({ MaterialExceptions: () => null }));
vi.mock("@/components/projects/issue-intake-source", () => ({ IssueIntakeSource: () => null }));
vi.mock("@/components/projects/decision-intake-source", () => ({ DecisionSourceRows: () => null }));

import { IssueRiskWorkCard } from "./issue-risk-work-card";

const reference = { exception_id: "material-exception", review_id: "named-review", source_digest: "current-source" };
const card = {
  item: { id: "issue", project_id: "project", status: "verification", title: "电机缺料", severity: "high", owner_user_id: "owner", verifier_user_id: "verifier", target_date: "2026-09-30", closure_criteria: "齐备后验证", updated_at: "2026-09-30T01:00:00Z" },
  actor_id: "verifier", permissions: { edit: true, assign: true, execute: true, verify: true }, verification_policy: {}, people: [{ id: "owner", name: "原负责人", active: true }, { id: "verifier", name: "原验证人", active: true }],
  material_closure: { required: true, ready: true, items: [{ exception_id: reference.exception_id, title: "电机恢复", closure: { ready: true, reasons: [], reference } }] },
};
const choice = "我已核对以上全部来源，引用本次物料恢复记录";
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

async function openCard() {
  const user = userEvent.setup();
  render(<IssueRiskWorkCard projectId="project" itemId="issue" kind="issues" onChanged={vi.fn().mockResolvedValue(undefined)} onNotice={vi.fn()}/>);
  await user.click(screen.getByText("查看依据并办理问题"));
  await screen.findByText("电机恢复 · 当前复核可供关闭验证");
  await user.type(screen.getByLabelText("验证及关闭证据"), "具名验证报告");
  await user.click(screen.getByRole("checkbox", { name: choice }));
  return user;
}

describe("material closure in My Work", () => {
  it("lets the original verifier select and submit sources directly from the work card", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(Response.json(card)).mockResolvedValueOnce(Response.json({ ...card.item, status: "closed" })).mockResolvedValueOnce(Response.json({ ...card, item: { ...card.item, status: "closed" } }));
    vi.stubGlobal("fetch", fetcher);
    const user = await openCard();
    await user.click(screen.getByRole("button", { name: "验证通过并关闭" }));
    await screen.findByText("电机缺料 · 已关闭");
    expect(fetcher.mock.calls[1][0]).toBe("/api/projects/project/issues/issue/transitions");
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({ to_status: "closed", expected_updated_at: card.item.updated_at, closure_evidence_ref: "具名验证报告", material_closures: [reference] });
  });

  it("clears stale 409 references while retaining the original evidence", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(Response.json(card)).mockResolvedValueOnce(Response.json({ detail: { message: "供给来源已更新" } }, { status: 409 })));
    const user = await openCard();
    await user.click(screen.getByRole("button", { name: "验证通过并关闭" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("供给来源已更新");
    expect(screen.getByRole("checkbox", { name: choice })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: choice })).toBeDisabled();
    expect(screen.getByLabelText("验证及关闭证据")).toHaveValue("具名验证报告");
    expect(screen.getByRole("button", { name: "验证通过并关闭" })).toBeDisabled();
  });

  it("removes actionable source data on a 403 response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(Response.json(card)).mockResolvedValueOnce(Response.json({ detail: { message: "供给权限已撤销" } }, { status: 403 })));
    const user = await openCard();
    await user.click(screen.getByRole("button", { name: "验证通过并关闭" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("供给权限已撤销");
    expect(screen.queryByRole("checkbox", { name: choice })).not.toBeInTheDocument();
    expect(screen.queryByText("电机恢复 · 当前复核可供关闭验证")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "验证通过并关闭" })).not.toBeInTheDocument();
  });
});
