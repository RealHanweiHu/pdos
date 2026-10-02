import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: getCookie }) }));
import { GET, POST } from "./route";
const context = { params: Promise.resolve({ projectId: "project/id" }) }, fetcher = vi.fn<typeof fetch>();
beforeEach(() => { vi.resetAllMocks(); vi.stubGlobal("fetch", fetcher); getCookie.mockReturnValue({ value: "fixture" }); vi.stubEnv("PDOS_API_INTERNAL_URL", "http://127.0.0.1:8000"); });
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
function post(body: unknown) { return new Request("http://localhost", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); }
describe("Issue scope BFF", () => {
  it("uses the exact scope path and preserves the named revision-bound command", async () => {
    const value = { revision: 2, reused: false }, body = { request_id: "55555555-5555-4555-8555-555555555555", expected_revision: 1, enabled: false, reason: "停止本项目后续应用" };
    fetcher.mockImplementation(async () => Response.json(value));
    expect(await (await GET(new Request("http://localhost"), context)).json()).toEqual(value); expect(await (await POST(post(body), context)).json()).toEqual(value);
    expect(fetcher.mock.calls.map(call => String(call[0]))).toEqual(Array(2).fill("http://127.0.0.1:8000/api/projects/project%2Fid/ai-issue-applications/scope"));
    expect(fetcher.mock.calls[0][1]).toEqual(expect.objectContaining({ method: "GET", cache: "no-store", headers: expect.objectContaining({ Authorization: "Bearer fixture" }) })); expect(fetcher.mock.calls[1][1]?.body).toBe(JSON.stringify(body));
  });
  it("requires a session, rejects malformed requests and preserves authorization/version errors", async () => {
    for (const status of [403, 409]) { const value = { detail: "请重新核对项目授权" }; fetcher.mockResolvedValueOnce(Response.json(value, { status })); const response = await POST(post({}), context); expect(response.status).toBe(status); expect(await response.json()).toEqual(value); }
    fetcher.mockClear();
    expect((await POST(new Request("http://localhost", { method: "POST", headers: { "Content-Type": "application/json" }, body: "bad-json" }), context)).status).toBe(400);
    getCookie.mockReturnValue(undefined); expect((await GET(new Request("http://localhost"), context)).status).toBe(401); expect((await POST(post({}), context)).status).toBe(401); expect(fetcher).not.toHaveBeenCalled();
  });
});
