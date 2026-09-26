import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({ cookies: async () => ({ get: getCookie }) }));

import { GET, POST } from "./route";

const projectId = "11111111-2222-4333-8444-555555555555";
const id = "66666666-7777-4888-8999-aaaaaaaaaaaa";

function context(changePath: string[]) {
  return { params: Promise.resolve({ projectId, changePath }) };
}

function json(body: object) {
  return new Request("http://localhost", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("change governance BFF", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
    fetchMock.mockImplementation(async () => Response.json({ ecrs: [], ecns: [] }));
  });

  it("proxies the ECR chain and the handoff verbs", async () => {
    await GET(new Request("http://localhost/api/x"), context([]));
    await POST(json({ code: "ECR-1" }), context(["ecrs"]));
    await POST(json({}), context(["ecrs", id, "start-impact"]));
    await POST(json({ outcome: "approved" }), context(["ecrs", id, "decide"]));
    await POST(json({}), context(["ecns", id, "submit-effectivity"]));
    await POST(json({ confirmation: "EXPORT_CONFIRMED" }), context(["handoffs", id, "export"]));
    await GET(new Request("http://localhost/api/x"), context(["handoffs", id, "delivery"]));

    expect(fetchMock.mock.calls.map((call) => String(call[0]))).toEqual([
      `http://127.0.0.1:8000/api/projects/${projectId}/changes`,
      `http://127.0.0.1:8000/api/projects/${projectId}/changes/ecrs`,
      `http://127.0.0.1:8000/api/projects/${projectId}/changes/ecrs/${id}/start-impact`,
      `http://127.0.0.1:8000/api/projects/${projectId}/changes/ecrs/${id}/decide`,
      `http://127.0.0.1:8000/api/projects/${projectId}/changes/ecns/${id}/submit-effectivity`,
      `http://127.0.0.1:8000/api/projects/${projectId}/changes/handoffs/${id}/export`,
      `http://127.0.0.1:8000/api/projects/${projectId}/changes/handoffs/${id}/delivery`,
    ]);
  });

  it("does not let a mistyped verb reach a different handoff operation", async () => {
    expect((await POST(json({}), context(["handoffs", id, "exprt"]))).status).toBe(404);
    expect((await POST(json({}), context(["handoffs", id]))).status).toBe(404);
    // delivery is a read; it must not be reachable as a write.
    expect((await POST(json({}), context(["handoffs", id, "delivery"]))).status).toBe(404);
    // ...and the ECR verbs must not be reachable as reads.
    expect((await GET(new Request("http://localhost"), context(["ecrs", id, "decide"]))).status).toBe(404);
    expect((await POST(json({}), context(["ecrs", "not-a-uuid", "decide"]))).status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("requires a session", async () => {
    getCookie.mockReturnValue(undefined);
    expect((await GET(new Request("http://localhost"), context([]))).status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
