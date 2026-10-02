import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ProductMasterReferences, type MasterReference, type MasterReferenceList } from "./product-master-references";
import type { Evidence } from "./product-work-api";

const reference = { tenant_id: "tenant", kind: "evidence_snapshot", ref_id: "snapshot", digest: "a".repeat(64), as_of: "2026-09-30T10:00:00Z" };
const evidence: Evidence[] = [{ id: reference.ref_id, name: "主数据交接原依据", url: "https://example.test/private", captured_at: reference.as_of, taint: "untrusted", is_stale: false, superseded: false, has_conflict: false, reference }];
const definition = { id: "definition", version: 2, revision: 2, digest: "d".repeat(64), release_id: "release" };
const item: MasterReference = { id: "entry", action: "register", previous_id: null, system_kind: "erp", source_system: "erp_main", master_kind: "material", external_id: "MAT-001", external_revision: "A", external_as_of: reference.as_of, sources: [reference], reason: "原登记依据", created_by_user_id: "registrar", created_at: reference.as_of, definition_ref: definition, product_snapshot: { id: "product" }, context_status: "current", version: 1 };
const data: MasterReferenceList = { product: { id: "product", version: 1, code: "P1", name: "产品一", level: "model", lifecycle: "active" }, current_definition: definition, context_digest: "c".repeat(64), items: [item] };
const props = { base: "spaces/space", productId: "product", canManage: true, evidence };
// Automatic citation metadata reads have a separate exact-path response.
// The original mock tracks business reads/writes and their immutable payloads.
function stubBusinessFetch(fetcher: typeof fetch) {
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "https://app.test");
    if (["/api/product-work/spaces/space/evidence", "/api/product-work/spaces/other/evidence"].includes(url.pathname)) {
      expect(init?.method).toBe("GET");
      expect(url.searchParams.getAll("snapshot_ids")).toEqual([reference.ref_id]);
      expect([...url.searchParams.keys()]).toEqual(["snapshot_ids"]);
      return Promise.resolve(Response.json({ items: evidence }));
    }
    return fetcher(input, init);
  });
}
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
function start() { fireEvent.click(screen.getByRole("button", { name: "新登记交接引用" })); fireEvent.change(screen.getByLabelText("系统标识"), { target: { value: "erp_secondary" } }); fireEvent.change(screen.getByLabelText("外部对象标识"), { target: { value: "MAT-NEW" } }); fireEvent.change(screen.getByLabelText("外部修订"), { target: { value: "B" } }); fireEvent.change(screen.getByLabelText("外部来源时点"), { target: { value: "2026-09-30T10:00" } }); fireEvent.change(screen.getByLabelText("登记原因"), { target: { value: "人工核对登记" } }); fireEvent.click(screen.getByLabelText(/主数据交接原依据/)); }
function submit() { fireEvent.submit(screen.getByLabelText("登记原因").closest("form")!); }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it.each(["network", 503, 408, 429] as const)("retries the immutable original registration after uncertain %s without releasing navigation", async status => {
  const finish = deferred<Response>(), fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(data));
  if (status === "network") fetcher.mockRejectedValueOnce(new TypeError("交接回执丢失")); else fetcher.mockResolvedValueOnce(Response.json({ detail: { message: "交接回执丢失" } }, { status }));
  fetcher.mockReturnValueOnce(finish.promise); stubBusinessFetch(fetcher);
  const onPendingChange = vi.fn(); const rendered = render(<ProductMasterReferences {...props} onPendingChange={onPendingChange}/>);
  await screen.findByText("对象：产品一 · P1 · model"); start(); act(() => { submit(); submit(); fireEvent.click(screen.getByRole("button", { name: "取消登记" })); });
  await screen.findByText("交接回执丢失"); expect(fetcher).toHaveBeenCalledTimes(2); expect(onPendingChange.mock.calls.map(([value]) => value)).toEqual([true]); expect(screen.getByLabelText("系统标识")).toBeDisabled(); expect(screen.getByRole("button", { name: "取消登记" })).toBeDisabled(); expect(screen.getByRole("button", { name: "刷新交接引用" })).toBeDisabled();
  const original = String(fetcher.mock.calls[1][1]?.body); expect(JSON.parse(original)).toMatchObject({ action: "register", previous_id: null, external_id: "MAT-NEW", sources: [reference], expected_context_digest: data.context_digest }); expect(JSON.parse(original).request_id).toBeTruthy();
  const replacementEvidence = [{ ...evidence[0], reference: { ...reference, digest: "b".repeat(64) } }]; rendered.rerender(<ProductMasterReferences {...props} evidence={replacementEvidence} disabled onPendingChange={onPendingChange}/>);
  act(() => { fireEvent.click(screen.getByRole("button", { name: "按原请求重试交接登记" })); fireEvent.click(screen.getByRole("button", { name: "按原请求重试交接登记" })); }); expect(fetcher).toHaveBeenCalledTimes(3); expect(fetcher.mock.calls[2][1]?.body).toBe(original);
  await act(async () => finish.resolve(Response.json({ ...data, items: [...data.items, { ...item, id: "new-entry", external_id: "MAT-NEW" }] })));
  await waitFor(() => expect(onPendingChange.mock.calls.map(([value]) => value)).toEqual([true, false])); expect(screen.queryByLabelText("登记原因")).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: "按原请求重试交接登记" })).not.toBeInTheDocument(); expect(screen.getByText("新登记 · erp_main / 物料 / MAT-NEW")).toBeInTheDocument();
});

