import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ProductEvidenceProposal } from "./product-evidence-proposal";

const fact = { text: "待验证假设", fact_kind: "hypothesis", sources: [], approval: null, derivation_version: null };
const budget = { amount: null, basis: fact };
const solutions = ["new_development", "platform_reuse", "upgrade"].map((approach, i) => ({ id: `s${i}`, title: `方案${i}`, approach, rationale: fact, constraints: [], unknowns: [] }));
const strategy = { opportunity_id: "opportunity", supersedes_id: "old-strategy", title: "策略候选", canvas: Object.fromEntries(["vision", "segment_jtbd", "relative_cost", "value_proposition", "trade_offs", "success_metrics", "growth_path", "capabilities_partners", "defensibility"].map(key => [key, { ...fact, text: key }])), route_comparisons: solutions.map(s => ({ solution_id: s.id, currency: "CNY", price_target: budget, nre_budget: budget, id_cycle_days: budget, modules: [{ key: "motor", name: "电机", target: { amount: "10", basis: fact } }, { key: "control", name: "控制", target: budget }], ...Object.fromEntries(["scope", "quality", "supply", "manufacturing", "resources", "trade_off"].map(key => [key, fact])) })), professional_constraints: ["dqe", "sqe", "ie"].map(discipline => ({ discipline, statement: fact, work_item_id: "work" })), unknowns: ["实际成本未知"], decision_reason: "暂缓选择" };
const spec = { item_key: "pressure", title: "压力规格", target_text: null, target_value: "100", unit: "kPa", tolerance: null, conditions: ["25℃"], priority: "must", required_for_release: true, rationale: fact, verification_method: null, acceptance_criterion: null, verification_stage: null };
const definition = { product_id: "product", strategy_id: "old-strategy", supersedes_id: "old-definition", title: "定义候选", target_users: ["用户"], scenarios: ["现场"], included_features: ["inflate"], excluded_features: ["lighting"], region_constraints: [fact], target_cost: fact, price_position: fact, launch_window: fact, service_requirements: [fact], success_criteria: [fact], items: [spec], change_reason: "合成修订" };
const targets = [{ kind: "opportunity", id: "opportunity", title: "原机会", version: 1, state: "exploring", solutions }, { kind: "strategy", id: "old-strategy", title: "原发布策略", revision_number: 1, state: "published" }, { kind: "definition", id: "old-definition", title: "原发布定义", state: "published", content: { items: [spec] } }, { kind: "product", id: "product", code: "PUMP", name: "产品", lifecycle: "developing" }, { kind: "work", id: "work", title: "原专业工作", action_type: "constraint_review", state: "planned" }];
const workspace = { current_user_id: "owner", members: [{ id: "owner", display_name: "原发起人", access: "manager" }], work_items: [] };
const catalog = { nodes: [], line_access: { line: { can_contribute: true } }, members: [{ product_line_id: "line", user_id: "owner", access: "manager" }] };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function setup(capability: "product_strategy" | "product_definition") {
  const items = [capability === "product_strategy" ? strategy : definition];
  const proposal = { capability, items };
  const finding = { id: "finding", run_id: "run", status: "pending_review", proposed_digest: "a".repeat(64), accepted_digest: null, accepted_payload: null, proposed_payload: { assessment: { [capability === "product_strategy" ? "product_strategies" : "product_definitions"]: items } } };
  const accepted = { ...finding, status: "accepted", accepted_digest: "b".repeat(64), accepted_payload: { proposal } };
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ finding, proposal, targets, calculations: [], sources_current: true, product_line_id: "line", evidence: [] })).mockResolvedValueOnce(Response.json(workspace)).mockResolvedValueOnce(Response.json(catalog)).mockResolvedValueOnce(Response.json({ finding: accepted, calculations: [] })).mockResolvedValueOnce(Response.json({ finding: { ...accepted, status: "applied" }, records: [{ id: "saved", ...items[0] }] }));
  vi.stubGlobal("fetch", fetcher); render(<ProductEvidenceProposal base="spaces/space" runId="run" disabled={false}/>);
  fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新业务候选" })); return fetcher;
}

