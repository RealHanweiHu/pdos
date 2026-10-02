import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProductEvidenceProposal } from "./product-evidence-proposal";

const ref = { tenant_id: "tenant", project_id: null, kind: "evidence_snapshot", ref_id: "source", as_of: "2026-09-15T00:00:00Z", digest: "a".repeat(64), version: null, locator: null };
const observation = { brand: "合成品牌", model: "A", variant: "标准版", competitor_kind: "direct", region: "TEST", channel: "online", configuration: "合成配置", lifecycle: "announced", observed_on: "2026-09-15", identity_sources: [ref], metrics: [{ key: "pressure", label: "压力", number: "100", text: null, unit: "kPa", nature: "claimed", conditions: "25℃", method: null, source_refs: [ref], missing_reason: null }], price_quote: null, certifications: [], notes: "", revision_reason: "核对来源" };
const proposal = { capability: "competitor_analysis", items: [observation, { ...observation, model: "B" }] };
const finding = { id: "finding", run_id: "run", status: "pending_review", proposed_digest: "a".repeat(64), accepted_digest: null, accepted_payload: null, proposed_payload: { assessment: { competitor_observations: proposal.items, market_segments: [] } }, review_comment: null };
const record = { finding, proposal, calculations: [], sources_current: true, product_line_id: null, evidence: [{ id: "source", name: "原始证据", url: null, captured_at: ref.as_of, taint: "untrusted", is_stale: false, superseded: false, has_conflict: false, reference: ref }] };
const workspace = { can_contribute: true, current_user_id: "owner" };
const catalog = { nodes: [], line_access: {} };
const props = { base: "spaces/space", runId: "run", disabled: false };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function fetchSetup(value = record) { return vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(value)).mockResolvedValueOnce(Response.json(workspace)).mockResolvedValueOnce(Response.json(catalog)); }
async function load() { fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新业务候选" })); await screen.findByText(/待核对 · 共 2 项/); }

describe("competitor/market batch candidates", () => {
  it("prefills actual metrics and dates, reviews edited content, then applies separately", async () => {
    const accepted = { ...finding, status: "accepted", accepted_digest: "b".repeat(64), accepted_payload: { proposal }, review_comment: "核对完成" };
    const fetcher = fetchSetup().mockResolvedValueOnce(Response.json({ finding: accepted, calculations: [] })).mockResolvedValueOnce(Response.json({ finding: { ...accepted, status: "applied" }, records: [{ id: "saved-a", ...observation }, { id: "saved-b", ...observation, model: "B" }] }));
    const pendingChange = vi.fn();
    vi.stubGlobal("fetch", fetcher); render(<ProductEvidenceProposal {...props} onPendingChange={pendingChange}/>); await load();
    fireEvent.click(screen.getByRole("button", { name: "查看 / 核对第 1 项" }));
    fireEvent.click(screen.getByRole("button", { name: "修订此条草案" }));
    expect(screen.getByLabelText("观察日期")).toHaveValue("2026-09-15");
    expect(screen.getByLabelText("数值（与文字值二选一）")).toHaveValue(100);
    fireEvent.change(screen.getByLabelText("数值（与文字值二选一）"), { target: { value: "110" } });
    fireEvent.click(screen.getByRole("button", { name: "保存此条核对内容" }));
    expect(fetcher).toHaveBeenCalledTimes(3);
    fireEvent.change(screen.getByLabelText("办理说明"), { target: { value: "核对完成" } });
    fireEvent.click(screen.getByRole("button", { name: "接受整批核对内容" }));
    await screen.findByText(/已接受，尚未登记/);
    const body = JSON.parse(String(fetcher.mock.calls[3][1]?.body));
    expect(body.proposal.items[0].metrics[0].number).toBe("110");
    expect(body.proposal.items[0].metrics[0].source_refs).toEqual([ref]);
    expect(body.proposal.items[0]).not.toHaveProperty("request_id");
    expect(body.proposal.items[0]).not.toHaveProperty("product_line_id");
    expect(body.proposal.items[1]).toEqual(proposal.items[1]);
    expect(fetcher).toHaveBeenCalledTimes(4);
    fireEvent.click(screen.getByRole("button", { name: "独立应用整批记录" }));
    expect(await screen.findByRole("link", { name: /打开已保存第 1 项/ })).toHaveAttribute("href", "/product-work?space=space&tab=competitors&line=&history=1#competitor-saved-a");
    expect(screen.getByRole("link", { name: /打开已保存第 2 项/ })).toHaveAttribute("href", "/product-work?space=space&tab=competitors&line=&history=1#competitor-saved-b");
    expect(JSON.parse(String(fetcher.mock.calls[4][1]?.body))).toEqual({ run_id: "run", finding_id: "finding", accepted_digest: accepted.accepted_digest });
    expect(pendingChange.mock.calls).toEqual([[true], [false], [true], [false]]);
  });
  it("keeps original output readonly and prevents accepting stale sources", async () => {
    const fetcher = fetchSetup({ ...record, sources_current: false });
    vi.stubGlobal("fetch", fetcher); render(<ProductEvidenceProposal {...props}/>); await load();
    fireEvent.click(screen.getByRole("button", { name: "查看原始第 1 项" }));
    expect(screen.queryByLabelText("数值（与文字值二选一）")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "修订此条草案" })).not.toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "返回候选列表" }));
    fireEvent.change(screen.getByLabelText("办理说明"), { target: { value: "来源已变化" } });
    expect(screen.getByRole("button", { name: "接受整批核对内容" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "拒绝此候选" })).toBeEnabled();
  });
  it("clears evidence on denied access during a mutation", async () => {
    const fetcher = fetchSetup().mockResolvedValueOnce(Response.json({ detail: { message: "资料权限已撤回" } }, { status: 403 }));
    const pendingChange = vi.fn();
    vi.stubGlobal("fetch", fetcher); render(<ProductEvidenceProposal {...props} onPendingChange={pendingChange}/>); await load();
    fireEvent.change(screen.getByLabelText("办理说明"), { target: { value: "核对完成" } });
    fireEvent.click(screen.getByRole("button", { name: "接受整批核对内容" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("资料权限已撤回");
    expect(screen.queryByRole("button", { name: "查看 / 核对第 1 项" })).not.toBeInTheDocument();
    expect(pendingChange.mock.calls).toEqual([[true], [false]]);
  });
});

it("prefills market facts and unknown bounds without saving to the manual endpoint", async () => {
  const fact = { text: "通勤需求待验证", fact_kind: "hypothesis", sources: [ref], approval: null, derivation_version: null };
  const item = { title: "合成通勤", job_to_be_done: fact, target_users: [fact], customer_problems: [fact], use_environments: [fact], buying_criteria: [fact], unmet_needs: [fact], outcome: { statement: "减少补气用时", metric_key: "inflation_seconds", unit: "s", baseline_value: null, target_value: "90", measurement_method: "同工况计时", window: "合成验证期", sources: [ref] }, sizing_inputs: { horizon_year: 2027, currency: "CNY", population_unit: "人", boundary: "合成范围", ...Object.fromEntries(["potential_customers", "annual_units_per_customer", "unit_price", "serviceable_share", "obtainable_share"].map(key => [key, { lower: null, upper: null, basis: fact }])) }, revision_reason: "核对候选" };
  const market = { ...record, proposal: { capability: "market_analysis", items: [item] }, finding: { ...finding, proposed_payload: { assessment: { competitor_observations: [], market_segments: [item] } } } };
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(market)).mockResolvedValueOnce(Response.json(workspace)).mockResolvedValueOnce(Response.json(catalog));
  vi.stubGlobal("fetch", fetcher); render(<ProductEvidenceProposal {...props}/>);
  fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新业务候选" }));
  fireEvent.click(await screen.findByRole("button", { name: "查看 / 核对第 1 项" }));
  fireEvent.click(screen.getByRole("button", { name: "修订此条草案" }));
  expect(screen.getByLabelText("现状基线（未知留空）")).toHaveValue(null);
  expect(screen.getByLabelText("期望目标（待定留空）")).toHaveValue(90);
  expect(screen.getAllByLabelText("下界")).toHaveLength(5);
  expect(screen.getAllByLabelText("下界").every(input => (input as HTMLInputElement).value === "")).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "保存此条核对内容" }));
  expect(fetcher).toHaveBeenCalledTimes(3);
  expect(screen.getByRole("button", { name: "接受整批核对内容" })).toBeDisabled();
});

