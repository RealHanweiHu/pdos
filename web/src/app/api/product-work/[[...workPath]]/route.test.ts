import { afterEach, beforeEach, expect, it, vi } from "vitest";
const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: getCookie }) }));
import { GET, POST } from "./route";
const space = "33333333-3333-4333-8333-333333333333";
const definition = "44444444-4444-4444-8444-444444444444";
const context = (action: string) => ({ params: Promise.resolve({ workPath: ["spaces", space, "definitions", definition, action] }) });
const input = () => new Request("http://localhost", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: "核对后接受", accept_paths: ["items/pressure"] }) });
const fetcher = vi.fn<typeof fetch>();
beforeEach(() => { vi.clearAllMocks(); vi.stubGlobal("fetch", fetcher); getCookie.mockReturnValue({ value: "test-session" }); process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000"; });
afterEach(() => vi.unstubAllGlobals());
it("forwards derivation and selected parent changes through the signed session", async () => {
  fetcher.mockImplementation(async () => Response.json({ ok: true }));
  expect((await GET(new Request("http://localhost"), context("parent-comparison"))).status).toBe(200);
  expect((await POST(input(), context("derive"))).status).toBe(200);
  expect((await POST(input(), context("parent-merge"))).status).toBe(200);
  expect(fetcher).toHaveBeenCalledTimes(3);
  expect(String(fetcher.mock.calls[0][0])).toContain(`/spaces/${space}/definitions/${definition}/parent-comparison`);
  expect(new Headers(fetcher.mock.calls[2][1]?.headers).get("Authorization")).toBe("Bearer test-session");
  expect(JSON.parse(String(fetcher.mock.calls[2][1]?.body)).accept_paths).toEqual(["items/pressure"]);
});
it("rejects wrong verbs and unauthenticated derivation without forwarding", async () => {
  expect((await GET(new Request("http://localhost"), context("derive"))).status).toBe(404);
  expect((await POST(input(), context("parent-comparison"))).status).toBe(404);
  getCookie.mockReturnValue(undefined);
  expect((await POST(input(), context("derive"))).status).toBe(401);
  expect(fetcher).not.toHaveBeenCalled();
});
it("streams the original definition export bytes with download and private-cache headers", async () => {
  const bytes = new Uint8Array([37, 80, 68, 70, 45, 0, 255]);
  fetcher.mockImplementation(async () => new Response(bytes, { headers: { "Content-Type": "application/pdf", "Content-Disposition": "attachment; filename=definition.pdf", "Content-Length": String(bytes.length) } }));
  const download = { params: Promise.resolve({ workPath: ["spaces", space, "definition-exports", definition, "download"] }) };
  const response = await GET(new Request("http://localhost"), download);
  expect(response.status).toBe(200);
  expect(new Uint8Array(await response.arrayBuffer())).toEqual(bytes);
  expect(response.headers.get("content-type")).toBe("application/pdf");
  expect(response.headers.get("content-disposition")).toContain("definition.pdf");
  expect(response.headers.get("cache-control")).toBe("no-store");
  expect(response.headers.get("x-content-type-options")).toBe("nosniff");
  expect(new Headers(fetcher.mock.calls[0][1]?.headers).get("Authorization")).toBe("Bearer test-session");
});
it("preserves a refused download as an error and never forwards an unsigned request", async () => {
  fetcher.mockImplementation(async () => Response.json({ detail: { message: "原资料权限已撤回" } }, { status: 403 }));
  const download = { params: Promise.resolve({ workPath: ["spaces", space, "definition-exports", definition, "download"] }) };
  const response = await GET(new Request("http://localhost"), download);
  expect(response.status).toBe(403);
  expect((await response.json()).detail.message).toBe("原资料权限已撤回");
  expect(response.headers.get("content-disposition")).toBeNull();
  getCookie.mockReturnValue(undefined);
  expect((await GET(new Request("http://localhost"), download)).status).toBe(401);
  expect(fetcher).toHaveBeenCalledTimes(1);
});
it("forwards RFQ confirmation and bounded raw originals only through approved routes", async () => {
  const { PUT } = await import("./route");
  fetcher.mockImplementation(async () => Response.json({ ok: true }));
  const upload = { params: Promise.resolve({ workPath: ["spaces", space, "source-files", definition, "upload"] }) };
  const bytes = new Uint8Array([1, 2, 3]);
  expect((await PUT(new Request("http://localhost", { method: "PUT", body: bytes }), upload)).status).toBe(200);
  expect(new Uint8Array(await (fetcher.mock.calls[0][1]?.body as Blob).arrayBuffer())).toEqual(bytes);
  const rfq = { params: Promise.resolve({ workPath: ["spaces", space, "rfq-ai-confirm"] }) };
  expect((await POST(input(), rfq)).status).toBe(200);
  expect((await GET(new Request("http://localhost"), rfq)).status).toBe(404);
  expect((await PUT(new Request("http://localhost", { method: "PUT", headers: { "Content-Length": String(21 * 1024 * 1024) }, body: bytes }), upload)).status).toBe(413);
  expect(fetcher).toHaveBeenCalledTimes(2);
});

const evaluationContext = (...path: string[]) => ({ params: Promise.resolve({ workPath: ["spaces", space, "evaluation", ...path] }) });
it("forwards private evaluation preparation, bounded suites and receipts with the signed session", async () => {
  fetcher.mockImplementation(async () => Response.json({ qualification_granted: false }));
  const document = JSON.stringify({ note: "人工参考文件\r\n".repeat(3000) });
  const body = { evaluation_id: definition, suite_document: document, suite_sha256: "a".repeat(64) };
  expect((await POST(input(), evaluationContext("prepare"))).status).toBe(200);
  expect((await POST(new Request("http://localhost", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }), evaluationContext("suite"))).status).toBe(200);
  expect((await POST(input(), evaluationContext("runs"))).status).toBe(200);
  expect((await GET(new Request("http://localhost?private=ignored"), evaluationContext("runs", definition))).status).toBe(200);
  expect(fetcher).toHaveBeenCalledTimes(4);
  expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body)).suite_document).toBe(document);
  expect(new Headers(fetcher.mock.calls[1][1]?.headers).get("Authorization")).toBe("Bearer test-session");
  expect(String(fetcher.mock.calls[3][0])).toBe(`http://127.0.0.1:8000/api/product-work/spaces/${space}/evaluation/runs/${definition}`);
});

