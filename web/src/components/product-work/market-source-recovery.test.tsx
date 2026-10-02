import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MarketSegments, SegmentForm, type Fact, type Segment, type SizingResult } from "./market-segments";
import type { Evidence, ProductCatalog, SourceRef, Workspace } from "./product-work-api";
const ref: SourceRef = { tenant_id: "tenant", kind: "evidence_snapshot", ref_id: "snapshot", digest: "a".repeat(64), as_of: "2026-09-29T12:00:00Z" };
const fact: Fact = { text: "合成市场依据", fact_kind: "hypothesis", sources: [], approval: null, derivation_version: null };
const parameter = { lower: null, upper: null, basis: fact };
const sizing: SizingResult = { horizon_year: 2027, currency: "CNY", boundary: "合成范围", population_unit: "家", policy_version: "market-bottom-up-v1", estimates: { tam: { annual_units: null, annual_revenue: null, units_formula: "potential_customers × annual_units_per_customer", revenue_formula: "potential_customers × annual_units_per_customer × unit_price" } }, unknown_parameters: ["potential_customers"], hypothesis_parameters: [], interpretation: "合成计算，非实际销量" };
const segment: Segment = { id: "segment", title: "原空间细分", product_line_id: null, supersedes_id: null, version: 1, created_at: "2026-09-29T12:00:00Z", is_latest: true, source_warnings: [], revision_reason: "首次合成观察", target_users: [fact], customer_problems: [fact], use_environments: [fact], buying_criteria: [fact], unmet_needs: [fact], job_to_be_done: { ...fact, sources: [ref] }, outcome: { statement: "合成目标", metric_key: "seconds", unit: "s", baseline_value: null, target_value: null, measurement_method: "合成计时", window: "合成周期", sources: [] }, sizing_inputs: { horizon_year: 2027, currency: "CNY", population_unit: "家", boundary: "合成范围", potential_customers: parameter, annual_units_per_customer: parameter, unit_price: parameter, serviceable_share: parameter, obtainable_share: parameter }, sizing_result: sizing };
const evidence: Evidence = { id: ref.ref_id, name: "受限市场资料", url: "https://private.example.com/report", captured_at: ref.as_of, taint: "untrusted_external", is_stale: false, superseded: false, has_conflict: false, reference: ref };
const props = { base: "spaces/old", workspace: { can_contribute: true } as Workspace, catalog: { nodes: [], line_access: {} } as unknown as ProductCatalog, evidence: [evidence] };
const body = (content = "原范围客户正文") => ({ snapshot_id: ref.ref_id, content_digest: ref.digest, content });
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
async function openDetails() { await screen.findByText("原空间细分 · v1"); fireEvent.click(screen.getByText("查看用户、目标和计算依据")); }
async function read() { await openDetails(); fireEvent.click(screen.getByRole("button", { name: "查看正文" })); }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it.each(["space", "scope"])("clears visible original text and ignores a late read after changing %s", async kind => {
  const pending = deferred<Response>(); const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [segment] })).mockResolvedValueOnce(Response.json(body())).mockReturnValueOnce(pending.promise).mockResolvedValueOnce(Response.json({ items: [{ ...segment, title: "新空间细分" }] }));
  vi.stubGlobal("fetch", fetcher); const view = render(<MarketSegments {...props}/>); await read(); await screen.findByText("原范围客户正文");
  fireEvent.click(screen.getByRole("button", { name: "查看正文" })); await screen.findByRole("button", { name: "取消读取正文" });
  if (kind === "space") view.rerender(<MarketSegments {...props} base="spaces/new"/>);
  else fireEvent.change(screen.getByLabelText("工作归属"), { target: { value: "" } });
  expect(screen.queryByText("原范围客户正文")).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: "取消读取正文" })).not.toBeInTheDocument();
  await act(async () => pending.resolve(Response.json(body("旧范围迟到正文")))); expect(screen.queryByText("旧范围迟到正文")).not.toBeInTheDocument();
  if (kind === "space") expect(await screen.findByText("新空间细分 · v1")).toBeInTheDocument();
});
it.each(["id", "digest"])("rejects a source body with a mismatched %s", async mismatch => {
  vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [segment] })).mockResolvedValueOnce(Response.json({ ...body("不匹配的正文"), ...(mismatch === "id" ? { snapshot_id: "other" } : { content_digest: "b".repeat(64) }) })));
  render(<MarketSegments {...props}/>); await read(); expect(await screen.findByRole("alert")).toHaveTextContent("固定引用版本不一致"); expect(screen.queryByText("不匹配的正文")).not.toBeInTheDocument();
});
it("cancels the first read without allowing it to replace a later successful read", async () => {
  const pending = deferred<Response>(); const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [segment] })).mockReturnValueOnce(pending.promise).mockResolvedValueOnce(Response.json(body("新读取原文")));
  vi.stubGlobal("fetch", fetcher); render(<MarketSegments {...props}/>); await read(); fireEvent.click(screen.getByRole("button", { name: "取消读取正文" })); fireEvent.click(screen.getByRole("button", { name: "查看正文" })); await screen.findByText("新读取原文");
  await act(async () => pending.resolve(Response.json(body("取消的旧原文")))); expect(screen.queryByText("取消的旧原文")).not.toBeInTheDocument(); expect(screen.getByText("新读取原文")).toBeInTheDocument();
});
it.each([{ path: "list", status: 401 }, { path: "list", status: 403 }, { path: "body", status: 401 }, { path: "body", status: 403 }])("wipes cards, editing and source metadata after $path denial $status", async ({ path, status }) => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [segment] })).mockResolvedValueOnce(Response.json({ detail: { message: "市场资料访问已撤回" } }, { status }));
  vi.stubGlobal("fetch", fetcher); const onAuthorityLost = vi.fn(); const view = render(<MarketSegments {...props} onAuthorityLost={onAuthorityLost}/>); await openDetails(); fireEvent.click(screen.getByRole("button", { name: "追加修订" })); expect(screen.getByLabelText("细分名称")).toHaveValue(segment.title);
  if (path === "list") fireEvent.click(screen.getByRole("button", { name: "刷新细分" })); else fireEvent.click(screen.getByRole("button", { name: "查看正文" }));
  await screen.findByText("市场资料访问已撤回"); expect(onAuthorityLost).toHaveBeenCalledWith("市场资料访问已撤回"); expect(screen.queryByText("原空间细分 · v1")).not.toBeInTheDocument(); expect(screen.queryByLabelText("细分名称")).not.toBeInTheDocument(); expect(screen.queryByText(/受限市场资料/)).not.toBeInTheDocument(); expect(screen.queryByText(/private.example.com/)).not.toBeInTheDocument();
  view.rerender(<MarketSegments {...props} evidence={[{ ...evidence }]} onAuthorityLost={onAuthorityLost}/>); expect(screen.queryByText("原空间细分 · v1")).not.toBeInTheDocument(); expect(screen.queryByText(/受限市场资料/)).not.toBeInTheDocument();
});
it("does not restore cards from an older initial list after refresh has denied access", async () => {
  const pending = deferred<Response>(); const fetcher = vi.fn<typeof fetch>().mockReturnValueOnce(pending.promise).mockResolvedValueOnce(Response.json({ detail: { message: "当前无权查看市场" } }, { status: 403 }));
  vi.stubGlobal("fetch", fetcher); const onAuthorityLost = vi.fn(); render(<MarketSegments {...props} onAuthorityLost={onAuthorityLost}/>); fireEvent.click(screen.getByRole("button", { name: "刷新细分" })); await screen.findByText("当前无权查看市场");
  await act(async () => pending.resolve(Response.json({ items: [segment] }))); expect(screen.queryByText("原空间细分 · v1")).not.toBeInTheDocument(); expect(onAuthorityLost).toHaveBeenCalledTimes(1);
});
it.each(["save", "calculate"])("does not apply an unmounted form's %s response to a new space", async kind => {
  const pending = deferred<Response>(); const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [segment] })).mockReturnValueOnce(pending.promise).mockResolvedValueOnce(Response.json({ items: [{ ...segment, title: "新页面市场" }] }));
  vi.stubGlobal("fetch", fetcher); const view = render(<MarketSegments {...props}/>); await screen.findByText("原空间细分 · v1"); fireEvent.click(screen.getByRole("button", { name: "追加修订" }));
  if (kind === "save") fireEvent.submit(screen.getByLabelText("细分名称").closest("form")!); else fireEvent.click(screen.getByRole("button", { name: "预览当前参数计算结果" }));
  view.rerender(<MarketSegments {...props} base="spaces/new"/>); await screen.findByText("新页面市场 · v1"); fireEvent.click(screen.getByRole("button", { name: "追加修订" }));
  await act(async () => pending.resolve(Response.json(kind === "save" ? segment : { ...sizing, interpretation: "旧空间计算回执" })));
  expect(screen.getByLabelText("细分名称")).toHaveValue("新页面市场"); expect(screen.queryByText("旧空间计算回执")).not.toBeInTheDocument(); expect(screen.queryByText("尚未保存 · 此处只计算输入参数")).not.toBeInTheDocument(); expect(fetcher).toHaveBeenCalledTimes(3);
});
it("sends one save for synchronous repeated submission of the real segment form", async () => {
  const pending = deferred<Response>(); const fetcher = vi.fn<typeof fetch>().mockReturnValueOnce(pending.promise); vi.stubGlobal("fetch", fetcher); const onSaved = vi.fn();
  render(<SegmentForm initial={segment} {...props} onSaved={onSaved} onCancel={vi.fn()}/>); const form = screen.getByLabelText("细分名称").closest("form")!; act(() => { fireEvent.submit(form); fireEvent.submit(form); }); expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[0][0]).toBe("/api/product-work/spaces/old/market-segments"); expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toMatchObject({ supersedes_id: segment.id, title: segment.title, job_to_be_done: segment.job_to_be_done });
  await act(async () => pending.resolve(Response.json(segment))); await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
});
