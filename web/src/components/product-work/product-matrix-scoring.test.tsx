import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ProductMatrixCoverage, type CoverageResume, type Result } from "./product-matrix-coverage";
import { ScoringResult, type CoverageScoring, type ScoringPolicy } from "./product-matrix-scoring";

const policy: ScoringPolicy = { formula_version: "product-coverage-weighted.v1", policy_key: "sample", policy_version: 1, title: "合成口径", basis: "合成需求重要性", weights: [{ criterion_key: "a", weight: "0.7", basis: "合成补气" }, { criterion_key: "b", weight: "0.3", basis: "合成照明" }] };
const resume = { record_id: "record", title: "合成对照", choices: [{ product_id: "p1", release_id: "r1" }, { product_id: "p2", release_id: "r2" }], scoring_policy: policy, notice: "重新核对来源", criteria: ["a", "b"].map(key => ({ key, source_locator: "job_to_be_done", interpretation: `合成判据${key}`, mode: "feature", mappings: [], lower: null, upper: null, unit: null, conditions: [] })), prepared: { segment: { id: "segment", title: "合成细分", version: 1, product_line_id: null }, source_digest: "a".repeat(64), source_warnings: [], facts: [{ locator: "job_to_be_done", fact: { text: "合成需求", fact_kind: "hypothesis", sources: [] } }], products: ["p1", "p2"].map(id => ({ id, name: id, code: id, lifecycle: "proposed", release_id: "r", definition_revision: 1, href: "/definition", source_warnings: [], content: { title: "合成定义", owner_user_id: "owner", target_users: [], scenarios: [], included_features: [], excluded_features: [], items: [], reviewers: {}, change_reason: "合成", region_constraints: [], service_requirements: [], success_criteria: [], target_cost: { text: "未知", fact_kind: "hypothesis", sources: [], approval: null, derivation_version: null }, price_position: { text: "未知", fact_kind: "hypothesis", sources: [], approval: null, derivation_version: null }, launch_window: { text: "未知", fact_kind: "hypothesis", sources: [], approval: null, derivation_version: null } } })) } } as CoverageResume;
const points = { score: null, lower_bound: "70", upper_bound: "100", unknown_weight: "0.3", contributions: [{ criterion_key: "a", weight: "0.7", status: "match", points: "70" }, { criterion_key: "b", weight: "0.3", status: "unknown", points: null }] };
const scoring: CoverageScoring = { policy, policy_digest: "d".repeat(64), formula: "合成公式：未知保留区间", scope: "需求覆盖分析", products: [{ product_id: "p1", ...points }], selected_portfolio: points };
const result: Result = { snapshot: resume.prepared, criteria: [], product_summary: [], overlap: [], result_digest: "b".repeat(64), input_digest: "c".repeat(64), formula_version: "market-definition-coverage.v2", formula: "覆盖规则", scope: "当前声明", scoring };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("carries a saved policy through calculation and save and invalidates changed weights", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(result)).mockResolvedValueOnce(Response.json({ id: "saved" }));
  vi.stubGlobal("fetch", fetcher);
  render(<ProductMatrixCoverage base="/spaces/s" choices={resume.choices} resume={resume} onRead={vi.fn()}/>);
  expect(screen.getByLabelText("政策编号")).toHaveValue("sample");
  fireEvent.click(screen.getByLabelText(/我已逐项核对/));
  fireEvent.click(screen.getByRole("button", { name: "计算声明覆盖与重叠" }));
  await screen.findByText(/需求覆盖评分/);
  expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body)).scoring_policy).toEqual(policy);
  fireEvent.change(screen.getByLabelText("保存 / 修订原因"), { target: { value: "保留合成口径" } });
  fireEvent.click(screen.getByRole("button", { name: "保存本次对照" }));
  await screen.findByText(/对照已保存/);
  const body = JSON.parse(String(fetcher.mock.calls[1][1]?.body));
  expect(body.calculation.scoring_policy).toEqual(policy);
  expect(body.supersedes_id).toBe("record");
  fireEvent.change(screen.getByLabelText(/判据 1 权重（/), { target: { value: "0.2" } });
  expect(screen.getByText(/判据或评分政策已改动/)).toBeVisible();
  expect(screen.getByRole("button", { name: "保存本次对照" })).toBeDisabled();
});

it("starts a newly enabled policy with blank weights and explicit basis", () => {
  render(<ProductMatrixCoverage base="/spaces/s" choices={resume.choices} resume={{ ...resume, scoring_policy: null }} onRead={vi.fn()}/>);
  expect(screen.queryByLabelText("政策编号")).not.toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("同时计算需求覆盖分"));
  expect(screen.getByLabelText("政策编号")).toHaveValue("");
  expect(screen.getByLabelText(/判据 1 权重（/)).toHaveValue("");
  expect(screen.getByLabelText("判据 1 权重依据")).toBeRequired();
});

it("renders incomplete product and portfolio scores as ranges", () => {
  render(<ScoringResult value={scoring} name={id => id}/>);
  expect(screen.getAllByText(/待补资料 · 可能区间 70～100 \/ 100/)).toHaveLength(2);
  expect(screen.queryByText(/^70 \/ 100$/)).not.toBeInTheDocument();
  fireEvent.click(screen.getAllByText("逐项权重与得分")[0]);
  expect(screen.getAllByText(/未知，未计确定分/)[0]).toBeVisible();
});

it("rejects invalid calculation without keeping a saveable result", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(result)).mockResolvedValueOnce(Response.json({ detail: { message: "权重之和必须为1" } }, { status: 422 }));
  vi.stubGlobal("fetch", fetcher);
  render(<ProductMatrixCoverage base="/spaces/s" choices={resume.choices} resume={resume} onRead={vi.fn()}/>);
  fireEvent.click(screen.getByLabelText(/我已逐项核对/));
  fireEvent.click(screen.getByRole("button", { name: "计算声明覆盖与重叠" }));
  await screen.findByText(/需求覆盖评分/);
  fireEvent.change(screen.getByLabelText(/判据 1 权重（/), { target: { value: "0.2" } });
  fireEvent.click(screen.getByRole("button", { name: "计算声明覆盖与重叠" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("权重之和必须为1"));
  expect(screen.queryByRole("button", { name: "保存本次对照" })).not.toBeInTheDocument();
});
