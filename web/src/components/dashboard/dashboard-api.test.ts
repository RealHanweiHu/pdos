import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { parseDashboardRisks, requestDashboardRisks } from "./dashboard-api";

function snapshot() {
  return {
    items: [{
      id: "risk-1",
      project_id: "project-1",
      title: "Supplier delay",
      status: "mitigating",
      likelihood: 4,
      impact: 5,
      score: 20,
      updated_at: "2026-09-08T01:00:00Z",
      project: { id: "project-1", code: "PRJ-001", name: "Pump platform" },
    }],
    total: 1,
    projects: [
      { project_id: "project-1", open_risk_count: 1, max_score: 20 },
      { project_id: "project-2", open_risk_count: 0, max_score: 0 },
    ],
  };
}

describe("dashboard risk response contract", () => {
  it("preserves server ranking and zero-risk project summaries", () => {
    const body = snapshot();
    expect(parseDashboardRisks(body)).toEqual(body);
    expect(parseDashboardRisks({ items: [], total: 0, projects: [] })).toEqual({ items: [], total: 0, projects: [] });
  });

  it.each([
    ["closed risk", (body: ReturnType<typeof snapshot>) => { body.items[0].status = "closed"; }],
    ["candidate risk", (body: ReturnType<typeof snapshot>) => { body.items[0].status = "pending_review"; }],
    ["invalid likelihood", (body: ReturnType<typeof snapshot>) => { body.items[0].likelihood = 0; }],
    ["fractional impact", (body: ReturnType<typeof snapshot>) => { body.items[0].impact = 2.5; }],
    ["score mismatch", (body: ReturnType<typeof snapshot>) => { body.items[0].score = 19; }],
    ["invalid timestamp", (body: ReturnType<typeof snapshot>) => { body.items[0].updated_at = "yesterday"; }],
    ["date without timezone or time", (body: ReturnType<typeof snapshot>) => { body.items[0].updated_at = "2026-09-08"; }],
    ["blank risk id", (body: ReturnType<typeof snapshot>) => { body.items[0].id = " "; }],
    ["blank project code", (body: ReturnType<typeof snapshot>) => { body.items[0].project.code = ""; }],
    ["different nested project", (body: ReturnType<typeof snapshot>) => { body.items[0].project.id = "other-project"; }],
    ["negative total", (body: ReturnType<typeof snapshot>) => { body.total = -1; }],
    ["fractional total", (body: ReturnType<typeof snapshot>) => { body.total = 1.5; }],
    ["missing summary", (body: ReturnType<typeof snapshot>) => { body.projects.shift(); }],
    ["duplicate summary", (body: ReturnType<typeof snapshot>) => { body.projects.push(body.projects[1]); }],
    ["total mismatch", (body: ReturnType<typeof snapshot>) => { body.projects[0].open_risk_count = 2; }],
    ["summary score below listed risk", (body: ReturnType<typeof snapshot>) => { body.projects[0].max_score = 15; }],
    ["nonzero score without risks", (body: ReturnType<typeof snapshot>) => { body.projects[1].max_score = 1; }],
    ["zero score with risks", (body: ReturnType<typeof snapshot>) => { body.projects[0].max_score = 0; }],
    ["over-eight ranking", (body: ReturnType<typeof snapshot>) => {
      body.items = Array.from({ length: 9 }, (_, index) => ({ ...body.items[0], id: `risk-${index}` }));
      body.total = 9;
      body.projects[0].open_risk_count = 9;
    }],
    ["missing ranked risk", (body: ReturnType<typeof snapshot>) => {
      body.total = 2;
      body.projects[0].open_risk_count = 2;
    }],
    ["duplicate risk id", (body: ReturnType<typeof snapshot>) => {
      body.items.push(body.items[0]);
      body.total = 2;
      body.projects[0].open_risk_count = 2;
    }],
    ["project count below ranked risks", (body: ReturnType<typeof snapshot>) => {
      body.items.push({ ...body.items[0], id: "risk-2" });
      body.total = 2;
      body.projects[1].open_risk_count = 1;
      body.projects[1].max_score = 10;
    }],
  ])("rejects %s rather than presenting an incomplete or misleading snapshot", (_, mutate) => {
    const body = snapshot();
    mutate(body);
    expect(() => parseDashboardRisks(body)).toThrow();
  });

  it.each([null, [], {}, { items: [], total: 0 }, { items: [null], total: 1, projects: [] }])("rejects malformed envelopes: %j", (body) => {
    expect(() => parseDashboardRisks(body)).toThrow();
  });

  it("rejects a non-string status even if string coercion matches an open status", () => {
    const body = snapshot();
    expect(() => parseDashboardRisks({ ...body, items: [{ ...body.items[0], status: ["open"] }] })).toThrow();
  });
});

describe("requestDashboardRisks", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => vi.unstubAllGlobals());

  it("makes one same-origin, uncached aggregate request without project parameters", async () => {
    fetchMock.mockResolvedValue(Response.json(snapshot()));
    expect(await requestDashboardRisks()).toEqual(snapshot());
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith("/api/dashboard/risks", { cache: "no-store", credentials: "same-origin" });
  });

  it.each([401, 403, 503])("propagates HTTP %i as a visible failure", async (status) => {
    fetchMock.mockResolvedValue(Response.json({}, { status }));
    await expect(requestDashboardRisks()).rejects.toThrow(`(${status})`);
  });

  it("rejects an upstream malformed success", async () => {
    fetchMock.mockResolvedValue(Response.json({ items: [] }));
    await expect(requestDashboardRisks()).rejects.toThrow("invalid dashboard risk response");
  });
});
