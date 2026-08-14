import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: getCookie }),
}));

import { GET, POST } from "./route";
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

  it("forwards authenticated CRM event ingress without exposing the internal API", async () => {
    getCookie.mockReturnValue(undefined);
    fetchMock.mockResolvedValueOnce(
      Response.json({ created: true, requirement_id: "requirement-1" }, { status: 201 }),
    );
    const payload = {
      project_id: "project-1",
      event_id: "crm-event-1",
      event_type: "CRM_REQUIREMENT_RECEIVED",
      entity_id: "entity-1",
      payload: { code: "CRM-1" },
      occurred_at: "2026-08-13T08:00:00Z",
    };
    const response = await POST(
      new Request("https://pdos.example/api/events", {
        method: "POST",
        headers: {
          Authorization: "Bearer signed.crm.jwt",
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      }),
    );
    expect(response.status).toBe(201);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("http://127.0.0.1:8000/api/events");
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(payload),
        headers: expect.objectContaining({ Authorization: "Bearer signed.crm.jwt" }),
      }),
    );
  });

  it("rejects malformed CRM ingress auth and bodies before upstream IO", async () => {
    getCookie.mockReturnValue(undefined);
    const noAuth = await POST(
      new Request("https://pdos.example/api/events", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      }),
    );
    expect(noAuth.status).toBe(401);
    const badBody = await POST(
      new Request("https://pdos.example/api/events", {
        method: "POST",
        headers: {
          Authorization: "Bearer signed.crm.jwt",
          "Content-Type": "text/plain",
        },
        body: "{}",
      }),
    );
    expect(badBody.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