it("rejects evaluation path and verb extensions, missing sessions and oversized envelopes before forwarding", async () => {
  const { PUT } = await import("./route");
  expect((await GET(new Request("http://localhost"), evaluationContext("suite"))).status).toBe(404);
  expect((await POST(input(), evaluationContext("runs", definition))).status).toBe(404);
  expect((await PUT(input(), evaluationContext("prepare"))).status).toBe(404);
  expect((await GET(new Request("http://localhost"), evaluationContext("runs", "not-an-id"))).status).toBe(404);
  expect((await POST(input(), evaluationContext("suite", "extra"))).status).toBe(404);
  const oversized = new Request("http://localhost", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ suite_document: "x".repeat(8 * 1024 * 1024 + 16384) }) });
  expect((await POST(oversized, evaluationContext("suite"))).status).toBe(400);
  getCookie.mockReturnValue(undefined);
  expect((await POST(input(), evaluationContext("suite"))).status).toBe(401);
  expect(fetcher).not.toHaveBeenCalled();
});

it("preserves upstream evaluation permission and configuration refusals", async () => {
  fetcher.mockResolvedValueOnce(Response.json({ detail: { code: "PRODUCT_WORK_FORBIDDEN", message: "管理员权限已失效" } }, { status: 403 }));
  const response = await POST(input(), evaluationContext("suite"));
  expect(response.status).toBe(403);
  expect((await response.json()).detail.message).toBe("管理员权限已失效");
  expect(response.headers.get("cache-control")).toBe("no-store");
});

