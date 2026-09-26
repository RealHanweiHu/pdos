import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TestPlanProposalView, testPlanProposalReady } from "./test-plan-proposal";

const proposal = {
  base_plan_id: "plan", base_digest: "a".repeat(64), summary: "修改建议", messages: ["按客户要求调整"],
  base_items: [{ key: "a", title: "功能", method: "原方法", acceptance_criteria: "原标准", applicable: true }],
  questions: [], changes: [{ operation: "modify", target_key: "a", reason: "客户要求", unresolved: [],
    after: { title: "功能", category: "whole_unit", method: "新方法", acceptance_criteria: "新标准", applicability: "本项目", evidence_requirements: "照片", required: true },
    references: [{ reference_id: "message:1", quote: "按客户要求调整" }] }],
};

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("test plan proposal review", () => {
  it("shows the actual before/after and source without a generic new-risk preview", () => {
    render(<TestPlanProposalView payload={proposal} />);
    expect(screen.getByText("原方法")).toBeInTheDocument();
    expect(screen.getByText("新方法")).toBeInTheDocument();
    expect(screen.getByText("用户要求 1")).toBeInTheDocument();
    expect(screen.queryByText("业务对象尚未创建")).not.toBeInTheDocument();
  });
  it("keeps unresolved or malformed proposals out of acceptance", () => {
    expect(testPlanProposalReady(proposal)).toBe(true);
    expect(testPlanProposalReady({ ...proposal, questions: ["缺少参数"] })).toBe(false);
    expect(testPlanProposalReady({ ...proposal, changes: [] })).toBe(false);
    expect(testPlanProposalReady({ ...proposal, changes: [{ ...proposal.changes[0], unresolved: ["待核实"] }] })).toBe(false);
    expect(testPlanProposalReady({})).toBe(false);
  });
  it("edits proposed values and deselects items while preserving the baseline and conversation", () => {
    const change = vi.fn();
    render(<TestPlanProposalView payload={proposal} onChange={change} />);
    fireEvent.change(screen.getByLabelText("测试方法 · 建议值"), { target: { value: "人工修正方法" } });
    expect(change.mock.lastCall?.[0].changes[0].after.method).toBe("人工修正方法");
    expect(change.mock.lastCall?.[0].base_items).toEqual(proposal.base_items);
    expect(change.mock.lastCall?.[0].messages).toEqual(proposal.messages);
    fireEvent.click(screen.getByRole("button", { name: "取消此项" }));
    expect(change.mock.lastCall?.[0].changes).toEqual([]);
  });
});
