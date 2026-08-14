import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: getCookie }),
}));

import { GET, PATCH } from "./route";
import { POST as STAGE_TRANSITION } from "./stage-transitions/route";
import { POST as STATUS_TRANSITION } from "./transitions/route";

const context = { params: Promise.resolve({ projectId: "project/id with spaces" }) };

function request(path: string, body: object, method: "PATCH" | "POST") {
  return new Request(`http://localhost${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("dynamic Project BFF routes", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
  });

  it("encodes ids and forwards GET", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ id: "project-1" }));

    expect((await GET(new Request("http://localhost"), context)).status).toBe(200);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces",
    );
  });

  it("forwards bounded patch and transition payloads", async () => {
    fetchMock
      .mockResolvedValueOnce(Response.json({ id: "project-1" }))
      .mockResolvedValueOnce(Response.json({ id: "project-1" }))
      .mockResolvedValueOnce(Response.json({ id: "project-1" }));
    const patchBody = { name: "Updated" };
    const statusBody = { to_status: "proposed" };
    const stageBody = { to_stage_id: "stage-2" };

    await PATCH(request("/api/projects/project-1", patchBody, "PATCH"), context);
    await STATUS_TRANSITION(
      request("/api/projects/project-1/transitions", statusBody, "POST"),
      context,
    );
    await STAGE_TRANSITION(
      request("/api/projects/project-1/stage-transitions", stageBody, "POST"),
      context,
    );

    expect(fetchMock.mock.calls.map((call) => call[1])).toEqual([
      expect.objectContaining({ method: "PATCH", body: JSON.stringify(patchBody) }),
      expect.objectContaining({ method: "POST", body: JSON.stringify(statusBody) }),
      expect.objectContaining({ method: "POST", body: JSON.stringify(stageBody) }),
    ]);
  });
});
