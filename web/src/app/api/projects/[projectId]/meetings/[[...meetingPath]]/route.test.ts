import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: getCookie }),
}));

import { GET, POST, PUT } from "./route";

const meetingId = "33333333-3333-4333-8333-333333333333";
const minutesId = "44444444-4444-4444-8444-444444444444";

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

  it("forwards an exact minutes record without replacing it with the latest page", async () => {
    const original = { items: [{ id: minutesId, version_no: 1 }], current_version: 3, next_before: null };
    fetchMock.mockResolvedValue(Response.json(original));
    const result = await GET(
      new Request(`http://localhost?record_id=${minutesId}`),
      context([meetingId, "minutes"]),
    );
    expect(result.status).toBe(200);
    expect(await result.json()).toEqual(original);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      `http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/meetings/${meetingId}/minutes?record_id=${minutesId}`,
    );
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(expect.objectContaining({
      method: "GET", headers: expect.objectContaining({ Authorization: "Bearer signed.jwt.value" }),
    }));
  });

  it("rejects invalid or conflicting minutes selectors before contacting the API", async () => {
    expect((await GET(
      new Request("http://localhost?record_id=not-a-uuid"), context([meetingId, "minutes"]),
    )).status).toBe(400);
    expect((await GET(
      new Request(`http://localhost?record_id=${minutesId}&before_version=2`), context([meetingId, "minutes"]),
    )).status).toBe(409);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("preserves the existing minutes cursor and returns a missing record error unchanged", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ items: [], next_before: null }));
    await GET(new Request("http://localhost?before_version=2"), context([meetingId, "minutes"]));
    expect(String(fetchMock.mock.calls[0]?.[0]).endsWith(`/minutes?before_version=2`)).toBe(true);
    const missing = { detail: { code: "MEETING_NOT_FOUND", message: "Meeting was not found" } };
    fetchMock.mockResolvedValueOnce(Response.json(missing, { status: 404 }));
    const response = await GET(
      new Request(`http://localhost?record_id=${minutesId}`), context([meetingId, "minutes"]),
    );
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual(missing);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("forwards meeting event history and its UUID cursor without altering trigger or run states", async () => {
    const original = { items: [{ id: minutesId, status: "queued", reason: "已进入生成队列", run: { id: meetingId, status: "failed", error: "MODEL_UNAVAILABLE" } }], next_before: minutesId };
    fetchMock.mockResolvedValueOnce(Response.json(original));
    const result = await GET(
      new Request(`http://localhost?before=${minutesId}`), context([meetingId, "ai-event-history"]),
    );
    expect(result.status).toBe(200);
    expect(await result.json()).toEqual(original);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      `http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/meetings/${meetingId}/ai-event-history?before=${minutesId}`,
    );
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(expect.objectContaining({
      method: "GET", headers: expect.objectContaining({ Authorization: "Bearer signed.jwt.value" }),
    }));
    fetchMock.mockResolvedValueOnce(Response.json({ items: [], next_before: null }));
    await GET(new Request("http://localhost"), context([meetingId, "ai-event-history"]));
    expect(String(fetchMock.mock.calls[1]?.[0]).endsWith(`/${meetingId}/ai-event-history`)).toBe(true);
  });

  it("keeps event history read-only and rejects invalid cursors or paths locally", async () => {
    for (const before of ["", "not-a-uuid", "1"]) {
      expect((await GET(new Request(`http://localhost?before=${before}`), context([meetingId, "ai-event-history"]))).status).toBe(400);
    }
    expect((await POST(jsonRequest({}), context([meetingId, "ai-event-history"]))).status).toBe(404);
    expect((await PUT(jsonRequest({}, "PUT"), context([meetingId, "ai-event-history"]))).status).toBe(404);
    expect((await GET(new Request("http://localhost"), context([meetingId, "ai-event-history", "extra"]))).status).toBe(404);
    expect((await GET(new Request("http://localhost"), context(["invalid", "ai-event-history"]))).status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
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
