import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({ cookies: async () => ({ get: getCookie }) }));

import { forwardEvidence } from "./evidence-bff";

const snapshotId = "aaaaaaaa-2222-4333-8444-555555555555";

function context(evidencePath: string[]) {
  return { params: Promise.resolve({ evidencePath }) };
}

function json(body: object) {
  return new Request("http://localhost", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("evidence BFF", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
    fetchMock.mockImplementation(async () => Response.json({ items: [] }));
  });

  it("proxies sources, snapshots and the two linkage writes", async () => {
    await forwardEvidence("GET", new Request("http://localhost/api/x"), context(["sources"]));
    await forwardEvidence("POST", json({ name: "s" }), context(["sources"]));
    await forwardEvidence(
      "GET",
      new Request("http://localhost/api/x?include_superseded=false"),
      context(["snapshots"]),
    );
    await forwardEvidence("POST", json({ content: "c" }), context(["snapshots"]));
    await forwardEvidence("GET", new Request("http://localhost/api/x"), context(["snapshots", snapshotId]));
    await forwardEvidence("POST", json({}), context(["snapshots", snapshotId, "supersede"]));
    await forwardEvidence("POST", json({}), context(["snapshots", snapshotId, "conflict"]));

    expect(fetchMock.mock.calls.map((call) => String(call[0]))).toEqual([
      "http://127.0.0.1:8000/api/evidence/sources",
      "http://127.0.0.1:8000/api/evidence/sources",
      "http://127.0.0.1:8000/api/evidence/snapshots?include_superseded=false",
      "http://127.0.0.1:8000/api/evidence/snapshots",
      `http://127.0.0.1:8000/api/evidence/snapshots/${snapshotId}`,
      `http://127.0.0.1:8000/api/evidence/snapshots/${snapshotId}/supersede`,
      `http://127.0.0.1:8000/api/evidence/snapshots/${snapshotId}/conflict`,
    ]);
  });

  it("offers no way to edit a captured snapshot", async () => {
    // A snapshot is immutable; correcting one means capturing a new one and
    // superseding. There must be no write path that looks like an edit.
    expect((await forwardEvidence("POST", json({}), context(["snapshots", snapshotId]))).status).toBe(404);
    expect((await forwardEvidence("POST", json({}), context(["snapshots", snapshotId, "edit"]))).status).toBe(404);
    expect((await forwardEvidence("POST", json({}), context(["snapshots", snapshotId, "delete"]))).status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fails closed on bad ids, unknown paths and missing sessions", async () => {
    expect((await forwardEvidence("GET", new Request("http://localhost"), context(["dump"]))).status).toBe(404);
    expect((await forwardEvidence("POST", json({}), context(["snapshots", "nope", "supersede"]))).status).toBe(404);

    getCookie.mockReturnValue(undefined);
    expect((await forwardEvidence("GET", new Request("http://localhost"), context(["sources"]))).status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
