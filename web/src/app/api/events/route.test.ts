import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: getCookie }),
}));

import { GET } from "./route";
import { GET as GET_CATALOG } from "./catalog/route";

describe("Event debug BFF", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
  });

  it("forwards only allowlisted stream filters with bearer auth", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ items: [], has_more: false }));
    const response = await GET(
      new Request(
        "http://localhost/api/events?after_id=12&limit=25&event_type=PROJECT%20CREATED&project_id=project%2Fid&ignored=secret",
      ),
    );

    expect(response.status).toBe(200);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "http://127.0.0.1:8000/api/events?after_id=12&limit=25&event_type=PROJECT+CREATED&project_id=project%2Fid",
    );
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer signed.jwt.value" }),
      }),
    );
  });

  it("forwards catalog and fails closed without a session", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ items: [] }));
    expect((await GET_CATALOG()).status).toBe(200);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "http://127.0.0.1:8000/api/events/catalog",
    );

    getCookie.mockReturnValue(undefined);
    expect((await GET(new Request("http://localhost/api/events"))).status).toBe(401);
    expect((await GET_CATALOG()).status).toBe(401);
  });
});
