import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({ cookies: async () => ({ get: getCookie }) }));

import { GET, POST } from "./route";

const projectId = "eeeeeeee-1111-4222-8333-444444444444";
const itemId = "ffffffff-5555-4666-8777-888888888888";

function context(checkPath: string[]) {
  return { params: Promise.resolve({ projectId, checkPath }) };
}

describe("deliverable checks BFF", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
    fetchMock.mockImplementation(async () => Response.json({ items: [] }));
  });

  it("proxies the list, the template prepare and item resolution", async () => {
    await GET(new Request("http://localhost/api/x"), context([]));
    await POST(new Request("http://localhost", { method: "POST" }), context(["prepare"]));
    await POST(
      new Request("http://localhost", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "completed", evidence_reference: "TR-1" }),
      }),
      context(["items", itemId, "resolve"]),
    );

    const base = `http://127.0.0.1:8000/api/projects/${projectId}/deliverable-checks`;
    expect(fetchMock.mock.calls.map((call) => String(call[0]))).toEqual([
      base,
      `${base}/prepare`,
      `${base}/items/${itemId}/resolve`,
    ]);
  });

  it("prepare is the one write forwarded without a body", async () => {
    await POST(new Request("http://localhost", { method: "POST" }), context(["prepare"]));
    expect(fetchMock.mock.calls[0]?.[1]).not.toHaveProperty("body");
  });

  it("fails closed on unknown shapes and missing sessions", async () => {
    expect((await POST(new Request("http://localhost", { method: "POST" }), context(["reset"]))).status).toBe(404);
    expect((await POST(new Request("http://localhost", { method: "POST" }), context(["items", "nope", "resolve"]))).status).toBe(404);
    expect((await GET(new Request("http://localhost"), context(["prepare"]))).status).toBe(404);

    getCookie.mockReturnValue(undefined);
    expect((await GET(new Request("http://localhost"), context([]))).status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
