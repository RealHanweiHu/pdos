import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: getCookie }),
}));

import { GET } from "./route";

const context = { params: Promise.resolve({ projectId: "project/id with spaces" }) };

describe("Project members BFF route", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
  });

  it("encodes the project id and forwards the bearer token", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ items: [] }));

    expect((await GET(new Request("http://localhost"), context)).status).toBe(200);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/members",
    );
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer signed.jwt.value" }),
      }),
    );
  });

  it("rejects requests without a session before calling the API", async () => {
    getCookie.mockReturnValue(undefined);

    expect((await GET(new Request("http://localhost"), context)).status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fails closed when the API is unreachable", async () => {
    fetchMock.mockRejectedValueOnce(new Error("offline"));

    const response = await GET(new Request("http://localhost"), context);
    expect(response.status).toBe(503);
  });
});
