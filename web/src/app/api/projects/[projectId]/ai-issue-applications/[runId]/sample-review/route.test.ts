import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: getCookie }) }));
import { GET, POST } from "./route";
const id = "55555555-5555-4555-8555-555555555555", context = { params: Promise.resolve({ projectId: "project/id", runId: id }) }, fetcher = vi.fn<typeof fetch>();
beforeEach(() => { vi.resetAllMocks(); vi.stubGlobal("fetch", fetcher); getCookie.mockReturnValue({ value: "fixture" }); vi.stubEnv("PDOS_API_INTERNAL_URL", "http://127.0.0.1:8000"); });
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
function post(body: unknown, query = "") { return new Request(`http://localhost${query}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); }
describe("AI Issue sample-review BFF", () => {
  it("forwards authenticated stable history and exact named review, preserving its original receipt", async () => {
    const body = { request_id: id, expected_digest: "a".repeat(64), verdict: "needs_correction", reason: "补充失败条件" }, value = { application_id: id, history: [], review_receipt: { id }, replayed: true }; fetcher.mockImplementation(async () => Response.json(value));
    expect(await (await GET(new Request(`http://localhost?before_id=${id}`), context)).json()).toEqual(value); expect(await (await POST(post(body), context)).json()).toEqual(value);
    expect(fetcher.mock.calls.map(call => String(call[0]))).toEqual([`http://127.0.0.1:8000/api/projects/project%2Fid/ai-issue-applications/${id}/sample-review?before_id=${id}`, `http://127.0.0.1:8000/api/projects/project%2Fid/ai-issue-applications/${id}/sample-review`]); expect(fetcher.mock.calls[0][1]).toEqual(expect.objectContaining({ method: "GET", cache: "no-store", headers: expect.objectContaining({ Authorization: "Bearer fixture" }) })); expect(fetcher.mock.calls[1][1]?.body).toBe(JSON.stringify(body));
  });
  it("rejects malformed history, runs, bodies and missing sessions before forwarding", async () => {
    for (const query of ["before_id=bad", `before_id=${id}&before_id=${id}`]) expect((await GET(new Request(`http://localhost?${query}`), context)).status).toBe(400); expect((await POST(post({}, `?before_id=${id}`), context)).status).toBe(400); expect((await GET(new Request("http://localhost"), { params: Promise.resolve({ projectId: "project", runId: "bad" }) })).status).toBe(400); expect((await POST(new Request("http://localhost", { method: "POST", headers: { "Content-Type": "application/json" }, body: "bad" }), context)).status).toBe(400); getCookie.mockReturnValue(undefined); expect((await GET(new Request("http://localhost"), context)).status).toBe(401); expect((await POST(post({}), context)).status).toBe(401); expect(fetcher).not.toHaveBeenCalled();
  });
  it("preserves permission/digest errors and reports uncertain upstream responses", async () => {
    for (const status of [403, 409]) { const value = { detail: "抽检权限或原问题已有变化" }; fetcher.mockResolvedValueOnce(Response.json(value, { status })); const response = await POST(post({}), context); expect(response.status).toBe(status); expect(await response.json()).toEqual(value); } fetcher.mockRejectedValueOnce(new Error("connection unavailable")); expect((await POST(post({}), context)).status).toBe(503);
  });
});
