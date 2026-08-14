import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: getCookie }),
}));

import { GET as GET_BOMS, POST as POST_BOM } from "./boms/route";
import { POST as POST_ITEM } from "./boms/[bomId]/items/route";
import { GET as GET_REFERENCES } from "./erp-references/route";
import { GET as GET_SPECIFICATIONS, POST as POST_SPECIFICATION } from "./specifications/route";

const projectContext = { params: Promise.resolve({ projectId: "project/id with spaces" }) };
const bomContext = {
  params: Promise.resolve({
    projectId: "project/id with spaces",
    bomId: "bom/id with spaces",
  }),
};

function postRequest(path: string, body: object) {
  return new Request(`http://localhost${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("product engineering BFF routes", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
  });

  it("encodes scope and forwards register methods with bearer auth", async () => {
    fetchMock.mockImplementation(async () => Response.json({ items: [] }));
    const specificationBody = { code: "SPEC-C4S", title: "C4s specification" };
    const bomBody = { bom_type: "ebom", code: "C4S-EBOM", name: "C4s EBOM" };
    const itemBody = { line_number: 10, part_number: "C4S-HOUSING" };

    await GET_SPECIFICATIONS(new Request("http://localhost"), projectContext);
    await POST_SPECIFICATION(postRequest("/specifications", specificationBody), projectContext);
    await GET_BOMS(new Request("http://localhost"), projectContext);
    await POST_BOM(postRequest("/boms", bomBody), projectContext);
    await POST_ITEM(postRequest("/boms/bom-1/items", itemBody), bomContext);
    await GET_REFERENCES(new Request("http://localhost"), projectContext);

    expect(fetchMock.mock.calls.map((call) => String(call[0]))).toEqual([
      "http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/product-engineering/specifications",
      "http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/product-engineering/specifications",
      "http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/product-engineering/boms",
      "http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/product-engineering/boms",
      "http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/product-engineering/boms/bom%2Fid%20with%20spaces/items",
      "http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/product-engineering/erp-references",
    ]);
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer signed.jwt.value" }),
      }),
    );
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(
      expect.objectContaining({ method: "POST", body: JSON.stringify(specificationBody) }),
    );
    expect(fetchMock.mock.calls[4]?.[1]).toEqual(
      expect.objectContaining({ method: "POST", body: JSON.stringify(itemBody) }),
    );
  });

  it("fails closed without a session and rejects unbounded input before fetch", async () => {
    getCookie.mockReturnValue(undefined);
    expect(
      (await GET_SPECIFICATIONS(new Request("http://localhost"), projectContext)).status,
    ).toBe(401);

    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    const invalid = new Request("http://localhost/api/projects/project-1/product-engineering/boms", {
      method: "POST",
      body: "not-json",
    });
    expect((await POST_BOM(invalid, projectContext)).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
