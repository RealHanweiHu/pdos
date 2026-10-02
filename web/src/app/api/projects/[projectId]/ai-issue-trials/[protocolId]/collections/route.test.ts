import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: getCookie }) }));
import { GET, POST } from "./route";
import { GET as detail } from "./[collectionId]/route";
const id = "55555555-5555-4555-8555-555555555555", context = { params: Promise.resolve({ projectId: "project/id", protocolId: id }) }, detailContext = { params: Promise.resolve({ projectId: "project/id", protocolId: id, collectionId: id }) };
const fetcher = vi.fn<typeof fetch>();
beforeEach(() => { vi.resetAllMocks(); vi.stubGlobal("fetch", fetcher); getCookie.mockReturnValue({ value: "fixture" }); vi.stubEnv("PDOS_API_INTERNAL_URL", "http://127.0.0.1:8000"); });
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
function post(body: unknown) { return new Request("http://localhost", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); }
describe("Issue trial collections BFF", () => {
  it("forwards authenticated stable history, original detail, and the exact collection command", async () => {
    const value = { id, qualification_granted: false }, body = { request_id: id };
    fetcher.mockImplementation(async () => Response.json(value));
    expect(await (await GET(new Request(`http://localhost?before_id=${id}&limit=10`), context)).json()).toEqual(value);
    expect(await (await detail(new Request("http://localhost"), detailContext)).json()).toEqual(value);
    expect(await (await POST(post(body), context)).json()).toEqual(value);
    expect(fetcher.mock.calls.map(call => String(call[0]))).toEqual([`http://127.0.0.1:8000/api/projects/project%2Fid/ai-issue-trials/${id}/collections?limit=10&before_id=${id}`, `http://127.0.0.1:8000/api/projects/project%2Fid/ai-issue-trials/${id}/collections/${id}`, `http://127.0.0.1:8000/api/projects/project%2Fid/ai-issue-trials/${id}/collections`]);
    expect(fetcher.mock.calls[0][1]).toEqual(expect.objectContaining({ method: "GET", cache: "no-store", headers: expect.objectContaining({ Authorization: "Bearer fixture" }) }));
    expect(fetcher.mock.calls[2][1]).toEqual(expect.objectContaining({ method: "POST", body: JSON.stringify(body) }));
  });
  it("rejects invalid pagination, identifiers, malformed bodies and missing sessions", async () => {
    for (const query of ["before_id=bad", `before_id=${id}&before_id=${id}`, "limit=0", "limit=21", "limit=1&limit=2", "limit=1.5"]) expect((await GET(new Request(`http://localhost?${query}`), context)).status).toBe(400);
    expect((await GET(new Request("http://localhost"), { params: Promise.resolve({ projectId: "project", protocolId: "invalid" }) })).status).toBe(400);
    expect((await detail(new Request("http://localhost"), { params: Promise.resolve({ projectId: "project", protocolId: id, collectionId: "invalid" }) })).status).toBe(400);
    expect((await POST(new Request("http://localhost", { method: "POST", headers: { "Content-Type": "application/json" }, body: "bad-json" }), context)).status).toBe(400);
    getCookie.mockReturnValue(undefined);
    expect((await GET(new Request("http://localhost"), context)).status).toBe(401); expect((await detail(new Request("http://localhost"), detailContext)).status).toBe(401); expect((await POST(post({}), context)).status).toBe(401);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("preserves the server's capacity and permission explanation", async () => {
    for (const status of [403, 409]) {
      const value = { detail: status === 409 ? "原窗口超过5000条，未保存部分结果" : "当前账号不能采集" };
      fetcher.mockResolvedValueOnce(Response.json(value, { status })); const response = await POST(post({}), context);
      expect(response.status).toBe(status); expect(await response.json()).toEqual(value);
    }
  });
});
