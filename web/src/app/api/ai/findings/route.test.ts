import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: getCookie }),
}));

import { GET as GET_BRIEF } from "../brief/route";
import { POST as POST_CHAT } from "../chat/route";
import { POST as POST_APPLY } from "./[findingId]/apply/route";
import { POST as POST_REVIEW } from "./[findingId]/review/route";
import { GET } from "./route";

describe("AI workspace BFF", () => {
  const fetchMock = vi.fn<typeof fetch>();
  const context = { params: Promise.resolve({ findingId: "finding/id" }) };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
  });

  it("forwards only allowlisted Finding filters", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ items: [] }));
    const response = await GET(
      new Request("http://localhost/api/ai/findings?project_id=p%2F1&status=accepted&secret=no"),
    );

    expect(response.status).toBe(200);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "http://127.0.0.1:8000/api/ai/findings?project_id=p%2F1&status=accepted",
    );
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer signed.jwt.value" }),
      }),
    );
  });

  it("keeps review and apply as separate upstream actions", async () => {
    fetchMock
      .mockResolvedValueOnce(Response.json({ status: "accepted" }))
      .mockResolvedValueOnce(Response.json({ finding: { status: "applied" } }));
    const reviewPayload = { decision: "accepted" };
    const review = await POST_REVIEW(
      new Request("http://localhost/api/ai/findings/finding%2Fid/review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(reviewPayload),
      }),
      context,
    );
    const apply = await POST_APPLY(
      new Request("http://localhost/api/ai/findings/finding%2Fid/apply", { method: "POST" }),
      context,
    );

    expect(review.status).toBe(200);
    expect(apply.status).toBe(200);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "http://127.0.0.1:8000/api/ai/findings/finding%2Fid/review",
    );
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({ method: "POST", body: JSON.stringify(reviewPayload) }),
    );
    expect(String(fetchMock.mock.calls[1]?.[0])).toBe(
      "http://127.0.0.1:8000/api/ai/findings/finding%2Fid/apply",
    );
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(expect.objectContaining({ method: "POST" }));
  });

  it("forwards brief and chat without exposing the session token", async () => {
    fetchMock
      .mockResolvedValueOnce(Response.json({ status: "active", items: [] }))
      .mockResolvedValueOnce(Response.json({ status: "insufficient_evidence", citations: [] }));
    expect((await GET_BRIEF()).status).toBe(200);
    const payload = { project_id: "project-1", question: "What changed?" };
    expect(
      (
        await POST_CHAT(
          new Request("http://localhost/api/ai/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          }),
        )
      ).status,
    ).toBe(200);
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(
      expect.objectContaining({ method: "POST", body: JSON.stringify(payload) }),
    );
  });

  it("fails closed without a session", async () => {
    getCookie.mockReturnValue(undefined);
    expect((await GET(new Request("http://localhost/api/ai/findings"))).status).toBe(401);
    expect((await GET_BRIEF()).status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
