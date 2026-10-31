import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: getCookie }),
}));

import { GET as MY_TASKS } from "./my-tasks/route";
import { GET as RISKS } from "./risks/route";

describe("portfolio BFF routes", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
  });

  it("forwards both read-only views with the session bearer", async () => {
    fetchMock
      .mockResolvedValueOnce(Response.json({ items: [] }))
      .mockResolvedValueOnce(Response.json({ items: [] }));

    expect((await RISKS()).status).toBe(200);
    expect((await MY_TASKS()).status).toBe(200);
    expect(fetchMock.mock.calls.map((call) => String(call[0]))).toEqual([
      "http://127.0.0.1:8000/api/portfolio/risks",
      "http://127.0.0.1:8000/api/portfolio/my-tasks",
    ]);
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer signed.jwt.value" }),
      }),
    );
  });

  it("requires a session and fails closed when the API is down", async () => {
    getCookie.mockReturnValueOnce(undefined);
    expect((await RISKS()).status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();

    fetchMock.mockRejectedValueOnce(new Error("offline"));
    expect((await MY_TASKS()).status).toBe(503);
  });
});
