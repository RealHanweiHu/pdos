import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: getCookie }) }));
import { GET, POST } from "./route";
const id = "55555555-5555-4555-8555-555555555555", context = { params: Promise.resolve({ projectId: "project/id", runId: id }) };
const fetcher = vi.fn<typeof fetch>();
beforeEach(() => { vi.resetAllMocks(); vi.stubGlobal("fetch", fetcher); getCookie.mockReturnValue({ value: "fixture" }); vi.stubEnv("PDOS_API_INTERNAL_URL", "http://127.0.0.1:8000"); });
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
function post(body: unknown) { return new Request("http://localhost", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); }

describe("Issue application BFF", () => {
  it("forwards exact read and confirmation identities with server-side authorization", async () => {
    const result = { application: { issue_id: "original", disposition: "reused" } }, body = { request_id: id, result_id: id, expected_digest: "a".repeat(64) };
    fetcher.mockImplementation(async () => Response.json(result));
    expect(await (await GET(new Request("http://localhost"), context)).json()).toEqual(result);
    expect(await (await POST(post(body), context)).json()).toEqual(result);
    expect(fetcher.mock.calls.map(([url]) => String(url))).toEqual(Array(2).fill(`http://127.0.0.1:8000/api/projects/project%2Fid/ai-issue-applications/${id}`));
    expect(fetcher.mock.calls[0][1]).toEqual(expect.objectContaining({ method: "GET", cache: "no-store", headers: expect.objectContaining({ Authorization: "Bearer fixture" }) }));
    expect(fetcher.mock.calls[1][1]).toEqual(expect.objectContaining({ method: "POST", body: JSON.stringify(body) }));
  });
  it("preserves the backend conflict and blocks invalid ids, malformed bodies and missing sessions", async () => {
    const conflict = { detail: "当前条件未就绪" };
    fetcher.mockResolvedValueOnce(Response.json(conflict, { status: 409 }));
    const result = await POST(post({}), context); expect(result.status).toBe(409); expect(await result.json()).toEqual(conflict);
    fetcher.mockClear();
    expect((await GET(new Request("http://localhost"), { params: Promise.resolve({ projectId: "project", runId: "bad" }) })).status).toBe(400);
    expect((await POST(new Request("http://localhost", { method: "POST", headers: { "Content-Type": "application/json" }, body: "bad-json" }), context)).status).toBe(400);
    getCookie.mockReturnValue(undefined);
    expect((await GET(new Request("http://localhost"), context)).status).toBe(401);
    expect((await POST(post({}), context)).status).toBe(401);
    expect(fetcher).not.toHaveBeenCalled();
  });
});
