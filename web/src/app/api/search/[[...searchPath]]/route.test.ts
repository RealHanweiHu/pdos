import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: getCookie }),
}));

import { GET, POST } from "./route";

const projectId = "44444444-4444-4444-8444-444444444444";

function context(searchPath: string[]) {
  return { params: Promise.resolve({ searchPath }) };
}

describe("search BFF", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
  });

  it("forwards the query string, which carries the whole search", async () => {
    fetchMock.mockImplementation(async () => Response.json({ items: [] }));

    await GET(
      new Request("http://localhost/api/search?q=%E5%AF%86%E5%B0%81%E9%9D%A2&limit=5"),
      context([]),
    );

    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "http://127.0.0.1:8000/api/search?q=%E5%AF%86%E5%B0%81%E9%9D%A2&limit=5",
    );
  });

  it("allows the sample-match write and rejects anything else", async () => {
    fetchMock.mockImplementation(async () => Response.json({ items: [] }));

    const ok = await POST(
      new Request("http://localhost", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: "SN-1001" }),
      }),
      context(["projects", projectId, "sample-matches"]),
    );
    expect(ok.status).toBe(200);

    expect((await POST(new Request("http://localhost", { method: "POST" }), context(["dump"]))).status).toBe(404);
    expect(
      (await POST(new Request("http://localhost", { method: "POST" }), context(["projects", "not-a-uuid", "sample-matches"]))).status,
    ).toBe(404);
    expect((await GET(new Request("http://localhost"), context(["projects"]))).status).toBe(404);
  });

  it("requires a session", async () => {
    getCookie.mockReturnValue(undefined);
    expect((await GET(new Request("http://localhost/api/search?q=x"), context([]))).status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
