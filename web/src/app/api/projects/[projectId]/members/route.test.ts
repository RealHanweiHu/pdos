import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: getCookie }),
}));

import { GET, POST } from "./route";
import { POST as REMOVE } from "./[userId]/remove/route";

const projectContext = { params: Promise.resolve({ projectId: "project/1" }) };
const memberContext = { params: Promise.resolve({ projectId: "project/1", userId: "user 2" }) };

function post(body: unknown) {
  return new Request("http://localhost/api/projects/project-1/members", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("project member BFF routes", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
  });

  it("forwards roster reads and member commands to encoded upstream paths", async () => {
    fetchMock
      .mockResolvedValueOnce(Response.json({ items: [] }))
      .mockResolvedValueOnce(Response.json({ items: [] }, { status: 201 }))
      .mockResolvedValueOnce(Response.json({ items: [] }));
    const addBody = { request_id: "r-1", user_id: "user-2" };
    const removeBody = { request_id: "r-2" };

    expect((await GET(new Request("http://localhost"), projectContext)).status).toBe(200);
    expect((await POST(post(addBody), projectContext)).status).toBe(201);
    expect((await REMOVE(post(removeBody), memberContext)).status).toBe(200);

    expect(fetchMock.mock.calls.map((call) => String(call[0]))).toEqual([
      "http://127.0.0.1:8000/api/projects/project%2F1/members",
      "http://127.0.0.1:8000/api/projects/project%2F1/members",
      "http://127.0.0.1:8000/api/projects/project%2F1/members/user%202/remove",
    ]);
    expect(fetchMock.mock.calls.slice(1).map((call) => call[1])).toEqual([
      expect.objectContaining({ method: "POST", body: JSON.stringify(addBody) }),
      expect.objectContaining({ method: "POST", body: JSON.stringify(removeBody) }),
    ]);
  });

  it("refuses without a session and never calls upstream", async () => {
    getCookie.mockReturnValue(undefined);

    expect((await GET(new Request("http://localhost"), projectContext)).status).toBe(401);
    expect((await POST(post({}), projectContext)).status).toBe(401);
    expect((await REMOVE(post({}), memberContext)).status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
