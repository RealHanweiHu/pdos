import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: getCookie }) }));
import * as route from "./route";
const context = { params: Promise.resolve({ projectId: "project/id" }) };
const fetcher = vi.fn<typeof fetch>();
beforeEach(() => { vi.clearAllMocks(); vi.stubGlobal("fetch", fetcher); getCookie.mockReturnValue({ value: "fixture-token" }); vi.stubEnv("PDOS_API_INTERNAL_URL", "http://127.0.0.1:8000"); });
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

describe("issue event source BFF", () => {
  it("forwards only GET with authenticated bounded numeric pagination and preserves original links", async () => {
    const body = { items: [{ event_row_id: 19, existing_issue: { id: "issue", href: "/projects?entity_id=issue" } }], next_before: 19, notice: "当前来源" };
    fetcher.mockImplementation(async () => Response.json(body));
    const response = await route.GET(new Request("http://localhost?before=20&limit=10"), context);
    expect(await response.json()).toEqual(body);
    expect(String(fetcher.mock.calls[0][0])).toBe("http://127.0.0.1:8000/api/projects/project%2Fid/ai-issue-event-sources?limit=10&before=20");
    expect(fetcher.mock.calls[0][1]).toEqual(expect.objectContaining({ method: "GET", cache: "no-store", headers: expect.objectContaining({ Authorization: "Bearer fixture-token" }) }));
    await route.GET(new Request("http://localhost"), context);
    expect(String(fetcher.mock.calls[1][0])).toMatch(/\?limit=20$/);
    expect(Object.keys(route)).toEqual(["GET"]);
  });

  it("rejects invalid or repeated numeric pagination before contacting the server", async () => {
    for (const query of ["before=0", "before=-1", "before=1.2", "before=", "before=9007199254740992", "before=1&before=2", "limit=0", "limit=21", "limit=1&limit=2"]) {
      expect((await route.GET(new Request(`http://localhost?${query}`), context)).status).toBe(400);
    }
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("requires a session and preserves backend access failures", async () => {
    getCookie.mockReturnValue(undefined);
    expect((await route.GET(new Request("http://localhost"), context)).status).toBe(401);
    expect(fetcher).not.toHaveBeenCalled();
    getCookie.mockReturnValue({ value: "fixture-token" });
    const body = { detail: { code: "PROJECT_ACCESS_DENIED", message: "无权读取项目资料" } };
    fetcher.mockResolvedValueOnce(Response.json(body, { status: 403 }));
    const response = await route.GET(new Request("http://localhost"), context);
    expect(response.status).toBe(403);
    expect(await response.json()).toEqual(body);
  });
});
