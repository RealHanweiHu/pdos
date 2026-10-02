import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: getCookie }) }));
import { POST as single } from "./route";
import { POST as run } from "../withdraw-run/route";
const id = "55555555-5555-4555-8555-555555555555", context = { params: Promise.resolve({ projectId: "project/id", runId: id }) };
const fetcher = vi.fn<typeof fetch>();
beforeEach(() => { vi.resetAllMocks(); vi.stubGlobal("fetch", fetcher); getCookie.mockReturnValue({ value: "fixture" }); vi.stubEnv("PDOS_API_INTERNAL_URL", "http://127.0.0.1:8000"); });
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
function post(body: unknown) { return new Request("http://localhost", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); }

describe("Issue withdrawal BFF", () => {
  it("keeps single and whole-run endpoints separate with exact request bodies", async () => {
    const response = { id, kind: "single", items: [] }, one = { request_id: id, application_id: id, reason: "重复来源" }, all = { request_id: id, reason: "撤销本次运行" };
    fetcher.mockImplementation(async () => Response.json(response));
    expect(await (await single(post(one), context)).json()).toEqual(response);
    expect(await (await run(post(all), context)).json()).toEqual(response);
    expect(fetcher.mock.calls.map(([url]) => String(url))).toEqual([`http://127.0.0.1:8000/api/projects/project%2Fid/ai-issue-applications/${id}/withdraw`, `http://127.0.0.1:8000/api/projects/project%2Fid/ai-issue-applications/${id}/withdraw-run`]);
    expect(fetcher.mock.calls[0][1]).toEqual(expect.objectContaining({ method: "POST", cache: "no-store", headers: expect.objectContaining({ Authorization: "Bearer fixture" }), body: JSON.stringify(one) }));
    expect(fetcher.mock.calls[1][1]?.body).toBe(JSON.stringify(all));
  });
  it("preserves conflicts and rejects unauthenticated, malformed or invalid original-run requests", async () => {
    fetcher.mockResolvedValueOnce(Response.json({ detail: "已由人工办理，不能撤回" }, { status: 409 }));
    const response = await single(post({}), context); expect(response.status).toBe(409); expect(await response.json()).toEqual({ detail: "已由人工办理，不能撤回" }); fetcher.mockClear();
    for (const endpoint of [single, run]) {
      expect((await endpoint(post({}), { params: Promise.resolve({ projectId: "project", runId: "invalid" }) })).status).toBe(400);
      expect((await endpoint(new Request("http://localhost", { method: "POST", headers: { "Content-Type": "application/json" }, body: "bad-json" }), context)).status).toBe(400);
    }
    getCookie.mockReturnValue(undefined);
    expect((await single(post({}), context)).status).toBe(401); expect((await run(post({}), context)).status).toBe(401);
    expect(fetcher).not.toHaveBeenCalled();
  });
});
