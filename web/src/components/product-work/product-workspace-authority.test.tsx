import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ProductWorkspace } from "./product-workspace";
import type { Research } from "./product-work-api";
vi.mock("next/navigation", async () => {
  const { useSyncExternalStore } = await import("react");
  const replace = vi.fn();
  const subscribe = (fn: () => void) => { window.addEventListener("popstate", fn); return () => window.removeEventListener("popstate", fn); };
  return { useRouter: () => ({ replace }), useSearchParams: () => new URLSearchParams(useSyncExternalStore(subscribe, () => window.location.search)) };
});
vi.mock("@/components/workspace-api", () => ({ requestIdentity: async () => ({ user: { role: "product_manager" }, tenant: {} }) }));
vi.mock("@/components/workspace-shell", () => ({ WorkspaceShell: ({ children }: { children: ReactNode }) => <main>{children}</main> }));
vi.mock("./work-responsibility", () => ({ WorkResponsibility: () => null, WorkResponsibilityLanding: () => null }));
vi.mock("./product-catalog", () => ({ ProductTree: () => null, SpaceSettings: () => null }));
vi.mock("./product-source-files", () => ({ ProductSourceFiles: () => null }));
vi.mock("./research-collection", () => ({ ResearchCollection: () => null }));
vi.mock("./product-ai-preparation", () => ({ ProductAiPreparation: () => null }));
const ref = { tenant_id: "tenant", kind: "evidence_snapshot", ref_id: "snapshot", as_of: "2026-09-30T00:00:00Z", digest: "a".repeat(64) };
const space = { id: "one", code: "ONE", title: "共享空间", lifecycle: "active", version: 1, payload_digest: "b".repeat(64), owner_user_id: "owner", user_groups: [], regions: [], use_scenarios: [], research_questions: [] };
const source = { id: "snapshot", name: "私有来源名称", url: null, captured_at: ref.as_of, taint: "untrusted", is_stale: false, superseded: false, has_conflict: false, reference: ref };
const workspace = { space, current_user_id: "owner", members: [{ id: "owner", display_name: "私有负责人", access: "manager" }], available_members: [], can_manage: false, can_contribute: true, can_collect: false,
  research: [{ id: "research", product_line_id: null, owner_user_id: "owner", version: 1, payload_digest: "c".repeat(64), question: "私有研究问题", state: "completed", method: "私有方法", time_scope: "本期", expected_decision: "私有决定", stop_conditions: ["完成"], conclusion: "私有研究结论", findings: ["私有发现"], unresolved: [], sources: [ref] }],
  work_items: [{ id: "work", product_line_id: null, title: "私有专业工作", version: 1, payload_digest: "d".repeat(64), state: "completed", owner_user_id: "owner", receiver_user_id: null, action_type: "evidence_collection", acceptance_required: false, expected_output: "私有输出", completion_criteria: "核对正文", result_note: "私有办理结论", due_at: null, evidence: [] }] };
