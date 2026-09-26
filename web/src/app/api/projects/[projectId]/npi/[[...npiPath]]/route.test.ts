// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: getCookie }),
}));

import { GET, PATCH, POST, PUT } from "./route";

const projectId = "55555555-5555-4555-8555-555555555555";
const id = "66666666-6666-4666-8666-666666666666";
const runId = "77777777-7777-4777-8777-777777777777";

function context(npiPath: string[]) {
  return { params: Promise.resolve({ projectId, npiPath }) };
}

function json(body: object) {
  return new Request("http://localhost", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("NPI BFF", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    delete process.env.PDOS_AI_TEST_PLAN_ASYNC;
    vi.stubGlobal("fetch", fetchMock);
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
    fetchMock.mockImplementation(async () => Response.json({ ok: true }));
  });

  it("forwards the whole execution surface with server-side bearer auth", async () => {
    await GET(new Request("http://localhost/api/x"), context([]));
    await POST(json({ code: "BB-1" }), context(["builds"]));
    await PATCH(json({ status: "in_progress" }), context(["builds", id]));
    await POST(json({}), context(["builds", id, "samples"]));
    await PUT(json({}), context(["samples", id, "build-configuration"]));
    await POST(json({}), context(["test-cases", id, "runs", runId, "complete"]));

    expect(fetchMock.mock.calls.map((call) => String(call[0]))).toEqual([
      `http://127.0.0.1:8000/api/projects/${projectId}/npi`,
      `http://127.0.0.1:8000/api/projects/${projectId}/npi/builds`,
      `http://127.0.0.1:8000/api/projects/${projectId}/npi/builds/${id}`,
      `http://127.0.0.1:8000/api/projects/${projectId}/npi/builds/${id}/samples`,
      `http://127.0.0.1:8000/api/projects/${projectId}/npi/samples/${id}/build-configuration`,
      `http://127.0.0.1:8000/api/projects/${projectId}/npi/test-cases/${id}/runs/${runId}/complete`,
    ]);
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Authorization: "Bearer signed.jwt.value" }),
      }),
    );
  });

  it("keeps the query string on reads", async () => {
    await GET(
      new Request("http://localhost/api/x?phase=evt"),
      context(["sample-configurations"]),
    );
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      `http://127.0.0.1:8000/api/projects/${projectId}/npi/sample-configurations?phase=evt`,
    );
  });

  it("forwards Excel bytes as multipart with only the file and plan", async () => {
    const form = new FormData();
    form.set("plan_id", id);
    form.set("file", new File([new Uint8Array([80, 75, 3, 4, 255])], "整机.xlsx"));
    form.set("tenant_id", "untrusted");
    const response = await POST(new Request("http://localhost", { method: "POST", body: form }), context(["test-imports"]));
    expect(response.status).toBe(200);
    const init = fetchMock.mock.calls[0][1]!;
    expect(init.headers).toEqual(expect.objectContaining({ Authorization: "Bearer signed.jwt.value" }));
    expect(new Headers(init.headers).has("content-type")).toBe(false);
    const sent = init.body as FormData;
    expect([...sent.keys()]).toEqual(["plan_id", "file"]);
    expect(sent.get("plan_id")).toBe(id);
    expect(new Uint8Array(await (sent.get("file") as File).arrayBuffer())).toEqual(new Uint8Array([80, 75, 3, 4, 255]));
  });

  it("rejects oversized or invalid uploads without calling upstream", async () => {
    expect((await POST(new Request("http://localhost", {
      method: "POST", headers: { "Content-Type": "multipart/form-data; boundary=x", "Content-Length": String(22 * 1024 * 1024) }, body: "x",
    }), context(["test-imports"]))).status).toBe(413);
    expect((await POST(json({ plan_id: id }), context(["test-imports"]))).status).toBe(400);
    const form = new FormData();
    form.set("plan_id", "not-a-uuid");
    form.set("file", new File(["x"], "report.xlsx"));
    expect((await POST(new Request("http://localhost", { method: "POST", body: form }), context(["test-imports"]))).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("enforces the method as well as the shape", async () => {
    // `builds` accepts POST but not GET; `sample-configurations` the reverse.
    expect((await GET(new Request("http://localhost"), context(["builds"]))).status).toBe(404);
    expect((await POST(json({}), context(["sample-configurations"]))).status).toBe(404);
    // A non-uuid where an id belongs must not reach the backend.
    expect((await PATCH(json({}), context(["builds", "not-a-uuid"]))).status).toBe(404);
    expect((await POST(json({}), context(["builds", id, "delete-everything"]))).status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fails closed without a session and on malformed JSON", async () => {
    getCookie.mockReturnValue(undefined);
    expect((await GET(new Request("http://localhost"), context([]))).status).toBe(401);

    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    const invalid = new Request("http://localhost", { method: "POST", body: "x" });
    expect((await POST(invalid, context(["builds"]))).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it("routes configured suggestions to the queue and forwards status lookup", async () => {
    process.env.PDOS_AI_TEST_PLAN_ASYNC = "true";
    try {
      await POST(json({ message: "补充条件", request_id: runId }), context(["test-plans", id, "suggestions"]));
      expect(String(fetchMock.mock.calls[0][0])).toContain(`/test-plans/${id}/suggestion-requests`);
      await GET(new Request("http://localhost/api/x"), context(["test-plans", id, "suggestion-requests", runId]));
      expect(String(fetchMock.mock.calls[1][0])).toContain(`/suggestion-requests/${runId}`);
    } finally { delete process.env.PDOS_AI_TEST_PLAN_ASYNC; }
  });


it("routes configured Excel uploads and status queries to the report queue", async () => {
  process.env.PDOS_AI_REPORT_IMPORT_ASYNC = "true";
  try {
    const form = new FormData();
    form.set("plan_id", id);
    form.set("file", new File(["xlsx"], "report.xlsx"));
    await POST(new Request("http://localhost", { method: "POST", body: form }), context(["test-imports"]));
    expect(String(fetchMock.mock.calls[0][0])).toContain("/npi/test-import-requests");
    expect((fetchMock.mock.calls[0][1]!.body as FormData).get("plan_id")).toBe(id);
    await GET(new Request("http://localhost"), context(["test-import-requests", runId]));
    expect(String(fetchMock.mock.calls[1][0])).toContain(`/test-import-requests/${runId}`);
  } finally { delete process.env.PDOS_AI_REPORT_IMPORT_ASYNC; }
});

});
