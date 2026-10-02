// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: getCookie }) }));
import { POST } from "./route";

const projectId = "55555555-5555-4555-8555-555555555555";
const movementId = "77777777-7777-4777-8777-777777777777";
const context = (movement = movementId) => ({ params: Promise.resolve({ projectId, movementId: movement }) });
const json = (body: object) => new Request("http://localhost", { method: "POST",
  headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => { vi.clearAllMocks(); vi.stubGlobal("fetch", fetchMock);
  vi.stubEnv("PDOS_API_INTERNAL_URL", "http://127.0.0.1:8000");
  getCookie.mockReturnValue({ value: "synthetic.session" }); });
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

describe("material reconciliation preview BFF", () => {
  it("forwards the exact scoped preview with server-held session and no caching", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ digest: "a".repeat(64) }));
    const response = await POST(json({ evidence_id: "selected-evidence" }), context());
    expect(response.status).toBe(200);
    expect(response.headers.get("Cache-Control")).toContain("no-store");
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      `http://127.0.0.1:8000/api/projects/${projectId}/npi/material-movements/${movementId}/reconcile/preview`,
    );
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get("Authorization")).toBe("Bearer synthetic.session");
  });

  it("rejects unauthenticated, malformed and oversized requests before upstream", async () => {
    getCookie.mockReturnValue(undefined);
    expect((await POST(json({}), context())).status).toBe(401);
    getCookie.mockReturnValue({ value: "synthetic.session" });
    expect((await POST(json({}), context("../another"))).status).toBe(400);
    expect((await POST(json({ reason: "x".repeat(17000) }), context())).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("preserves current-source conflict details", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ detail: { message: "原余额已变化" } }, { status: 409 }));
    const response = await POST(json({}), context());
    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({ detail: { message: "原余额已变化" } });
  });
});
