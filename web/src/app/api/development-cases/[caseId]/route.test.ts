import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: getCookie }),
}));

import { GET, PATCH } from "./route";
import { POST as TRANSITION } from "./transitions/route";

const context = { params: Promise.resolve({ caseId: "case/id with spaces" }) };

function request(path: string, body: string, method: "PATCH" | "POST") {
  return new Request(`http://localhost${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body,
  });
}

describe("dynamic Development Case BFF routes", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
  });

  it("encodes ids and forwards GET", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ id: "case-1" }));

    const response = await GET(new Request("http://localhost"), context);

    expect(response.status).toBe(200);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "http://127.0.0.1:8000/api/development-cases/case%2Fid%20with%20spaces",
    );
  });

  it("forwards bounded PATCH and transition payloads", async () => {
    fetchMock
      .mockResolvedValueOnce(Response.json({ id: "case-1", title: "Updated" }))
      .mockResolvedValueOnce(Response.json({ id: "case-1", status: "evaluating" }));

    const patchBody = { title: "Updated" };
    const patch = await PATCH(
      request("/api/development-cases/case-1", JSON.stringify(patchBody), "PATCH"),
      context,
    );
    const transitionBody = { to_status: "evaluating" };
    const transition = await TRANSITION(
      request(
        "/api/development-cases/case-1/transitions",
        JSON.stringify(transitionBody),
        "POST",
      ),
      context,
    );

    expect(patch.status).toBe(200);
    expect(transition.status).toBe(200);
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({ method: "PATCH", body: JSON.stringify(patchBody) }),
    );
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(
      expect.objectContaining({ method: "POST", body: JSON.stringify(transitionBody) }),
    );
  });

  it("rejects invalid JSON before contacting the API", async () => {
    const response = await PATCH(
      request("/api/development-cases/case-1", "not-json", "PATCH"),
      context,
    );

    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
