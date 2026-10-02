// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: getCookie }) }));
import { POST } from "./route";

const projectId = "55555555-5555-4555-8555-555555555555";
const supplierId = "66666666-6666-4666-8666-666666666666";
const recordId = "77777777-7777-4777-8777-777777777777";
const context = (operation = "preview", record = recordId) => ({ params: Promise.resolve({ projectId, supplierId, recordId: record, operation }) });
const json = (body: object) => new Request("http://localhost", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

describe("supplier reply BFF", () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => { vi.clearAllMocks(); vi.stubGlobal("fetch", fetchMock); getCookie.mockReturnValue({ value: "signed.token" }); process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000"; });
  it("forwards only preview and confirm with server-held authentication", async () => {
    fetchMock.mockImplementation(async () => Response.json({ version: 2 }));
    await POST(json({ location: "原件第2页" }), context());
    await POST(json({ expected_version: 1 }), context("confirm"));
    expect(fetchMock.mock.calls.map(call => String(call[0]))).toEqual([
      `http://127.0.0.1:8000/api/projects/${projectId}/npi/supplier-replies/${supplierId}/${recordId}/preview`,
      `http://127.0.0.1:8000/api/projects/${projectId}/npi/supplier-replies/${supplierId}/${recordId}/confirm`,
    ]);
    expect(new Headers(fetchMock.mock.calls[1][1]?.headers).get("Authorization")).toBe("Bearer signed.token");
  });
  it("rejects missing sessions, unknown operations and malformed identifiers before upstream", async () => {
    getCookie.mockReturnValue(undefined);
    expect((await POST(json({}), context())).status).toBe(401);
    getCookie.mockReturnValue({ value: "signed.token" });
    expect((await POST(json({}), context("send"))).status).toBe(400);
    expect((await POST(json({}), context("confirm", "../../other"))).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it("bounds reply bodies and preserves server conflict details", async () => {
    expect((await POST(json({ location: "x".repeat(17000) }), context())).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
    fetchMock.mockResolvedValueOnce(Response.json({ detail: { message: "原件已变化" } }, { status: 409 }));
    const response = await POST(json({}), context("confirm"));
    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({ detail: { message: "原件已变化" } });
  });
});
