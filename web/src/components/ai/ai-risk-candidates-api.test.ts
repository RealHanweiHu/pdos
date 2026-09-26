import { afterEach, describe, expect, it, vi } from "vitest";

import { requestInboxRiskCandidates } from "./ai-api";

describe("aggregate inbox risk candidates", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("uses one fixed same-origin endpoint and preserves each candidate's project", async () => {
    const candidates = ["project-1", "project-2"].map((project_id) => ({ id: `risk-${project_id}`, project_id, title: "Task delay", description: null, likelihood: 3, impact: 4, score: 12, created_at: "2026-09-08T12:00:00Z" }));
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ items: candidates }));
    vi.stubGlobal("fetch", fetchMock);
    expect(await requestInboxRiskCandidates()).toEqual(candidates);
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith("/api/ai/risk-candidates", { cache: "no-store", credentials: "same-origin" });
  });

  it.each([Response.json({}, { status: 503 }), Response.json({ items: [{ id: "malformed" }] })])("rejects failure or incomplete rows rather than treating them as an empty queue", async (response) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    await expect(requestInboxRiskCandidates()).rejects.toThrow();
  });
});