it("prefills Canvas, route budgets and original professional work without making decisions", async () => {
  const fetcher = setup("product_strategy");
  fireEvent.click(await screen.findByRole("button", { name: "查看 / 核对第 1 项" }));
  fireEvent.click(screen.getByRole("button", { name: "修订此条草案" }));
  expect(screen.getByDisplayValue("vision")).toBeInTheDocument();
  expect(screen.getByDisplayValue("defensibility")).toBeInTheDocument();
  expect(screen.getByLabelText("策略负责人")).toBeDisabled();
  expect(screen.getByLabelText("推荐选择")).toBeDisabled();
  expect(screen.getAllByDisplayValue("原专业工作")).toHaveLength(3);
  fireEvent.change(screen.getByLabelText("策略名称"), { target: { value: "核对后的策略" } });
  fireEvent.click(screen.getByRole("button", { name: "保存此条核对内容" }));
  expect(fetcher).toHaveBeenCalledTimes(3);
  fireEvent.change(screen.getByLabelText("办理说明"), { target: { value: "核对完成" } });
  fireEvent.click(screen.getByRole("button", { name: "接受整批核对内容" }));
  await screen.findByText(/已接受，尚未登记/);
  const item = JSON.parse(String(fetcher.mock.calls[3][1]?.body)).proposal.items[0];
  expect(item).toEqual({ ...strategy, title: "核对后的策略" });
  expect(item).not.toHaveProperty("owner_user_id"); expect(item).not.toHaveProperty("selected_solution_id");
  expect(item.professional_constraints[0]).not.toHaveProperty("disposition");
  fireEvent.click(screen.getByRole("button", { name: "独立应用整批记录" }));
  expect(await screen.findByRole("link", { name: /打开已保存第 1 项/ })).toHaveAttribute("href", "/product-work?space=space&tab=strategies&line=line&history=1#strategy-saved");
});

it("retains original revision keys and leaves specifications and reviewers unconfirmed", async () => {
  const fetcher = setup("product_definition");
  fireEvent.click(await screen.findByRole("button", { name: "查看 / 核对第 1 项" }));
  fireEvent.click(screen.getByRole("button", { name: "修订此条草案" }));
  expect(screen.getByLabelText("产品对象")).toHaveValue("product");
  expect(screen.getByLabelText("产品对象")).toBeDisabled();
  expect(screen.getByLabelText("稳定条目标识")).toHaveAttribute("readonly");
  expect(screen.getByLabelText("确认状态")).toBeDisabled();
  expect(screen.getByLabelText("确认状态")).toHaveValue("needs_confirmation");
  expect(screen.getByLabelText("验证负责人")).toBeDisabled();
  expect(screen.getByLabelText("ID 工业设计")).toBeDisabled();
  expect(screen.getByLabelText("通过判据")).toHaveValue("");
  fireEvent.change(screen.getByLabelText("通过判据"), { target: { value: "人工提出待验证判据" } });
  fireEvent.click(screen.getByRole("button", { name: "保存此条核对内容" }));
  expect(fetcher).toHaveBeenCalledTimes(3);
  fireEvent.change(screen.getByLabelText("办理说明"), { target: { value: "保留原编号，新判据仍待确认" } });
  fireEvent.click(screen.getByRole("button", { name: "接受整批核对内容" }));
  await screen.findByText(/已接受，尚未登记/);
  const item = JSON.parse(String(fetcher.mock.calls[3][1]?.body)).proposal.items[0];
  expect(item.supersedes_id).toBe("old-definition"); expect(item.items[0].item_key).toBe("pressure");
  expect(item.items[0].acceptance_criterion).toBe("人工提出待验证判据");
  for (const key of ["owner_user_id", "state", "disposition_reason"]) expect(item.items[0]).not.toHaveProperty(key);
  expect(item).not.toHaveProperty("reviewers");
  fireEvent.click(screen.getByRole("button", { name: "独立应用整批记录" }));
  expect(await screen.findByRole("link", { name: /打开已保存第 1 项/ })).toHaveAttribute("href", "/product-work?space=space&tab=definitions&line=line&history=1#definition-saved");
});
