import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: getCookie }),
}));

import { GET, POST } from "./route";

function postRequest(body: string) {
  return new Request("http://localhost/api/requirements", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
}

describe("/api/requirements BFF", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
  });

  it("rejects missing sessions without contacting the API", async () => {
    getCookie.mockReturnValue(undefined);

    const response = await GET();

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({
      detail: { code: "INVALID_ACCESS_TOKEN", message: "Authentication required" },
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("forwards list requests with a server-only bearer token", async () => {
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    fetchMock.mockResolvedValueOnce(Response.json({ items: [] }));

    const response = await GET();

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ items: [] });
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "http://127.0.0.1:8000/api/requirements",
    );
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer signed.jwt.value",
        }),
      }),
    );
  });

  it("forwards only bounded JSON objects on create", async () => {
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    fetchMock.mockResolvedValueOnce(
      Response.json({ id: "requirement-1" }, { status: 201 }),
    );
    const payload = { code: "REQ-001", title: "Reduce leakage" };

    const response = await POST(postRequest(JSON.stringify(payload)));

    expect(response.status).toBe(201);
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(payload),
        headers: expect.objectContaining({
          Authorization: "Bearer signed.jwt.value",
          "Content-Type": "application/json",
        }),
      }),
    );

    const invalid = await POST(postRequest("not-json"));
    expect(invalid.status).toBe(400);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
