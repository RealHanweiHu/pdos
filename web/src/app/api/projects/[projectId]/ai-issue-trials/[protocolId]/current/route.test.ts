import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: getCookie }) }));
import { GET } from "./route";
const id = "55555555-5555-4555-8555-555555555555", context = { params: Promise.resolve({ projectId: "project/id", protocolId: id }) }, fetcher = vi.fn<typeof fetch>();
beforeEach(() => { vi.resetAllMocks(); vi.stubGlobal("fetch", fetcher); getCookie.mockReturnValue({ value: "fixture" }); vi.stubEnv("PDOS_API_INTERNAL_URL", "http://127.0.0.1:8000"); });
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
describe("registered Issue current check BFF", () => {
  it("forwards only an authenticated uncached current read, preserving original and current results", async () => {
    const body = { protocol_id: id, state: "unavailable", original_result: null, fresh_result: null, qualification_granted: false }; fetcher.mockResolvedValue(Response.json(body));
    expect(await (await GET(new Request("http://localhost?as_of=2099-01-01"), context)).json()).toEqual(body);
    expect(String(fetcher.mock.calls[0][0])).toBe(`http://127.0.0.1:8000/api/projects/project%2Fid/ai-issue-trials/${id}/current`);
    expect(fetcher.mock.calls[0][1]).toEqual(expect.objectContaining({ method: "GET", cache: "no-store", headers: expect.objectContaining({ Authorization: "Bearer fixture" }) }));
  });
  it("rejects missing session and invalid protocol before forwarding", async () => {
    expect((await GET(new Request("http://localhost"), { params: Promise.resolve({ projectId: "project", protocolId: "bad" }) })).status).toBe(400); getCookie.mockReturnValue(undefined); expect((await GET(new Request("http://localhost"), context)).status).toBe(401); expect(fetcher).not.toHaveBeenCalled();
  });
  it("preserves denied and changed-source explanations and makes a failed read retryable", async () => {
    for (const status of [403, 409]) { const body = { detail: "当前核对范围或原资料已变化" }; fetcher.mockResolvedValueOnce(Response.json(body, { status })); const response = await GET(new Request("http://localhost"), context); expect(response.status).toBe(status); expect(await response.json()).toEqual(body); }
    fetcher.mockRejectedValueOnce(new Error("connection unavailable")); expect((await GET(new Request("http://localhost"), context)).status).toBe(503);
  });
});
