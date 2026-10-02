import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { StrategyForm, type StrategyContent } from "./strategies";
import type { Solution } from "./opportunities";
import type { Fact } from "./market-segments";
import type { Evidence, ProductCatalog, Workspace } from "./product-work-api";

const reference = { tenant_id: "tenant", kind: "evidence_snapshot", ref_id: "manufacturing-source", digest: "a".repeat(64), as_of: "2026-09-30T12:00:00Z" };
const fact: Fact = { text: "制造能力与工装成本仍须专业验证", fact_kind: "hypothesis", sources: [reference], approval: null, derivation_version: null };
const evidence: Evidence[] = [{ id: reference.ref_id, name: "原制造研究快照", url: null, captured_at: reference.as_of, taint: "untrusted", is_stale: false, superseded: false, has_conflict: false, reference }];
const solutions: Solution[] = ["new_development", "platform_reuse", "upgrade"].map((approach, index) => ({ id: `solution-${index}`, title: `原路线${index + 1}`, approach: approach as Solution["approach"], rationale: fact, constraints: [fact], unknowns: ["制造节拍未验证"] }));
const opportunity = { id: "opportunity", title: "原机会", version: 2, state: "evaluating" as const, is_latest: true, solutions, product_line_id: null };
const workspace: Workspace = { space: { id: "space", code: "SPACE", title: "合成市场空间", lifecycle: "active", version: 1, payload_digest: "b".repeat(64), owner_user_id: "owner", user_groups: [], regions: [], use_scenarios: [], research_questions: [] }, research: [], work_items: [], members: [{ id: "owner", display_name: "原候选发起人", access: "manager" }], available_members: [], can_manage: true, can_collect: false, can_manage_sources: false, can_restore: false, can_contribute: true, current_user_id: "owner" };
const catalog: ProductCatalog = { nodes: [], members: [], line_access: {}, can_create_line: false };
const work = [{ id: "quality-review", title: "DQE待验证工作" }, { id: "supply-review", title: "SQE待验证工作" }, { id: "manufacturing-review", title: "制造工艺待验证工作" }];
function content(manufacturing: "pie" | "ie" = "pie"): StrategyContent {
  return { title: "待核对制造策略", owner_user_id: "owner", canvas: { vision: fact, segment_jtbd: fact, relative_cost: fact, value_proposition: fact, trade_offs: fact, success_metrics: fact, growth_path: fact, capabilities_partners: fact, defensibility: fact }, route_comparisons: solutions.map(solution => ({ solution_id: solution.id, currency: "CNY", price_target: { amount: null, basis: fact }, nre_budget: { amount: null, basis: fact }, id_cycle_days: { amount: null, basis: fact }, modules: [{ key: "tooling", name: "工装每台成本", target: { amount: null, basis: fact } }], scope: fact, quality: fact, supply: fact, manufacturing: fact, resources: fact, trade_off: fact })), selected_solution_id: null, professional_constraints: ["dqe", "sqe", manufacturing].map((discipline, index) => ({ id: `constraint-${index}`, discipline, statement: fact, work_item_id: index === 2 ? null : work[index].id, disposition: null })), unknowns: ["制造节拍未验证", "PIE工装资源条件待核实"], decision_reason: "先补专业验证，不作最终选择" };
}
function renderCandidate(value: StrategyContent) {
  const onReview = vi.fn(), onSaved = vi.fn(), fetcher = vi.fn<typeof fetch>(); vi.stubGlobal("fetch", fetcher);
  render(<StrategyForm initial={null} revise={false} candidate={{ opportunity_id: opportunity.id, content: value }} candidateWork={work} onReview={onReview} opportunities={[opportunity]} workspace={workspace} catalog={catalog} evidence={evidence} base="spaces/space" onSaved={onSaved} onCancel={vi.fn()}/>);
  return { onReview, onSaved, fetcher };
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it.each(["pie", "ie"] as const)("accepts a reviewed candidate with %s manufacturing constraints while retaining its sources and pending professional work", discipline => {
  const original = content(discipline), { onReview, onSaved, fetcher } = renderCandidate(original);
  expect(screen.getAllByLabelText("专业")[2]).toHaveValue(discipline);
  expect(screen.getByLabelText("推荐选择")).toBeDisabled();
  expect(screen.getAllByLabelText("处置")).toHaveLength(3);
  for (const disposition of screen.getAllByLabelText("处置")) { expect(disposition).toBeDisabled(); expect(disposition).toHaveValue(""); }
  fireEvent.change(screen.getAllByLabelText("关联专业评审工作")[2], { target: { value: work[2].id } });
  fireEvent.change(screen.getByLabelText("策略名称"), { target: { value: "人工核对后的制造策略" } });
  const confirm = screen.getByRole("button", { name: "保存此条核对内容" }); expect(confirm).toBeEnabled(); fireEvent.click(confirm);
  expect(onReview).toHaveBeenCalledExactlyOnceWith({ opportunity_id: opportunity.id, content: { ...original, title: "人工核对后的制造策略", professional_constraints: original.professional_constraints.map((constraint, index) => index === 2 ? { ...constraint, work_item_id: work[2].id } : constraint) } });
  expect(onSaved).not.toHaveBeenCalled(); expect(fetcher).not.toHaveBeenCalled();
});

it("allows the manufacturing specialty to be selected as PIE without converting historical IE evidence or dispositions", () => {
  const original = content("ie"), { onReview, fetcher } = renderCandidate(original);
  fireEvent.change(screen.getAllByLabelText("专业")[2], { target: { value: "pie" } });
  fireEvent.change(screen.getAllByLabelText("关联专业评审工作")[2], { target: { value: work[2].id } });
  expect(screen.getAllByLabelText("专业")[2]).toHaveValue("pie"); fireEvent.click(screen.getByRole("button", { name: "保存此条核对内容" }));
  expect(onReview).toHaveBeenCalledExactlyOnceWith({ opportunity_id: opportunity.id, content: { ...original, professional_constraints: original.professional_constraints.map((constraint, index) => index === 2 ? { ...constraint, discipline: "pie", work_item_id: work[2].id } : constraint) } });
  expect(original.professional_constraints[2].discipline).toBe("ie"); expect(original.professional_constraints[2].statement.sources).toEqual([reference]); expect(original.professional_constraints[2].disposition).toBeNull(); expect(fetcher).not.toHaveBeenCalled();
});

it.each(["dqe", "sqe", "pie"] as const)("blocks candidate confirmation when required %s constraints are absent", missing => {
  const original = content(); original.professional_constraints = original.professional_constraints.filter(constraint => constraint.discipline !== missing);
  const { onReview, fetcher } = renderCandidate(original); const confirm = screen.getByRole("button", { name: "保存此条核对内容" }); expect(confirm).toBeDisabled(); fireEvent.click(confirm); expect(onReview).not.toHaveBeenCalled(); expect(fetcher).not.toHaveBeenCalled();
});

it("keeps three-route comparison mandatory even with complete DQE SQE and PIE constraints", () => {
  const original = content(); original.route_comparisons = original.route_comparisons.slice(0, 2);
  const { onReview, fetcher } = renderCandidate(original); const confirm = screen.getByRole("button", { name: "保存此条核对内容" }); expect(confirm).toBeDisabled(); fireEvent.click(confirm); expect(onReview).not.toHaveBeenCalled(); expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("checkbox", { name: "原路线3 · 升级" }));
  expect(screen.getByRole("button", { name: "保存此条核对内容" })).toBeEnabled();
});