const catalog = { nodes: [], members: [], line_access: {}, can_create_line: false };
let fetcher: ReturnType<typeof vi.fn<typeof fetch>>;
let status: number;
let pending: Promise<Response> | null;
let resolvePending: (response: Response) => void;
let reads: number;
let researchOverrides: Partial<Research>;
beforeEach(() => {
  status = 403; pending = null; reads = 0; researchOverrides = {};
  window.history.replaceState(null, "", "/product-work?space=one&tab=research");
  fetcher = vi.fn<typeof fetch>().mockImplementation(async input => {
    const path = String(input);
    if (path.endsWith("/spaces")) return Response.json({ items: [space], can_create: false });
    if (path.endsWith("/evidence/snapshot/content")) return status === 200 ? Response.json({ snapshot_id: "snapshot", content_digest: ref.digest, content: "私有原文正文" }) : Response.json({ detail: { message: "引用权限已撤回" } }, { status });
    if (path.split("?")[0].endsWith("/evidence")) return Response.json({ items: [source] });
    if (path.endsWith("/products")) return Response.json(catalog);
    if (path.endsWith("/spaces/one")) { reads++; return pending ?? Response.json({ ...workspace, research: [{ ...workspace.research[0], ...researchOverrides }] }); }
    throw new Error(`Unexpected request ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
function expectCleared() {
  for (const text of ["私有研究问题", "私有研究结论", "私有方法", "私有决定", "私有专业工作", "私有办理结论", "私有来源名称", "私有负责人", "私有原文正文"]) expect(screen.queryByText(text, { exact: false })).not.toBeInTheDocument();
  expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("研究问题")).not.toBeInTheDocument();
}
it.each([401, 403])("clears parent private data on real citation %s and requires explicit retry despite parent callback retransmission", async deniedStatus => {
  status = 200;
  const view = render(<ProductWorkspace/>);
  await screen.findByText("私有研究结论");
  fireEvent.click(screen.getByRole("button", { name: "查看此引用的原快照" }));
  await screen.findByText("私有原文正文");
  fireEvent.click(screen.getByRole("button", { name: "手动建研究任务" }));
  fireEvent.change(screen.getByLabelText("研究问题"), { target: { value: "未提交私有草稿" } });
  status = deniedStatus;
  fireEvent.click(screen.getByRole("button", { name: "查看此引用的原快照" }));
  await screen.findByRole("button", { name: "重试" });
  expectCleared();
  expect(screen.queryByDisplayValue("未提交私有草稿")).not.toBeInTheDocument();
  const before = fetcher.mock.calls.length;
  // The real parent passes a freshly created callback on rerender of the same scope.
  view.rerender(<ProductWorkspace/>);
  await act(async () => { await Promise.resolve(); });
  expectCleared(); expect(fetcher.mock.calls.length).toBe(before);
  status = 200;
  fireEvent.click(screen.getByRole("button", { name: "重试" }));
  await screen.findByText("私有研究结论");
  expect(await screen.findByText("私有来源名称", { exact: false })).toBeInTheDocument();
  expect(screen.queryByLabelText("研究问题")).not.toBeInTheDocument();
});
it("does not restore private parent data from a full workspace refresh already in flight before citation denial", async () => {
  render(<ProductWorkspace/>); await screen.findByText("私有研究结论");
  pending = new Promise<Response>(resolve => { resolvePending = resolve; });
  fireEvent.click(screen.getByRole("button", { name: "刷新工作与来源" }));
  await waitFor(() => expect(reads).toBe(2));
  fireEvent.click(screen.getByRole("button", { name: "查看此引用的原快照" }));
  await screen.findByRole("button", { name: "重试" }); expectCleared();
  await act(async () => { resolvePending(Response.json(workspace)); await Promise.resolve(); });
  expectCleared(); expect(reads).toBe(2);
  expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
});

function marketRecords() {
  const fact = { text: "合成待验证依据", fact_kind: "hypothesis", sources: [], approval: null, derivation_version: null };
  const parameter = { lower: null, upper: null, basis: fact };
  return { items: [{ id: "market", title: "私有市场细分", product_line_id: null, supersedes_id: null, version: 1, created_at: ref.as_of, is_latest: true, source_warnings: [], revision_reason: "原修订", job_to_be_done: fact, target_users: [fact], customer_problems: [fact], use_environments: [fact], buying_criteria: [fact], unmet_needs: [fact], outcome: { statement: "合成可衡量目标", metric_key: "seconds", unit: "s", baseline_value: null, target_value: null, measurement_method: "合成计时", window: "本期", sources: [] }, sizing_inputs: { horizon_year: 2027, currency: "CNY", population_unit: "家", boundary: "合成范围", potential_customers: parameter, annual_units_per_customer: parameter, unit_price: parameter, serviceable_share: parameter, obtainable_share: parameter }, sizing_result: { horizon_year: 2027, currency: "CNY", boundary: "合成范围", population_unit: "家", policy_version: "market-bottom-up-v1", estimates: {}, unknown_parameters: [], hypothesis_parameters: [], interpretation: "仅合成参数" } }] };
}
it.each([200, 403])("holds the actual workspace navigation for an uncertain market save until original retry returns %s", async nextStatus => {
  window.history.replaceState(null, "", "/product-work?space=one&tab=segments");
  const initialFetch = fetcher.getMockImplementation()!;
  let writeStatus = 503;
  fetcher.mockImplementation(async (input, init) => {
    if (String(input).endsWith("/market-segments")) return init?.method === "POST" ? Response.json({ detail: { message: writeStatus === 503 ? "保存回执暂未取得" : "市场权限已撤回" } }, { status: writeStatus }) : Response.json(marketRecords());
    return initialFetch(input, init);
  });
  render(<ProductWorkspace/>);
  fireEvent.click(await screen.findByRole("button", { name: "追加修订" }));
  fireEvent.change(screen.getByLabelText("记录 / 修订原因"), { target: { value: "合成修订原因" } });
  fireEvent.submit(screen.getByLabelText("细分名称").closest("form")!);
  await screen.findByText("保存回执暂未取得");
  expect(screen.getByRole("button", { name: /^市场空间$/ })).toBeDisabled();
  expect(screen.getByRole("button", { name: "刷新工作与来源" })).toBeDisabled();
  for (const tab of screen.getAllByRole("tab")) expect(tab).toBeDisabled();
  expect(screen.getByLabelText("细分名称")).toBeDisabled();
  const writesBefore = fetcher.mock.calls.filter(([input, init]) => String(input).endsWith("/market-segments") && init?.method === "POST");
  expect(writesBefore).toHaveLength(1);
  writeStatus = nextStatus;
  fireEvent.click(screen.getByRole("button", { name: "按原请求重试保存" }));
  if (nextStatus === 200) await screen.findByRole("button", { name: "追加修订" });
  else { await screen.findByRole("button", { name: "重试" }); expectCleared(); }
  await waitFor(() => expect(screen.getByRole("button", { name: /^市场空间$/ })).toBeEnabled());
  const writes = fetcher.mock.calls.filter(([input, init]) => String(input).endsWith("/market-segments") && init?.method === "POST");
  expect(writes).toHaveLength(2); expect(writes[0][1]?.body).toBe(writes[1][1]?.body);
  if (nextStatus === 200) expect(screen.getByRole("button", { name: "刷新工作与来源" })).toBeEnabled();
});

async function activeResearch() {
  researchOverrides = { state: "active", conclusion: null, findings: [], sources: [] };
  render(<ProductWorkspace/>);
  fireEvent.click(await screen.findByText("提交结论或取消"));
  fireEvent.change(screen.getByLabelText("结论 / 取消原因"), { target: { value: "本期未发现可确认的差异" } });
}
it("requires a currently available snapshot even for a conclusion with no findings", async () => {
  await activeResearch();
  expect(screen.getByRole("button", { name: "提交研究结论" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "取消并保留原因" })).toBeEnabled();
  expect(screen.getByText("研究结论需至少关联一条原始证据快照；无可用证据时，可取消研究并保留原因。")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "提交研究结论" }));
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0);
});
it("submits a no-findings conclusion with the selected original snapshot and then reads the stored result", async () => {
  const initialFetch = fetcher.getMockImplementation()!;
  fetcher.mockImplementation(async (input, init) => {
    if (String(input).endsWith("/research/research/conclude")) {
      const body = JSON.parse(String(init?.body));
      researchOverrides = { state: "completed", version: 2, conclusion: body.conclusion, findings: body.findings, sources: body.source_refs };
      return Response.json({ ok: true });
    }
    return initialFetch(input, init);
  });
  await activeResearch();
  fireEvent.click(screen.getByText("关联证据快照（已选 0）"));
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "提交研究结论" }));
  await screen.findByText("本期未发现可确认的差异");
  const writes = fetcher.mock.calls.filter(([input, init]) => String(input).endsWith("/research/research/conclude") && init?.method === "POST");
  expect(writes).toHaveLength(1);
  expect(JSON.parse(String(writes[0][1]?.body))).toMatchObject({ research_task_id: "research", findings: [], source_refs: [ref], expected_version: 1, payload_digest: workspace.research[0].payload_digest });
  expect(screen.getByText("关联证据 1 项")).toBeInTheDocument();
  expect(screen.queryByText("历史结论未关联原始快照，待补证核对。")).not.toBeInTheDocument();
});
it("preserves the actual reason when research stops without evidence instead of completing it", async () => {
  const initialFetch = fetcher.getMockImplementation()!;
  fetcher.mockImplementation(async (input, init) => {
    if (String(input).endsWith("/research/research/cancel")) {
      const body = JSON.parse(String(init?.body));
      researchOverrides = { state: "cancelled", version: 2, conclusion: null, findings: [], sources: [], cancellation_reason: body.reason };
      return Response.json({ ok: true });
    }
    return initialFetch(input, init);
  });
  await activeResearch();
  fireEvent.change(screen.getByLabelText("结论 / 取消原因"), { target: { value: "达到时间边界，尚未取得可引用证据" } });
  fireEvent.click(screen.getByRole("button", { name: "取消并保留原因" }));
  await screen.findByText("取消原因：达到时间边界，尚未取得可引用证据");
  const writes = fetcher.mock.calls.filter(([, init]) => init?.method === "POST");
  expect(writes).toHaveLength(1);
  expect(String(writes[0][0])).toContain("/research/research/cancel");
  expect(JSON.parse(String(writes[0][1]?.body))).toMatchObject({ reason: "达到时间边界，尚未取得可引用证据", expected_version: 1 });
  expect(screen.queryByRole("button", { name: "提交研究结论" })).not.toBeInTheDocument();
});
it("keeps legacy zero-reference conclusions readable with an explicit evidence gap", async () => {
  researchOverrides = { sources: [], findings: [] };
  render(<ProductWorkspace/>);
  await screen.findByText("私有研究结论");
  expect(screen.getByText("历史结论未关联原始快照，待补证核对。")).toBeInTheDocument();
  expect(screen.getByText("关联证据 0 项")).toBeInTheDocument();
});
