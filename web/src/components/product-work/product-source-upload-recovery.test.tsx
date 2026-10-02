import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ProductSourceFiles } from "./product-source-files";
vi.mock("./product-ai-runs", () => ({ ProductAiRuns: () => null }));
const original = { id: "original", filename: "RFQ.xlsx", classification: "internal", status: "uploaded", error_code: null, revoked_at: null, size_bytes: 4, fragment_count: 0 };
const bytes = new Uint8Array([1, 2, 3, 4]).buffer;
const list = () => Response.json({ items: [original], truncated: false });
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
function file(read: Promise<ArrayBuffer> = Promise.resolve(bytes)) { const value = new File(["data"], "RFQ.xlsx"); Object.defineProperty(value, "arrayBuffer", { value: vi.fn(() => read) }); return value; }
function choose(value = file()) { fireEvent.change(screen.getByLabelText("选择RFQ或客户原件"), { target: { files: [value] } }); }
const mutations = (fetcher: ReturnType<typeof vi.fn<typeof fetch>>) => fetcher.mock.calls.filter(([, init]) => init?.method !== "GET");
beforeEach(() => { vi.stubGlobal("crypto", { subtle: { digest: vi.fn().mockResolvedValue(new Uint8Array(32).buffer) }, randomUUID: vi.fn().mockReturnValue("immutable-request") }); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it.each(["register", "upload", "parse"])("retries the exact original %s stage without repeating confirmed steps", async stage => {
  let failed = false;
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url, init) => {
    if (init?.method === "GET") return list();
    const path = String(url); const current = path.endsWith("/upload") ? "upload" : path.endsWith("/parse") ? "parse" : "register";
    if (current === stage && !failed) { failed = true; throw new TypeError("回执丢失"); }
    return Response.json(current === "register" ? original : {});
  });
  vi.stubGlobal("fetch", fetcher); const onPendingChange = vi.fn();
  render(<ProductSourceFiles base="spaces/space" lineId="line" onPendingChange={onPendingChange}/>);
  await screen.findByText(/RFQ.xlsx/); choose(); await screen.findByText("回执丢失");
  expect(screen.getByLabelText("资料级别")).toBeDisabled(); expect(screen.getByRole("button", { name: "上传RFQ或客户原件" })).toBeDisabled();
  choose(file()); expect(mutations(fetcher)).toHaveLength(stage === "register" ? 1 : stage === "upload" ? 2 : 3);
  fireEvent.click(screen.getByRole("button", { name: "重试原件处理" })); await screen.findByText("原件已处理，请核对解析状态和出处。");
  const writes = mutations(fetcher); const register = writes.filter(([url]) => String(url).endsWith("/source-files")); const uploads = writes.filter(([url]) => String(url).endsWith("/upload")); const parses = writes.filter(([url]) => String(url).endsWith("/parse"));
  expect(register).toHaveLength(stage === "register" ? 2 : 1); expect(uploads).toHaveLength(stage === "upload" ? 2 : 1); expect(parses).toHaveLength(stage === "parse" ? 2 : 1);
  expect(JSON.parse(String(register[0][1]?.body))).toMatchObject({ request_id: "immutable-request", product_line_id: "line", classification: "internal", filename: "RFQ.xlsx" });
  if (register.length === 2) expect(register[1][1]?.body).toBe(register[0][1]?.body);
  uploads.forEach(([, init]) => expect(init?.body).toBe(bytes));
  expect(screen.queryByRole("button", { name: "重试原件处理" })).not.toBeInTheDocument(); await waitFor(() => expect(onPendingChange).toHaveBeenLastCalledWith(false));
});
it.each([401, 403])("clears originals after a non-JSON upload denial %s and never parses", async status => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(list()).mockResolvedValueOnce(Response.json(original)).mockResolvedValueOnce(new Response(status === 401 ? "" : "<html>Forbidden</html>", { status }));
  vi.stubGlobal("fetch", fetcher); const onPendingChange = vi.fn(); render(<ProductSourceFiles base="spaces/space" lineId={null} onPendingChange={onPendingChange}/>);
  await screen.findByText(/RFQ.xlsx/); choose(); await screen.findByRole("button", { name: "重新核对文件权限" });
  expect(screen.queryByText(/RFQ.xlsx/)).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: "重试原件处理" })).not.toBeInTheDocument(); expect(mutations(fetcher)).toHaveLength(2); await waitFor(() => expect(onPendingChange).toHaveBeenLastCalledWith(false));
});
it.each(["hash", "upload"])("does not continue a late %s response after switching scope", async stage => {
  const digest = deferred<ArrayBuffer>(), put = deferred<Response>();
  if (stage === "hash") vi.stubGlobal("crypto", { subtle: { digest: vi.fn(() => digest.promise) }, randomUUID: vi.fn().mockReturnValue("immutable-request") });
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url, init) => init?.method === "GET" ? list() : String(url).endsWith("/upload") ? put.promise : Response.json(original));
  vi.stubGlobal("fetch", fetcher); const view = render(<ProductSourceFiles base="spaces/old" lineId="old-line"/>); await screen.findByText(/RFQ.xlsx/); choose();
  await waitFor(() => expect(stage === "hash" ? crypto.subtle.digest : fetcher).toHaveBeenCalled());
  if (stage === "upload") await waitFor(() => expect(mutations(fetcher)).toHaveLength(2));
  view.rerender(<ProductSourceFiles base="spaces/new" lineId="new-line"/>);
  await act(async () => { digest.resolve(new Uint8Array(32).buffer); put.resolve(Response.json({})); });
  expect(mutations(fetcher)).toHaveLength(stage === "hash" ? 0 : 2); expect(screen.queryByText("原件已处理，请核对解析状态和出处。")).not.toBeInTheDocument(); expect(screen.getByRole("button", { name: "上传RFQ或客户原件" })).toBeEnabled();
});
it("fences synchronous duplicate file selection before hashing finishes", async () => {
  const read = deferred<ArrayBuffer>(); const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url, init) => init?.method === "GET" ? list() : Response.json(String(url).endsWith("/source-files") ? original : {}));
  vi.stubGlobal("fetch", fetcher); render(<ProductSourceFiles base="spaces/space" lineId={null}/>); await screen.findByText(/RFQ.xlsx/);
  const first = file(read.promise), second = file(); act(() => { choose(first); choose(second); });
  expect(second.arrayBuffer).not.toHaveBeenCalled(); await act(async () => { read.resolve(bytes); }); await screen.findByText("原件已处理，请核对解析状态和出处。"); expect(mutations(fetcher).filter(([url]) => String(url).endsWith("/source-files"))).toHaveLength(1);
});
it("does not revive upload retry when the confirmed parse is followed by a failed list read", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(list()).mockResolvedValueOnce(Response.json(original)).mockResolvedValueOnce(Response.json({})).mockResolvedValueOnce(Response.json({})).mockResolvedValueOnce(Response.json({ detail: { message: "列表暂不可用" } }, { status: 503 }));
  vi.stubGlobal("fetch", fetcher); const onPendingChange = vi.fn(); render(<ProductSourceFiles base="spaces/space" lineId={null} onPendingChange={onPendingChange}/>); await screen.findByText(/RFQ.xlsx/); choose(); await screen.findByText("列表暂不可用");
  expect(screen.getByText("原件已处理，请核对解析状态和出处。")).toBeInTheDocument(); expect(screen.queryByRole("button", { name: "重试原件处理" })).not.toBeInTheDocument(); await waitFor(() => expect(onPendingChange).toHaveBeenLastCalledWith(false));
});
it.each(["parse", "revoke"])("retains the exact original file %s operation and releases its external lock after recovery", async action => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(list()).mockRejectedValueOnce(new TypeError("操作回执丢失")).mockResolvedValueOnce(Response.json({})).mockResolvedValueOnce(list());
  vi.stubGlobal("fetch", fetcher); const onPendingChange = vi.fn(); render(<ProductSourceFiles base="spaces/space" lineId="line" onPendingChange={onPendingChange}/>); await screen.findByText(/RFQ.xlsx/);
  fireEvent.click(screen.getByRole("button", { name: action === "parse" ? "重试解析" : "停止引用此原件" })); await screen.findByText("操作回执丢失"); expect(onPendingChange).toHaveBeenLastCalledWith(true);
  fireEvent.click(screen.getByRole("button", { name: "重试原文件操作" })); await waitFor(() => expect(onPendingChange).toHaveBeenLastCalledWith(false));
  const writes = mutations(fetcher); expect(writes).toHaveLength(2); expect(writes[0][0]).toBe(`/api/product-work/spaces/space/source-files/original/${action}`); expect(writes[1][0]).toBe(writes[0][0]); expect(writes[1][1]?.body).toBe(writes[0][1]?.body); expect(screen.queryByRole("button", { name: "重试原文件操作" })).not.toBeInTheDocument();
});