it.each([401, 403])("wipes form, historical locators and source metadata after write denial %s", async status => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ ...data, items: [item, { ...item, id: "old", context_status: "stale" }] })).mockResolvedValueOnce(Response.json({ detail: { message: "无交接管理权限" } }, { status })); stubBusinessFetch(fetcher);
  const onAuthorityLost = vi.fn(), onPendingChange = vi.fn(); render(<ProductMasterReferences {...props} onAuthorityLost={onAuthorityLost} onPendingChange={onPendingChange}/>); await screen.findByText("对象：产品一 · P1 · model"); start(); submit(); await screen.findByText("无交接管理权限");
  expect(screen.queryByLabelText("系统标识")).not.toBeInTheDocument(); expect(screen.queryByText(/MAT-001/)).not.toBeInTheDocument(); expect(screen.queryByText(/主数据交接原依据/)).not.toBeInTheDocument(); expect(screen.queryByText(/registrar/)).not.toBeInTheDocument(); expect(screen.queryByRole("link", { name: "打开来源网页" })).not.toBeInTheDocument(); expect(onAuthorityLost).toHaveBeenCalledExactlyOnceWith("无交接管理权限"); expect(onPendingChange.mock.calls.map(([value]) => value)).toEqual([true, false]);
});

it("does not let a late list success restore history after the actual source reader denies access", async () => {
  const late = deferred<Response>(), fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(data)).mockReturnValueOnce(late.promise).mockResolvedValueOnce(Response.json({ detail: { message: "原依据已撤权" } }, { status: 403 })); stubBusinessFetch(fetcher); const onAuthorityLost = vi.fn(); render(<ProductMasterReferences {...props} onAuthorityLost={onAuthorityLost}/>);
  await screen.findByText("对象：产品一 · P1 · model"); fireEvent.click(screen.getByRole("button", { name: "刷新交接引用" })); fireEvent.click(screen.getByRole("button", { name: "查看此引用的原快照" })); await screen.findByText("原依据已撤权");
  await act(async () => late.resolve(Response.json(data))); expect(screen.queryByText(/MAT-001/)).not.toBeInTheDocument(); expect(screen.queryByText(/主数据交接原依据/)).not.toBeInTheDocument(); expect(onAuthorityLost).toHaveBeenCalledOnce(); expect(screen.getByRole("button", { name: "重新核对交接引用权限" })).toBeEnabled();
});

it("fences old product reads and writes and releases pending on a direct scope change", async () => {
  const lateRead = deferred<Response>(), lateWrite = deferred<Response>(); const fetcher = vi.fn<typeof fetch>().mockReturnValueOnce(lateRead.promise).mockResolvedValueOnce(Response.json({ ...data, product: { ...data.product, name: "产品二" } })).mockReturnValueOnce(lateWrite.promise).mockResolvedValueOnce(Response.json({ ...data, product: { ...data.product, name: "产品三" } })); stubBusinessFetch(fetcher); const onPendingChange = vi.fn();
  const rendered = render(<ProductMasterReferences {...props} onPendingChange={onPendingChange}/>); rendered.rerender(<ProductMasterReferences {...props} productId="product2" onPendingChange={onPendingChange}/>); await screen.findByText("对象：产品二 · P1 · model"); await act(async () => lateRead.resolve(Response.json(data))); expect(screen.queryByText("对象：产品一 · P1 · model")).not.toBeInTheDocument();
  start(); submit(); rendered.rerender(<ProductMasterReferences {...props} base="spaces/other" productId="product3" onPendingChange={onPendingChange}/>); await screen.findByText("对象：产品三 · P1 · model"); expect(onPendingChange.mock.calls.map(([value]) => value)).toEqual([true, false]); await act(async () => lateWrite.resolve(Response.json(data))); expect(screen.queryByText("对象：产品一 · P1 · model")).not.toBeInTheDocument(); expect(screen.queryByLabelText("登记原因")).not.toBeInTheDocument(); expect(onPendingChange).toHaveBeenCalledTimes(2);
});