const masterContext = (...suffix: string[]) => ({ params: Promise.resolve({ workPath: ["spaces", space, "products", definition, "master-references", ...suffix] }) });
it("forwards internal master-reference reads and original writes through the signed session", async () => {
  fetcher.mockImplementation(async () => Response.json({ items: [], current_definition: null }));
  const original = { request_id: definition, expected_context_digest: "c".repeat(64), action: "register", external_id: "SYNTHETIC-ERP-01", external_revision: "R1", sources: [{ digest: "d".repeat(64) }] };
  expect((await GET(new Request("http://localhost?tenant_id=forged&project_id=forged"), masterContext())).status).toBe(200);
  expect((await POST(new Request("http://localhost", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(original) }), masterContext())).status).toBe(200);
  expect(String(fetcher.mock.calls[0][0])).toBe(`http://127.0.0.1:8000/api/product-work/spaces/${space}/products/${definition}/master-references`);
  expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body))).toEqual(original);
  expect(new Headers(fetcher.mock.calls[1][1]?.headers).get("Authorization")).toBe("Bearer test-session");
});
it("rejects master-reference route extensions, unsupported verbs and unsigned requests", async () => {
  const { PUT } = await import("./route");
  expect((await GET(new Request("http://localhost"), masterContext("extra"))).status).toBe(404);
  expect((await PUT(input(), masterContext())).status).toBe(404);
  expect((await GET(new Request("http://localhost"), { params: Promise.resolve({ workPath: ["spaces", space, "products", "not-an-id", "master-references"] }) })).status).toBe(404);
  getCookie.mockReturnValue(undefined);
  expect((await GET(new Request("http://localhost"), masterContext())).status).toBe(401);
  expect((await POST(input(), masterContext())).status).toBe(401);
  expect(fetcher).not.toHaveBeenCalled();
});
it.each([403, 409])("preserves master-reference permission or version refusal %s without an external acknowledgment", async status => {
  fetcher.mockResolvedValue(Response.json({ detail: { code: "PRODUCT_WORK_INVALID", message: "当前引用条件已变化" } }, { status }));
  const response = await POST(input(), masterContext());
  expect(response.status).toBe(status);
  expect((await response.json()).detail.message).toBe("当前引用条件已变化");
  expect(response.headers.get("cache-control")).toBe("no-store");
});

it("reads an original product run using only its ID through a signed scoped POST", async () => {
  const path = { params: Promise.resolve({ workPath: ["spaces", space, "product-ai-run-read"] }) };
  fetcher.mockImplementation(async () => Response.json({ items: [{ run_id: definition, frozen_sources: [] }] }));
  const body = { run_id: definition };
  const response = await POST(new Request("http://localhost", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }), path);
  expect(response.status).toBe(200);
  expect(response.headers.get("cache-control")).toBe("no-store");
  expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual(body);
  expect(String(fetcher.mock.calls[0][0])).toBe(`http://127.0.0.1:8000/api/product-work/spaces/${space}/product-ai-run-read`);
  expect(new Headers(fetcher.mock.calls[0][1]?.headers).get("Authorization")).toBe("Bearer test-session");
  expect((await GET(new Request("http://localhost"), path)).status).toBe(404);
  const invalid = { params: Promise.resolve({ workPath: ["spaces", "invalid", "product-ai-run-read"] }) };
  expect((await POST(input(), invalid)).status).toBe(404);
  getCookie.mockReturnValue(undefined);
  expect((await POST(input(), path)).status).toBe(401);
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("forwards only exact snapshot IDs for citation metadata through the signed original scope", async () => {
  const path = { params: Promise.resolve({ workPath: ["spaces", space, "evidence"] }) };
  fetcher.mockResolvedValue(Response.json({ items: [] }));
  const response = await GET(new Request(`http://localhost?snapshot_ids=${definition}&tenant_id=forged&snapshot_ids=${space}&product_line_id=forged&q=forged`), path);
  expect(response.status).toBe(200);
  expect(response.headers.get("cache-control")).toBe("no-store");
  expect(String(fetcher.mock.calls[0][0])).toBe(`http://127.0.0.1:8000/api/product-work/spaces/${space}/evidence?snapshot_ids=${definition}&snapshot_ids=${space}`);
  expect(new Headers(fetcher.mock.calls[0][1]?.headers).get("Authorization")).toBe("Bearer test-session");
  getCookie.mockReturnValue(undefined);
  expect((await GET(new Request(`http://localhost?snapshot_ids=${definition}`), path)).status).toBe(401);
  expect(fetcher).toHaveBeenCalledTimes(1);
});
it("binds the personal attention POST to the signed session and excludes other verbs and unsigned requests", async () => {
  const attention = { params: Promise.resolve({ workPath: ["spaces", space, "product-work-attention"] }) };
  const body = () => new Request("http://localhost", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ all_lines: false, product_line_id: definition }) });
  fetcher.mockImplementation(async () => Response.json({ candidates: [], runs: [] }));
  expect((await POST(body(), attention)).status).toBe(200);
  expect(String(fetcher.mock.calls[0][0])).toContain(`/spaces/${space}/product-work-attention`);
  expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual({ all_lines: false, product_line_id: definition });
  expect(new Headers(fetcher.mock.calls[0][1]?.headers).get("Authorization")).toBe("Bearer test-session");
  expect((await GET(new Request("http://localhost"), attention)).status).toBe(404);
  getCookie.mockReturnValue(undefined);
  expect((await POST(body(), attention)).status).toBe(401);
  expect(fetcher).toHaveBeenCalledTimes(1);
});
