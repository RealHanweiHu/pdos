import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({ cookies: async () => ({ get: getCookie }) }));

import { GET, POST } from "./route";

const projectId = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const decisionId = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";

function context(decisionPath: string[]) {
  return { params: Promise.resolve({ projectId, decisionPath }) };
}

function json(body: object) {
  return new Request("http://localhost", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("decisions BFF", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
    fetchMock.mockImplementation(async () => Response.json({ items: [] }));
  });

  it("proxies the log and both writes", async () => {
    await GET(new Request("http://localhost/api/x"), context([]));
    await POST(json({ decision_kind: "technical_choice" }), context([]));
    await POST(json({ note: "已复测" }), context([decisionId, "follow-up"]));

    expect(fetchMock.mock.calls.map((call) => String(call[0]))).toEqual([
      `http://127.0.0.1:8000/api/projects/${projectId}/decisions`,
      `http://127.0.0.1:8000/api/projects/${projectId}/decisions`,
      `http://127.0.0.1:8000/api/projects/${projectId}/decisions/${decisionId}/follow-up`,
    ]);
  });

  it("fails closed on unknown shapes, bad ids and missing sessions", async () => {
    expect((await POST(json({}), context(["export-all"]))).status).toBe(404);
    expect(
      (await POST(json({}), context(["not-a-uuid", "follow-up"]))).status,
    ).toBe(404);
    expect((await GET(new Request("http://localhost"), context([decisionId]))).status).toBe(404);

    getCookie.mockReturnValue(undefined);
    expect((await GET(new Request("http://localhost"), context([]))).status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
