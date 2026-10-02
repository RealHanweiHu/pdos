import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: getCookie }) }));
import { GET, POST } from "./route";
const id = "55555555-5555-4555-8555-555555555555", context = { params: Promise.resolve({ projectId: "project/id", runId: id }) };
const fetcher = vi.fn<typeof fetch>();
beforeEach(() => { vi.resetAllMocks(); vi.stubGlobal("fetch", fetcher); getCookie.mockReturnValue({ value: "fixture" }); vi.stubEnv("PDOS_API_INTERNAL_URL", "http://127.0.0.1:8000"); });
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
function post(body: unknown) { return new Request("http://localhost", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); }

describe("Issue review BFF", () => {
  it("forwards exact read and confirmation identities with server-side authorization", async () => {
    const result = { review: { state: "declined", version: 1 } }, body = { request_id: id, result_id: id, expected_digest: "a".repeat(64), expected_version: 0, action: "decline", reason: "待补证" };
    fetcher.mockImplementation(async () => Response.json(result));
    expect(await (await GET(new Request("http://localhost?before_version=21"), context)).json()).toEqual(result);
    expect(await (await POST(post(body), context)).json()).toEqual(result);
    expect(fetcher.mock.calls.map(([url]) => String(url))).toEqual([`http://127.0.0.1:8000/api/projects/project%2Fid/ai-issue-applications/${id}/review?before_version=21`, `http://127.0.0.1:8000/api/projects/project%2Fid/ai-issue-applications/${id}/review`]);
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
  it("rejects ambiguous, nonpositive and unsafe history cursors before forwarding", async () => {
    for (const query of ["0", "-1", "1.5", "9007199254740992", "", "1&before_version=2"]) {
      expect((await GET(new Request(`http://localhost?before_version=${query}`), context)).status).toBe(400);
    }
    expect((await POST(new Request("http://localhost?before_version=2", { method: "POST", body: "{}" }), context)).status).toBe(400);
    expect(fetcher).not.toHaveBeenCalled();
  });

});
