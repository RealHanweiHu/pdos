import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: getCookie }),
}));

import { POST as POST_MEMORY_ACTION } from "../../projects/[projectId]/memories/[memoryId]/[action]/route";
import { GET as GET_MEMORIES } from "../../projects/[projectId]/memories/route";
import { POST as POST_SEARCH } from "./route";

describe("Knowledge and Memory BFF", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
  });

  it("forwards bounded search with the HttpOnly session token", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ source_status: "ready", items: [] }));
    const payload = { project_id: "project-1", query: "connector DVT", limit: 10 };

    const response = await POST_SEARCH(
      new Request("http://localhost/api/knowledge/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    );

    expect(response.status).toBe(200);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "http://127.0.0.1:8000/api/knowledge/search",
    );
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(payload),
        headers: expect.objectContaining({ Authorization: "Bearer signed.jwt.value" }),
      }),
    );
  });

  it("allowlists Memory status and lifecycle actions", async () => {
    fetchMock
      .mockResolvedValueOnce(Response.json({ items: [] }))
      .mockResolvedValueOnce(Response.json({ status: "verified" }));
    const memoryContext = { params: Promise.resolve({ projectId: "project/1" }) };
    const list = await GET_MEMORIES(
      new Request("http://localhost/api/projects/project%2F1/memories?status=verified&secret=no"),
      memoryContext,
    );
    const action = await POST_MEMORY_ACTION(
      new Request("http://localhost/api/projects/project%2F1/memories/memory%2F1/verify", {
        method: "POST",
      }),
      {
        params: Promise.resolve({
          projectId: "project/1",
          memoryId: "memory/1",
          action: "verify",
        }),
      },
    );

    expect(list.status).toBe(200);
    expect(action.status).toBe(200);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "http://127.0.0.1:8000/api/projects/project%2F1/memories?status=verified",
    );
    expect(String(fetchMock.mock.calls[1]?.[0])).toBe(
      "http://127.0.0.1:8000/api/projects/project%2F1/memories/memory%2F1/verify",
    );
  });

  it("fails closed without a session or for an unknown action", async () => {
    getCookie.mockReturnValue(undefined);
    expect(
      (
        await POST_SEARCH(
          new Request("http://localhost/api/knowledge/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: "{}",
          }),
        )
      ).status,
    ).toBe(401);
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    expect(
      (
        await POST_MEMORY_ACTION(new Request("http://localhost"), {
          params: Promise.resolve({
            projectId: "project-1",
            memoryId: "memory-1",
            action: "delete",
          }),
        })
      ).status,
    ).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
