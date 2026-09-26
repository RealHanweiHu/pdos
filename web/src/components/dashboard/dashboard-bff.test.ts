import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: getCookie }) }));

import * as route from "@/app/api/dashboard/risks/route";

function request(query = "") {
  return new Request(`http://localhost/api/dashboard/risks${query}`, {
    headers: { Authorization: "Bearer untrusted.browser.token", "X-Tenant-Id": "other-tenant" },
  });
}

describe("dashboard risks BFF", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubEnv("PDOS_API_INTERNAL_URL", "http://127.0.0.1:8000");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("exposes only GET", () => {
    expect(Object.keys(route)).toEqual(["GET"]);
  });

  it("fails closed without a server session and ignores browser authorization", async () => {
    getCookie.mockReturnValue(undefined);
    expect((await route.GET(request())).status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("forwards one fixed, uncached GET with only the server session", async () => {
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    const body = { items: [], total: 0, projects: [{ project_id: "project-1", open_risk_count: 0, max_score: 0 }] };
    fetchMock.mockResolvedValue(Response.json(body));

    const response = await route.GET(request());
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(body);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(getCookie).toHaveBeenCalledWith("pdos_access_token");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("http://127.0.0.1:8000/api/dashboard/risks");
    expect(fetchMock.mock.calls[0]?.[1]).toEqual({
      method: "GET",
      cache: "no-store",
      signal: expect.any(AbortSignal),
      headers: { Accept: "application/json", Authorization: "Bearer signed.jwt.value" },
    });
  });

  it.each(["?tenant_id=other-tenant", "?project_id=other-project", "?limit=100", "?unexpected=1"])("rejects unsupported parameters %s before fetching", async (query) => {
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    expect((await route.GET(request(query))).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([401, 403, 503])("preserves upstream HTTP %i and error body", async (status) => {
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    const body = { detail: { code: "DENIED", message: "Unavailable" } };
    fetchMock.mockResolvedValue(Response.json(body, { status }));
    const response = await route.GET(request());
    expect(response.status).toBe(status);
    expect(await response.json()).toEqual(body);
  });

  it("returns a bounded unavailable response after a network failure", async () => {
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    fetchMock.mockRejectedValue(new Error("private upstream detail"));
    const response = await route.GET(request());
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ detail: { code: "DASHBOARD_RISKS_UNAVAILABLE", message: "Dashboard risks unavailable" } });
  });
});
