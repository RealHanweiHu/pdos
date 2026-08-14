import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: getCookie }),
}));

import { GET, PATCH } from "./route";

const context = {
  params: Promise.resolve({ requirementId: "req/with unsafe characters" }),
};

describe("/api/requirements/[requirementId] BFF", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
  });

  it("encodes the route parameter before forwarding a detail request", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ id: "requirement-1" }));

    const response = await GET(new Request("http://localhost"), context);

    expect(response.status).toBe(200);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "http://127.0.0.1:8000/api/requirements/req%2Fwith%20unsafe%20characters",
    );
  });

  it("forwards bounded patches with the server-only token", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ id: "requirement-1" }));
    const payload = { title: "Updated title", customer_id: null };
    const request = new Request("http://localhost", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const response = await PATCH(request, context);

    expect(response.status).toBe(200);
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify(payload),
        headers: expect.objectContaining({
          Authorization: "Bearer signed.jwt.value",
          "Content-Type": "application/json",
        }),
      }),
    );
  });
});
