import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: getCookie }),
}));

import { GET, POST, PUT } from "./route";

const meetingId = "33333333-3333-4333-8333-333333333333";

function context(meetingPath: string[]) {
  return {
    params: Promise.resolve({ projectId: "project/id with spaces", meetingPath }),
  };
}

function jsonRequest(body: object, method = "POST") {
  return new Request("http://localhost/api/projects/project-1/meetings", {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("meetings BFF catch-all", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
  });

  it("allowlists reads and JSON mutations with server-side bearer auth", async () => {
    fetchMock.mockImplementation(async () => Response.json({ items: [] }));

    await GET(new Request("http://localhost"), context([]));
    await GET(new Request("http://localhost"), context([meetingId, "agenda"]));
    await PUT(jsonRequest({ items: [] }, "PUT"), context([meetingId, "agenda"]));
    await POST(
      jsonRequest({
        provider: "dingtalk",
        external_meeting_id: "conf-1",
        join_url: "https://meeting.dingtalk.com/j/conf-1",
      }),
      context([meetingId, "conference"]),
    );

    expect(fetchMock.mock.calls.map((call) => String(call[0]))).toEqual([
      "http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/meetings",
      `http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/meetings/${meetingId}/agenda`,
      `http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/meetings/${meetingId}/agenda`,
      `http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/meetings/${meetingId}/conference`,
    ]);
    expect(fetchMock.mock.calls[3]?.[1]).toEqual(
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Authorization: "Bearer signed.jwt.value" }),
      }),
    );
  });

  it("archive is the one write forwarded without a body", async () => {
    fetchMock.mockImplementation(async () => Response.json({ id: meetingId }));

    await POST(
      new Request("http://localhost", { method: "POST" }),
      context([meetingId, "archive"]),
    );

    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      `http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/meetings/${meetingId}/archive`,
    );
    expect(fetchMock.mock.calls[0]?.[1]).not.toHaveProperty("body");
  });

  it("fails closed for unknown paths, non-uuid ids, missing sessions and bad JSON", async () => {
    expect(
      (await GET(new Request("http://localhost"), context(["internal-dump"]))).status,
    ).toBe(404);
    expect(
      (await GET(new Request("http://localhost"), context([meetingId, "secrets"]))).status,
    ).toBe(404);
    // Only `agenda` accepts PUT; a PUT elsewhere must not reach the backend.
    expect(
      (await PUT(jsonRequest({}, "PUT"), context([meetingId, "status"]))).status,
    ).toBe(404);

    getCookie.mockReturnValue(undefined);
    expect((await GET(new Request("http://localhost"), context([]))).status).toBe(401);

    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    const invalid = new Request("http://localhost", { method: "POST", body: "x" });
    expect((await POST(invalid, context([meetingId, "status"]))).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
