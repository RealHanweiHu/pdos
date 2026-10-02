import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: getCookie }) }));
import { GET } from "./route";
const id = "55555555-5555-4555-8555-555555555555", context = { params: Promise.resolve({ projectId: "project/id" }) }, fetcher = vi.fn<typeof fetch>();
beforeEach(() => { vi.resetAllMocks(); vi.stubGlobal("fetch", fetcher); getCookie.mockReturnValue({ value: "fixture" }); vi.stubEnv("PDOS_API_INTERNAL_URL", "http://127.0.0.1:8000"); });
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
describe("Issue automatic event history BFF", () => {
  it("forwards the exact authenticated source and stable cursor without caching", async () => {
    const body = { items: [], next_before_id: null }; fetcher.mockResolvedValue(Response.json(body)); expect(await (await GET(new Request(`http://localhost?event_row_id=31&before_id=${id}&internal=ignored`), context)).json()).toEqual(body); expect(String(fetcher.mock.calls[0][0])).toBe(`http://127.0.0.1:8000/api/projects/project%2Fid/ai-issue-event-history?event_row_id=31&before_id=${id}`); expect(fetcher.mock.calls[0][1]).toEqual(expect.objectContaining({ method: "GET", cache: "no-store", headers: expect.objectContaining({ Authorization: "Bearer fixture" }) }));
  });
  it("rejects missing or invalid source/cursor and unauthenticated reads before forwarding", async () => {
    for (const query of ["", "event_row_id=0", "event_row_id=-1", "event_row_id=1.5", "event_row_id=9007199254740992", "event_row_id=31&event_row_id=32", "event_row_id=31&before_id=bad", `event_row_id=31&before_id=${id}&before_id=${id}`]) expect((await GET(new Request(`http://localhost?${query}`), context)).status).toBe(400); getCookie.mockReturnValue(undefined); expect((await GET(new Request("http://localhost?event_row_id=31"), context)).status).toBe(401); expect(fetcher).not.toHaveBeenCalled();
  });
  it("preserves denied and cursor-conflict reasons and reports retryable read failures", async () => {
    for (const status of [403, 409]) { const body = { detail: "当前来源或分页位置不可读取" }; fetcher.mockResolvedValueOnce(Response.json(body, { status })); const response = await GET(new Request("http://localhost?event_row_id=31"), context); expect(response.status).toBe(status); expect(await response.json()).toEqual(body); } fetcher.mockRejectedValueOnce(new Error("connection unavailable")); expect((await GET(new Request("http://localhost?event_row_id=31"), context)).status).toBe(503);
  });
});
