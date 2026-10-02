import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MarketSegments, SegmentForm, type Fact, type Segment, type SizingResult } from "./market-segments";
import type { ProductCatalog, Workspace } from "./product-work-api";
const ref = { tenant_id: "tenant", kind: "evidence_snapshot", ref_id: "original", digest: "a".repeat(64), as_of: "2026-09-29T12:00:00Z" };
const fact: Fact = { text: "完整原市场依据", fact_kind: "hypothesis", sources: [ref], approval: null, derivation_version: null };
const parameter = { lower: null, upper: null, basis: fact };
const sizing: SizingResult = { horizon_year: 2027, currency: "CNY", boundary: "合成范围", population_unit: "家", policy_version: "market-bottom-up-v1", estimates: {}, unknown_parameters: ["unit_price"], hypothesis_parameters: [], interpretation: "非实际销量" };
const segment: Segment = { id: "segment", title: "完整原市场", product_line_id: null, supersedes_id: null, version: 1, created_at: ref.as_of, is_latest: true, source_warnings: [], revision_reason: "保留原市场", target_users: [fact], customer_problems: [fact], use_environments: [fact], buying_criteria: [fact], unmet_needs: [fact], job_to_be_done: fact, outcome: { statement: "减少处理时间", metric_key: "seconds", unit: "s", baseline_value: null, target_value: "90", measurement_method: "同工况计时", window: "一周", sources: [ref] }, sizing_inputs: { horizon_year: 2027, currency: "CNY", population_unit: "家", boundary: "合成范围", potential_customers: parameter, annual_units_per_customer: parameter, unit_price: parameter, serviceable_share: parameter, obtainable_share: parameter }, sizing_result: sizing };
const props = { base: "spaces/space", workspace: { can_contribute: true } as Workspace, catalog: { nodes: [], line_access: {} } as unknown as ProductCatalog, evidence: [] };
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
function submit() { fireEvent.submit(screen.getByLabelText("细分名称").closest("form")!); }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it.each(["network", 503, 408, 429] as const)("keeps an immutable original save after uncertain %s and unlocks before notifying success", async failure => {
  const finish = deferred<Response>(); const fetcher = vi.fn<typeof fetch>();
  if (failure === "network") fetcher.mockRejectedValueOnce(new TypeError("保存回执丢失")); else fetcher.mockResolvedValueOnce(Response.json({ detail: { message: "保存回执丢失" } }, { status: failure }));
  fetcher.mockReturnValueOnce(finish.promise); vi.stubGlobal("fetch", fetcher);
  const events: string[] = [], onSaved = vi.fn(() => events.push("saved")), onCancel = vi.fn();
  const initial = JSON.parse(JSON.stringify(segment)) as Segment;
  render(<SegmentForm {...props} initial={initial} onSaved={onSaved} onCancel={onCancel} onPendingChange={pending => events.push(pending ? "locked" : "released")}/>);
  fireEvent.change(screen.getByLabelText("记录 / 修订原因"), { target: { value: "人工核对后保存" } });
  act(() => { submit(); submit(); fireEvent.click(screen.getByRole("button", { name: "取消" })); }); await screen.findByText("保存回执丢失"); expect(fetcher).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("细分名称")).toBeDisabled(); expect(screen.getByLabelText("用户要完成的任务（JTBD）")).toBeDisabled(); expect(screen.getByRole("button", { name: "取消" })).toBeDisabled(); expect(screen.getByRole("button", { name: "保存完整版本" })).toBeDisabled(); expect(screen.getByRole("button", { name: "预览当前参数计算结果" })).toBeDisabled();
  const original = String(fetcher.mock.calls[0][1]?.body); expect(JSON.parse(original)).toMatchObject({ title: segment.title, supersedes_id: segment.id, revision_reason: "人工核对后保存", job_to_be_done: segment.job_to_be_done }); expect(JSON.parse(original).request_id).toBeTruthy();
  initial.job_to_be_done.sources[0].digest = "b".repeat(64);
  const retry = screen.getByRole("button", { name: "按原请求重试保存" }); act(() => { fireEvent.click(retry); fireEvent.click(retry); submit(); }); expect(fetcher).toHaveBeenCalledTimes(2); expect(fetcher.mock.calls[1][1]?.body).toBe(original);
  await act(async () => finish.resolve(Response.json(segment))); await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1)); expect(events).toEqual(["locked", "released", "saved"]); expect(onCancel).not.toHaveBeenCalled(); expect(screen.queryByRole("button", { name: "按原请求重试保存" })).not.toBeInTheDocument(); expect(screen.getByLabelText("细分名称")).toBeEnabled();
});
it("releases a definite server rejection and permits a corrected request with a fresh identity", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ detail: { message: "明确校验拒绝" } }, { status: 409 })).mockResolvedValueOnce(Response.json(segment)); vi.stubGlobal("fetch", fetcher); const onPendingChange = vi.fn(), onSaved = vi.fn();
  render(<SegmentForm {...props} initial={segment} onSaved={onSaved} onCancel={vi.fn()} onPendingChange={onPendingChange}/>); submit(); await screen.findByText("明确校验拒绝"); expect(onPendingChange.mock.calls.map(([pending]) => pending)).toEqual([true, false]); expect(screen.getByLabelText("细分名称")).toBeEnabled(); expect(screen.queryByRole("button", { name: "按原请求重试保存" })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("细分名称"), { target: { value: "明确修正市场" } }); submit(); await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1)); const before = JSON.parse(String(fetcher.mock.calls[0][1]?.body)), after = JSON.parse(String(fetcher.mock.calls[1][1]?.body)); expect(after.title).toBe("明确修正市场"); expect(after.request_id).not.toBe(before.request_id);
});
it("locks the real market page while uncertain and releases it through the existing denial channel", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [segment] })).mockResolvedValueOnce(Response.json({ detail: { message: "保存暂未确认" } }, { status: 503 })).mockResolvedValueOnce(Response.json({ detail: { message: "当前市场无权保存" } }, { status: 403 })); vi.stubGlobal("fetch", fetcher); const onAuthorityLost = vi.fn(), onPendingChange = vi.fn();
  render(<MarketSegments {...props} onAuthorityLost={onAuthorityLost} onPendingChange={onPendingChange}/>); await screen.findByText("完整原市场 · v1"); fireEvent.click(screen.getByRole("button", { name: "追加修订" })); submit(); await screen.findByText("保存暂未确认");
  expect(screen.getByRole("button", { name: "刷新细分" })).toBeDisabled(); expect(screen.getAllByLabelText("工作归属")[0]).toBeDisabled(); expect(screen.getByLabelText("显示历史版本")).toBeDisabled(); expect(screen.queryByRole("button", { name: "新建细分" })).not.toBeInTheDocument();
  fireEvent.change(screen.getAllByLabelText("工作归属")[0], { target: { value: "" } }); expect(screen.getByLabelText("细分名称")).toHaveValue(segment.title); expect(fetcher).toHaveBeenCalledTimes(2);
  fireEvent.click(screen.getByRole("button", { name: "按原请求重试保存" })); await screen.findByText("当前市场无权保存"); expect(onAuthorityLost).toHaveBeenCalledExactlyOnceWith("当前市场无权保存"); expect(onPendingChange.mock.calls.map(([pending]) => pending)).toEqual([true, false]); expect(screen.queryByLabelText("细分名称")).not.toBeInTheDocument(); expect(screen.queryByText("完整原市场 · v1")).not.toBeInTheDocument(); expect(screen.getByRole("button", { name: "刷新细分" })).toBeEnabled();
});
it("keeps failed calculation read-only and AI review local without taking a write lock", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ detail: { message: "只读计算不可用" } }, { status: 503 })); vi.stubGlobal("fetch", fetcher); const onPendingChange = vi.fn(), onReview = vi.fn();
  render(<SegmentForm {...props} candidate={segment} onReview={onReview} initial={null} onSaved={vi.fn()} onCancel={vi.fn()} onPendingChange={onPendingChange}/>); fireEvent.click(screen.getByRole("button", { name: "预览当前参数计算结果" })); await screen.findByText("只读计算不可用"); expect(onPendingChange).not.toHaveBeenCalled(); expect(screen.queryByRole("button", { name: "按原请求重试保存" })).not.toBeInTheDocument(); expect(screen.getByLabelText("细分名称")).toBeEnabled();
  submit(); expect(onReview).toHaveBeenCalledTimes(1); expect(fetcher).toHaveBeenCalledTimes(1); expect(fetcher.mock.calls[0][0]).toBe("/api/product-work/spaces/space/market-sizing"); expect(onPendingChange).not.toHaveBeenCalled();
});
it("releases the external lock on unmount and ignores a late save receipt", async () => {
  const finish = deferred<Response>(); vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockReturnValueOnce(finish.promise)); const onSaved = vi.fn(), onPendingChange = vi.fn();
  const view = render(<SegmentForm {...props} initial={segment} onSaved={onSaved} onCancel={vi.fn()} onPendingChange={onPendingChange}/>); submit(); expect(onPendingChange).toHaveBeenLastCalledWith(true); view.unmount(); expect(onPendingChange).toHaveBeenLastCalledWith(false);
  await act(async () => finish.resolve(Response.json(segment))); expect(onSaved).not.toHaveBeenCalled(); expect(onPendingChange.mock.calls.map(([pending]) => pending)).toEqual([true, false]);
});
