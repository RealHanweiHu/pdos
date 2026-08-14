import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: getCookie }),
}));

import { POST } from "./route";

const context = { params: Promise.resolve({ requirementId: "requirement/id" }) };

function conversionRequest(body: string) {
  return new Request("http://localhost/api/requirements/requirement-1/convert-to-case", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
}

describe("Requirement conversion BFF", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
  });

  it("requires a server-side session", async () => {
    getCookie.mockReturnValue(undefined);

    const response = await POST(conversionRequest("{}"), context);

    expect(response.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("encodes the Requirement id and forwards bounded JSON", async () => {
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    fetchMock.mockResolvedValueOnce(
      Response.json({ development_case: { id: "case-1" } }, { status: 201 }),
    );
    const payload = { code: "CASE-001", title: "Development case", rationale: "Approved" };

    const response = await POST(conversionRequest(JSON.stringify(payload)), context);

    expect(response.status).toBe(201);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "http://127.0.0.1:8000/api/requirements/requirement%2Fid/convert-to-case",
    );
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(payload),
        headers: expect.objectContaining({ Authorization: "Bearer signed.jwt.value" }),
      }),
    );
  });

  it("rejects unbounded or invalid input", async () => {
    getCookie.mockReturnValue({ value: "signed.jwt.value" });

    const response = await POST(conversionRequest("not-json"), context);

    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
