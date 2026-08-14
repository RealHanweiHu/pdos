import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: getCookie }),
}));

import { GET, POST } from "./route";

const complaintId = "11111111-1111-4111-8111-111111111111";
const ncrId = "22222222-2222-4222-8222-222222222222";

function context(qualityPath: string[]) {
  return {
    params: Promise.resolve({ projectId: "project/id with spaces", qualityPath }),
  };
}

function jsonRequest(body: object) {
  return new Request("http://localhost/api/projects/project-1/quality", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("quality BFF catch-all", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
  });

  it("allowlists reads and JSON mutations with server-side bearer auth", async () => {
    fetchMock.mockImplementation(async () => Response.json({ items: [] }));

    await GET(new Request("http://localhost"), context(["complaints"]));
    await GET(
      new Request("http://localhost"),
      context(["ncrs", ncrId, "detail"]),
    );
    await POST(
      jsonRequest({ to_status: "investigating" }),
      context(["complaints", complaintId, "transitions"]),
    );

    expect(fetchMock.mock.calls.map((call) => String(call[0]))).toEqual([
      "http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/quality/complaints",
      `http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/quality/ncrs/${ncrId}/detail`,
      `http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/quality/complaints/${complaintId}/transitions`,
    ]);
    expect(fetchMock.mock.calls[2]?.[1]).toEqual(
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ to_status: "investigating" }),
        headers: expect.objectContaining({ Authorization: "Bearer signed.jwt.value" }),
      }),
    );
  });

  it("fails closed for unknown paths, missing sessions, and non-JSON writes", async () => {
    expect(
      (await GET(new Request("http://localhost"), context(["internal-dump"]))).status,
    ).toBe(404);

    getCookie.mockReturnValue(undefined);
    expect(
      (await GET(new Request("http://localhost"), context(["complaints"]))).status,
    ).toBe(401);

    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    const invalid = new Request("http://localhost", { method: "POST", body: "x" });
    expect((await POST(invalid, context(["complaints"]))).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