it.each([
  ["competitor_analysis", "competitors", "competitor", "competitor_observations"],
  ["market_analysis", "segments", "segment", "market_segments"],
  ["opportunity_mapping", "opportunities", "opportunity", "opportunities"],
  ["experiment_design", "experiments", "experiment", "experiments"],
  ["product_strategy", "strategies", "strategy", "product_strategies"],
  ["product_definition", "definitions", "definition", "product_definitions"],
])("recovers individual saved links for %s without another application", async (capability, tab, anchor, field) => {
  const accepted = { capability, items: [{ title: "已核对内容" }] };
  const value = { ...record, proposal: accepted, finding: { ...finding, status: "applied", accepted_payload: { proposal: accepted }, proposed_payload: { assessment: { [field]: accepted.items } } }, records: [{ id: "persisted-id", title: "服务端保存记录" }] };
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(value)).mockResolvedValueOnce(Response.json(workspace)).mockResolvedValueOnce(Response.json(catalog));
  vi.stubGlobal("fetch", fetcher); render(<ProductEvidenceProposal {...props}/>);
  fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新业务候选" }));
  expect(await screen.findByRole("link", { name: "打开已保存第 1 项：服务端保存记录" })).toHaveAttribute("href", `/product-work?space=space&tab=${tab}&line=&history=1#${anchor}-persisted-id`);
  expect(screen.queryByRole("button", { name: "独立应用整批记录" })).not.toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(3);
});

