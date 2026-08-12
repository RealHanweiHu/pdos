import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: getCookie }),
}));

import { GET as GET_DOCUMENTS, POST as POST_DOCUMENT } from "./documents/route";
import { GET as GET_GATES } from "./gates/route";

const context = { params: Promise.resolve({ projectId: "project/id with spaces" }) };

describe("Gate and document BFF routes", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
  });

  it("encodes project scope and forwards only bearer auth", async () => {
    fetchMock.mockImplementation(async () => Response.json({ items: [] }));
    await GET_GATES(new Request("http://localhost"), context);
    await GET_DOCUMENTS(new Request("http://localhost"), context);
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual([
      "http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/gates",
      "http://127.0.0.1:8000/api/ai/projects/project%2Fid%20with%20spaces/documents",
    ]);
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(expect.objectContaining({
      headers: expect.objectContaining({ Authorization: "Bearer signed.jwt.value" }),
    }));
  });

  it("fails closed without session and rejects non-multipart upload", async () => {
    getCookie.mockReturnValue(undefined);
    expect((await GET_GATES(new Request("http://localhost"), context)).status).toBe(401);
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    const invalid = new Request("http://localhost", { method: "POST", body: "plain" });
    expect((await POST_DOCUMENT(invalid)).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