it("does not restore a denied source through a late write receipt in the same product scope", async () => {
  const late = deferred<Response>(), fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(data)).mockReturnValueOnce(late.promise).mockResolvedValueOnce(Response.json({ detail: { message: "写入途中原依据撤权" } }, { status: 403 })); stubBusinessFetch(fetcher); const onAuthorityLost = vi.fn(), onPendingChange = vi.fn(); render(<ProductMasterReferences {...props} onAuthorityLost={onAuthorityLost} onPendingChange={onPendingChange}/>);
  await screen.findByText("对象：产品一 · P1 · model"); start(); submit(); fireEvent.click(screen.getByRole("button", { name: "查看此引用的原快照" })); await screen.findByText("写入途中原依据撤权"); await act(async () => late.resolve(Response.json(data)));
  expect(screen.queryByText(/MAT-001/)).not.toBeInTheDocument(); expect(screen.queryByLabelText("登记原因")).not.toBeInTheDocument(); expect(screen.queryByText(/主数据交接原依据/)).not.toBeInTheDocument(); expect(onAuthorityLost).toHaveBeenCalledExactlyOnceWith("写入途中原依据撤权"); expect(onPendingChange.mock.calls.map(([value]) => value)).toEqual([true, false]);
});

it("keeps changed-definition history and permits withdrawal without a current published definition", async () => {
  const old = { ...item, context_status: "no_current_release" as const }, withdrawn = { ...old, id: "withdrawn", action: "withdraw" as const, previous_id: item.id, reason: "停止沿用旧定位" }; const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ ...data, current_definition: null, items: [old] })).mockResolvedValueOnce(Response.json({ ...data, current_definition: null, items: [old, withdrawn] })); stubBusinessFetch(fetcher); render(<ProductMasterReferences {...props}/>);
  await screen.findByText("当前已无已发布定义，原引用保留待复查。"); expect(screen.getByRole("button", { name: "新登记交接引用" })).toBeDisabled(); expect(screen.getByRole("button", { name: "纠正此引用" })).toBeDisabled(); fireEvent.click(screen.getByRole("button", { name: "撤回此引用" })); expect(screen.queryByLabelText("外部对象标识")).not.toBeInTheDocument(); fireEvent.change(screen.getByLabelText("登记原因"), { target: { value: withdrawn.reason } }); submit(); await screen.findByText("撤回 · erp_main / 物料 / MAT-001"); const body = JSON.parse(String(fetcher.mock.calls[1][1]?.body)); expect(body).toMatchObject({ action: "withdraw", previous_id: item.id, system_kind: item.system_kind, source_system: item.source_system, master_kind: item.master_kind, external_id: item.external_id, external_revision: item.external_revision, external_as_of: item.external_as_of, sources: item.sources }); expect(screen.getByText("新登记 · erp_main / 物料 / MAT-001")).toBeInTheDocument(); expect(screen.queryByRole("button", { name: "撤回此引用" })).not.toBeInTheDocument();
});

it("unlocks a definite context conflict for explicit refresh and keeps read-only users out of writes", async () => {
  const changed = { ...data, current_definition: { ...definition, version: 3, revision: 3 }, context_digest: "e".repeat(64), items: [{ ...item, context_status: "stale" as const }] }; const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(data)).mockResolvedValueOnce(Response.json({ detail: { message: "已发布定义已变化，请刷新后核对" } }, { status: 409 })).mockResolvedValueOnce(Response.json(changed)); stubBusinessFetch(fetcher); const onPendingChange = vi.fn(); const rendered = render(<ProductMasterReferences {...props} onPendingChange={onPendingChange}/>);
  await screen.findByText("对象：产品一 · P1 · model"); start(); submit(); await screen.findByText("已发布定义已变化，请刷新后核对"); expect(onPendingChange.mock.calls.map(([value]) => value)).toEqual([true, false]); expect(screen.queryByRole("button", { name: "按原请求重试交接登记" })).not.toBeInTheDocument(); fireEvent.click(screen.getByRole("button", { name: "刷新交接引用" })); await screen.findByText("当前已发布定义：3 · v3"); expect(screen.getByText("当前定义或对象已变化，原引用保留，需要复查。")).toBeInTheDocument(); expect(screen.getByText(/固定已发布定义：2/)).toBeInTheDocument();
  rendered.rerender(<ProductMasterReferences {...props} canManage={false}/>); expect(screen.getByRole("button", { name: "新登记交接引用" })).toBeDisabled(); expect(screen.queryByRole("button", { name: "纠正此引用" })).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: "撤回此引用" })).not.toBeInTheDocument(); expect(fetcher).toHaveBeenCalledTimes(3);
});
