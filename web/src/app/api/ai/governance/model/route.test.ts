import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: getCookie }),
}));

import { GET, PATCH } from "./route";

function patchRequest(body: string) {
  return new Request("http://localhost/api/ai/governance/model", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body,
  });
}

describe("/api/ai/governance/model BFF", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
  });

  it("fails closed without a server-side session", async () => {
    getCookie.mockReturnValue(undefined);

    expect((await GET()).status).toBe(401);
    expect((await PATCH(patchRequest("{}"))).status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("forwards GET and bounded PATCH with bearer auth", async () => {
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    fetchMock
      .mockResolvedValueOnce(Response.json({ eligible_models: [] }))
      .mockResolvedValueOnce(Response.json({ selection: { provider: "minimax" } }));
    const payload = {
      provider: "minimax",
      model: "MiniMax-M2.7",
      daily_token_budget: 2000000,
    };

    expect((await GET()).status).toBe(200);
    expect((await PATCH(patchRequest(JSON.stringify(payload)))).status).toBe(200);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "http://127.0.0.1:8000/api/ai/governance/model",
    );
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify(payload),
        headers: expect.objectContaining({ Authorization: "Bearer signed.jwt.value" }),
      }),
    );
  });

  it("rejects invalid JSON before contacting the API", async () => {
    getCookie.mockReturnValue({ value: "signed.jwt.value" });

    expect((await PATCH(patchRequest("not-json"))).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
