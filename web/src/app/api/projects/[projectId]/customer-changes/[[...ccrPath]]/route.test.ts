import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({ cookies: async () => ({ get: getCookie }) }));

import { GET, POST } from "./route";

const projectId = "aaaaaaaa-1111-4222-8333-444444444444";
const ccrId = "bbbbbbbb-5555-4666-8777-888888888888";

function context(ccrPath: string[]) {
  return { params: Promise.resolve({ projectId, ccrPath }) };
}

function json(body: object) {
  return new Request("http://localhost", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("customer change BFF", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
    fetchMock.mockImplementation(async () => Response.json({ items: [] }));
  });

  it("proxies the whole chain", async () => {
    await GET(new Request("http://localhost/api/x"), context([]));
    await POST(json({ code: "CCR-1" }), context([]));
    await POST(json({}), context([ccrId, "analyze"]));
    await POST(json({ quote_note: "x", lead_time_days: 7 }), context([ccrId, "reply"]));
    await POST(json({}), context([ccrId, "reply", "approve"]));
    await POST(json({ accepted: true }), context([ccrId, "customer-decision"]));
    await POST(json({}), context([ccrId, "engineering-change"]));

    const base = `http://127.0.0.1:8000/api/projects/${projectId}/customer-changes`;
    expect(fetchMock.mock.calls.map((call) => String(call[0]))).toEqual([
      base,
      base,
      `${base}/${ccrId}/analyze`,
      `${base}/${ccrId}/reply`,
      `${base}/${ccrId}/reply/approve`,
      `${base}/${ccrId}/customer-decision`,
      `${base}/${ccrId}/engineering-change`,
    ]);
  });

  it("keeps the four-eyes approval as its own reachable shape only", async () => {
    // `reply/approve` must not be reachable by appending anything else, and a
    // deeper path under reply must not resolve to the approval.
    expect((await POST(json({}), context([ccrId, "reply", "approve", "force"]))).status).toBe(404);
    expect((await POST(json({}), context([ccrId, "approve"]))).status).toBe(404);
    expect((await GET(new Request("http://localhost"), context([ccrId, "reply", "approve"]))).status).toBe(404);
    expect((await POST(json({}), context(["not-a-uuid", "analyze"]))).status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("requires a session", async () => {
    getCookie.mockReturnValue(undefined);
    expect((await GET(new Request("http://localhost"), context([]))).status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
