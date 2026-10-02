import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ProductEvidenceProposal } from "./product-evidence-proposal";

const fact = { text: "原假设，实际效果待验证", fact_kind: "hypothesis", sources: [], approval: null, derivation_version: null };
const solutions = ["new_development", "platform_reuse", "upgrade"].map((approach, i) => ({ title: `原方案${i + 1}`, approach, rationale: fact, constraints: [fact], unknowns: ["噪声待验证"] }));
const opportunity = { segment_id: "segment", parent_opportunity_id: "parent", title: "合成分支", importance: null, satisfaction: null, importance_basis: fact, satisfaction_basis: fact, solutions, revision_reason: "保留三方案" };
const experiment = { opportunity_id: "parent", solution_id: "solution-1", dimension: "feasibility", hypothesis: "原实验假设", method: "原方法", sample_basis: "待招募", success_criterion: "达到阈值", falsification_criterion: "未达到阈值", due_at: null, sources: [] };
const targets = [{ kind: "segment", id: "segment", title: "原细分", version: 2 }, { kind: "opportunity", id: "parent", title: "原机会", version: 3, segment_id: "segment", state: "exploring", solutions: solutions.map((s, i) => ({ ...s, id: `solution-${i + 1}` })) }];
const workspace = { current_user_id: "owner", members: [{ id: "owner", display_name: "原发起人", access: "manager" }] };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function setup(capability: "opportunity_mapping" | "experiment_design") {
  const items = [capability === "opportunity_mapping" ? opportunity : experiment];
  const proposal = { capability, items };
  const finding = { id: "finding", run_id: "run", status: "pending_review", proposed_digest: "a".repeat(64), accepted_digest: null, accepted_payload: null, proposed_payload: { assessment: { opportunities: capability === "opportunity_mapping" ? items : [], experiments: capability === "experiment_design" ? items : [] } } };
  const accepted = { ...finding, status: "accepted", accepted_digest: "b".repeat(64), accepted_payload: { proposal } };
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ finding, proposal, targets, calculations: [], sources_current: true, product_line_id: "line", evidence: [] }))
    .mockResolvedValueOnce(Response.json(workspace)).mockResolvedValueOnce(Response.json({ nodes: [], line_access: {} }))
    .mockResolvedValueOnce(Response.json({ finding: accepted, calculations: [] })).mockResolvedValueOnce(Response.json({ finding: { ...accepted, status: "applied" }, records: [{ id: "saved", ...items[0] }] }));
  vi.stubGlobal("fetch", fetcher);
  render(<ProductEvidenceProposal base="spaces/space" runId="run" disabled={false}/>);
  fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新业务候选" }));
  return fetcher;
}

it("reviews all alternatives without request IDs or selecting a winning solution", async () => {
  const fetcher = setup("opportunity_mapping");
  fireEvent.click(await screen.findByRole("button", { name: "查看 / 核对第 1 项" }));
  fireEvent.click(screen.getByRole("button", { name: "修订此条草案" }));
  expect(screen.getByLabelText("细分与目标版本")).toHaveValue("segment");
  expect(screen.getByLabelText("父机会")).toHaveValue("parent");
  expect(screen.getByLabelText("重要度")).toHaveValue(null);
  expect(screen.getByLabelText("机会状态")).toBeDisabled();
  expect(screen.getByLabelText("方案 3 名称")).toHaveValue("原方案3");
  fireEvent.change(screen.getByLabelText("方案 2 名称"), { target: { value: "人工核对的复用方案" } });
  fireEvent.click(screen.getByRole("button", { name: "保存此条核对内容" }));
  expect(fetcher).toHaveBeenCalledTimes(3);
  fireEvent.change(screen.getByLabelText("办理说明"), { target: { value: "已核对三方案" } });
  fireEvent.click(screen.getByRole("button", { name: "接受整批核对内容" }));
  await screen.findByText(/已接受，尚未登记/);
  const item = JSON.parse(String(fetcher.mock.calls[3][1]?.body)).proposal.items[0];
  expect(item.solutions).toHaveLength(3); expect(item.solutions[1].title).toBe("人工核对的复用方案");
  for (const field of ["request_id", "state", "selected_solution_id", "requirement_links", "supersedes_id"]) expect(item).not.toHaveProperty(field);
  expect(item.solutions[0]).not.toHaveProperty("id");
  fireEvent.click(screen.getByRole("button", { name: "独立应用整批记录" }));
  expect(await screen.findByRole("link", { name: /打开已保存第 1 项/ })).toHaveAttribute("href", "/product-work?space=space&tab=opportunities&line=line&history=1#opportunity-saved");
});

it("preserves VUVF criteria and only prepares an experiment draft for the original actor", async () => {
  const fetcher = setup("experiment_design");
  fireEvent.click(await screen.findByRole("button", { name: "查看 / 核对第 1 项" }));
  fireEvent.click(screen.getByRole("button", { name: "修订此条草案" }));
  expect(screen.getByLabelText("机会版本")).toHaveValue("parent");
  expect(screen.getByLabelText("要验证的方案")).toHaveValue("solution-1");
  expect(screen.getByLabelText("验证维度")).toHaveValue("feasibility");
  expect(screen.getByLabelText("实验负责人")).toBeDisabled();
  expect(screen.getByDisplayValue("未达到阈值")).toBeInTheDocument();
  fireEvent.change(screen.getByDisplayValue("原方法"), { target: { value: "人工核对的对照实验" } });
  fireEvent.click(screen.getByRole("button", { name: "保存此条核对内容" }));
  expect(fetcher).toHaveBeenCalledTimes(3);
  fireEvent.change(screen.getByLabelText("办理说明"), { target: { value: "计划待批准与真实实验" } });
  fireEvent.click(screen.getByRole("button", { name: "接受整批核对内容" }));
  await screen.findByText(/已接受，尚未登记/);
  const item = JSON.parse(String(fetcher.mock.calls[3][1]?.body)).proposal.items[0];
  expect(item).toEqual({ ...experiment, method: "人工核对的对照实验" });
  fireEvent.click(screen.getByRole("button", { name: "独立应用整批记录" }));
  expect(await screen.findByRole("link", { name: /打开已保存第 1 项/ })).toHaveAttribute("href", "/product-work?space=space&tab=experiments&line=line&history=1#experiment-saved");
});

it("cannot save a candidate after reducing it below three alternatives", async () => {
  setup("opportunity_mapping");
  fireEvent.click(await screen.findByRole("button", { name: "查看 / 核对第 1 项" }));
  fireEvent.click(screen.getByRole("button", { name: "修订此条草案" }));
  fireEvent.click(screen.getAllByRole("button", { name: "从此次修订移除方案" })[0]);
  expect(screen.getByRole("button", { name: "保存此条核对内容" })).toBeDisabled();
});
