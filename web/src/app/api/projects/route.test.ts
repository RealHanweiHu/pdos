import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: getCookie }),
}));

import { GET, POST } from "./route";

function projectRequest(body: string) {
  return new Request("http://localhost/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
}

describe("/api/projects BFF", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
  });

  it("fails closed without a server-side session", async () => {
    getCookie.mockReturnValue(undefined);

    expect((await GET()).status).toBe(401);
    expect((await POST(projectRequest("{}"))).status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("forwards list and bounded create requests", async () => {
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    fetchMock
      .mockResolvedValueOnce(Response.json({ items: [] }))
      .mockResolvedValueOnce(Response.json({ id: "project-1" }, { status: 201 }));
    const payload = {
      development_case_id: "case-1",
      code: "PRJ-001",
      name: "Project one",
    };

    expect((await GET()).status).toBe(200);
    expect((await POST(projectRequest(JSON.stringify(payload)))).status).toBe(201);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "http://127.0.0.1:8000/api/projects",
    );
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(payload),
        headers: expect.objectContaining({ Authorization: "Bearer signed.jwt.value" }),
      }),
    );
  });

  it("rejects invalid JSON before contacting the API", async () => {
    getCookie.mockReturnValue({ value: "signed.jwt.value" });

    expect((await POST(projectRequest("not-json"))).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
