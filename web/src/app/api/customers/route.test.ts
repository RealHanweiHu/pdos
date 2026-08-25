import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: getCookie }),
}));

import { GET, POST } from "./route";

describe("GET /api/customers", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
  });

  it("forwards the authenticated selector and fails closed without a session", async () => {
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    fetchMock.mockResolvedValueOnce(Response.json({ items: [] }));

    const response = await GET();

    expect(response.status).toBe(200);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "http://127.0.0.1:8000/api/customers",
    );
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer signed.jwt.value",
        }),
      }),
    );

    getCookie.mockReturnValue(undefined);
    const missing = await GET();
    expect(missing.status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("forwards a bounded authenticated customer create request", async () => {
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    fetchMock.mockResolvedValueOnce(
      Response.json(
        { id: "customer-1", code: "ACME", name: "Acme Pumps", status: "active" },
        { status: 201 },
      ),
    );

    const response = await POST(
      new Request("http://localhost/api/customers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: "ACME", name: "Acme Pumps" }),
      }),
    );

    expect(response.status).toBe(201);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "http://127.0.0.1:8000/api/customers",
    );
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe("POST");
    expect(fetchMock.mock.calls[0]?.[1]?.body).toBe(
      JSON.stringify({ code: "ACME", name: "Acme Pumps" }),
    );
  });
});