it("propagates a real market preview denial and clears the whole private candidate", async () => {
  const fact = { text: "客户的私有研究发现", fact_kind: "hypothesis", sources: [ref], approval: null, derivation_version: null };
  const item = { title: "私有市场候选", job_to_be_done: fact, target_users: [fact], customer_problems: [fact], use_environments: [fact], buying_criteria: [fact], unmet_needs: [fact], outcome: { statement: "私有计量目标", metric_key: "seconds", unit: "s", baseline_value: null, target_value: "90", measurement_method: "私有测量方法", window: "私有周期", sources: [ref] }, sizing_inputs: { horizon_year: 2027, currency: "CNY", population_unit: "人", boundary: "私有市场范围", ...Object.fromEntries(["potential_customers", "annual_units_per_customer", "unit_price", "serviceable_share", "obtainable_share"].map(key => [key, { lower: null, upper: null, basis: fact }])) }, revision_reason: "核对候选" };
  const market = { ...record, proposal: { capability: "market_analysis", items: [item] }, finding: { ...finding, proposed_payload: { assessment: { market_segments: [item] } } }, evidence: [{ ...record.evidence[0], name: "受限客户原文", url: "https://private.example.com/report" }] };
  const calculation = { horizon_year: 2027, currency: "CNY", boundary: "私有市场范围", population_unit: "人", policy_version: "market-bottom-up-v1", estimates: { tam: { annual_units: { lower: "123", upper: "123" }, annual_revenue: { lower: "456", upper: "456" }, units_formula: "potential_customers", revenue_formula: "potential_customers × unit_price" } }, unknown_parameters: [], hypothesis_parameters: [], interpretation: "此前可读的计算回执" };
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(market)).mockResolvedValueOnce(Response.json(workspace)).mockResolvedValueOnce(Response.json(catalog)).mockResolvedValueOnce(Response.json(calculation)).mockResolvedValueOnce(Response.json({ detail: { message: "市场测算权限已撤回" } }, { status: 403 }));
  vi.stubGlobal("fetch", fetcher); const onAccessDenied = vi.fn(), onFailure = vi.fn();
  render(<ProductEvidenceProposal {...props} onAccessDenied={onAccessDenied} onFailure={onFailure}/>);
  fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新业务候选" })); fireEvent.click(await screen.findByRole("button", { name: "查看 / 核对第 1 项" }));
  fireEvent.click(screen.getByRole("button", { name: "修订此条草案" }));
  expect(screen.getByLabelText("细分名称")).toHaveValue("私有市场候选"); expect(screen.getAllByText(/受限客户原文/).length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole("button", { name: "预览当前参数计算结果" })); await screen.findByText("此前可读的计算回执");
  fireEvent.click(screen.getByRole("button", { name: "预览当前参数计算结果" })); expect(await screen.findByRole("alert")).toHaveTextContent("市场测算权限已撤回");
  expect(onAccessDenied).toHaveBeenCalledExactlyOnceWith("市场测算权限已撤回"); expect(onFailure).toHaveBeenCalledExactlyOnceWith("市场测算权限已撤回");
  expect(screen.queryByLabelText("细分名称")).not.toBeInTheDocument(); expect(screen.queryByText(/私有市场候选/)).not.toBeInTheDocument(); expect(screen.queryByText(/受限客户原文/)).not.toBeInTheDocument(); expect(screen.queryByText(/private.example.com/)).not.toBeInTheDocument(); expect(screen.queryByText("此前可读的计算回执")).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: "接受整批核对内容" })).not.toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith("/market-sizing"))).toHaveLength(2); expect(fetcher.mock.calls.some(([url]) => String(url).endsWith("/evidence-ai-review") || String(url).endsWith("/evidence-ai-apply"))).toBe(false);
});
