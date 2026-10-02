import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: getCookie }) }));
import { GET, POST } from "./route";
import { GET as PREPARE } from "./preparation/route";
const context = { params: Promise.resolve({ projectId: "project/id" }) }, id = "55555555-5555-4555-8555-555555555555";
const fetcher = vi.fn<typeof fetch>();
beforeEach(() => { vi.resetAllMocks(); vi.stubGlobal("fetch", fetcher); getCookie.mockReturnValue({ value: "fixture" }); vi.stubEnv("PDOS_API_INTERNAL_URL", "http://127.0.0.1:8000"); });
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

describe("event Issue run BFF", () => {
  it("forwards preparation, source history, UUID pagination and exact historical run reads", async () => {
    fetcher.mockImplementation(async () => Response.json({ items: [], next_before_id: null }));
    await PREPARE(new Request("http://localhost?event_row_id=31"), context);
    await GET(new Request(`http://localhost?event_row_id=31&before_id=${id}`), context);
    await GET(new Request(`http://localhost?run_id=${id}`), context);
    expect(fetcher.mock.calls.map(([url]) => String(url))).toEqual([
      "http://127.0.0.1:8000/api/projects/project%2Fid/ai-issue-event-runs/preparation?event_row_id=31",
      `http://127.0.0.1:8000/api/projects/project%2Fid/ai-issue-event-runs?event_row_id=31&before_id=${id}`,
      `http://127.0.0.1:8000/api/projects/project%2Fid/ai-issue-event-runs?run_id=${id}`,
    ]);
    expect(fetcher.mock.calls[0][1]).toEqual(expect.objectContaining({ method: "GET", cache: "no-store", headers: expect.objectContaining({ Authorization: "Bearer fixture" }) }));
  });
  it("forwards the exact original generation request and preserves backend conflicts", async () => {
    const body = { request_id: id, event_row_id: 31, expected_digest: "a".repeat(64) }, response = { detail: { message: "原资料已经变化" } };
    fetcher.mockResolvedValueOnce(Response.json(response, { status: 409 }));
    const result = await POST(new Request("http://localhost", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }), context);
    expect(fetcher.mock.calls[0][1]).toEqual(expect.objectContaining({ method: "POST", body: JSON.stringify(body) }));
    expect(result.status).toBe(409); expect(await result.json()).toEqual(response);
  });
  it("rejects invalid source ids, UUID selectors, combinations and malformed JSON locally", async () => {
    for (const query of ["event_row_id=0", "event_row_id=", "event_row_id=9007199254740992", "before_id=1", "run_id=no", `run_id=${id}&before_id=${id}`, "event_row_id=1&event_row_id=2"]) expect((await GET(new Request(`http://localhost?${query}`), context)).status).toBe(400);
    for (const query of ["", "event_row_id=0", "event_row_id=1&event_row_id=2"]) expect((await PREPARE(new Request(`http://localhost?${query}`), context)).status).toBe(400);
    expect((await POST(new Request("http://localhost", { method: "POST", headers: { "Content-Type": "application/json" }, body: "bad-json" }), context)).status).toBe(400);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("requires a server session for every operation", async () => {
    getCookie.mockReturnValue(undefined);
    expect((await GET(new Request("http://localhost"), context)).status).toBe(401);
    expect((await PREPARE(new Request("http://localhost?event_row_id=31"), context)).status).toBe(401);
    expect((await POST(new Request("http://localhost", { method: "POST" }), context)).status).toBe(401);
    expect(fetcher).not.toHaveBeenCalled();
  });
});
