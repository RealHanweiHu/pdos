import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: getCookie }),
}));

import { GET as GET_ISSUES, POST as POST_ISSUE } from "./issues/route";
import { GET as GET_RISK, PATCH as PATCH_RISK } from "./risks/[riskId]/route";
import { POST as TRANSITION_RISK } from "./risks/[riskId]/transitions/route";
import { GET as GET_TASKS, POST as POST_TASK } from "./tasks/route";
import { GET as GET_TASK, PATCH as PATCH_TASK } from "./tasks/[taskId]/route";
import { POST as TRANSITION_TASK } from "./tasks/[taskId]/transitions/route";

const projectContext = { params: Promise.resolve({ projectId: "project/id with spaces" }) };
const taskContext = {
  params: Promise.resolve({
    projectId: "project/id with spaces",
    taskId: "task/id with spaces",
  }),
};
const riskContext = {
  params: Promise.resolve({
    projectId: "project/id with spaces",
    riskId: "risk/id with spaces",
  }),
};

function request(path: string, body: object, method: "PATCH" | "POST") {
  return new Request(`http://localhost${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("project work-item BFF routes", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
  });

  it("encodes Task scope and forwards every Task method with bearer auth", async () => {
    fetchMock.mockImplementation(async () => Response.json({ id: "task-1" }));
    const createBody = { title: "Freeze requirements" };
    const patchBody = { priority: "high" };
    const transitionBody = { to_status: "in_progress" };

    await GET_TASKS(new Request("http://localhost"), projectContext);
    await POST_TASK(request("/tasks", createBody, "POST"), projectContext);
    await GET_TASK(new Request("http://localhost"), taskContext);
    await PATCH_TASK(request("/tasks/task-1", patchBody, "PATCH"), taskContext);
    await TRANSITION_TASK(
      request("/tasks/task-1/transitions", transitionBody, "POST"),
      taskContext,
    );

    expect(fetchMock.mock.calls.map((call) => String(call[0]))).toEqual([
      "http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/tasks",
      "http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/tasks",
      "http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/tasks/task%2Fid%20with%20spaces",
      "http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/tasks/task%2Fid%20with%20spaces",
      "http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/tasks/task%2Fid%20with%20spaces/transitions",
    ]);
    expect(fetchMock.mock.calls.map((call) => call[1])).toEqual([
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer signed.jwt.value" }),
      }),
      expect.objectContaining({ method: "POST", body: JSON.stringify(createBody) }),
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer signed.jwt.value" }),
      }),
      expect.objectContaining({ method: "PATCH", body: JSON.stringify(patchBody) }),
      expect.objectContaining({ method: "POST", body: JSON.stringify(transitionBody) }),
    ]);
  });

  it("routes Issue and Risk collections through the same guarded boundary", async () => {
    fetchMock.mockImplementation(async () => Response.json({ items: [] }));

    await GET_ISSUES(new Request("http://localhost"), projectContext);
    await POST_ISSUE(request("/issues", { title: "Thermal issue" }, "POST"), projectContext);
    await GET_RISK(new Request("http://localhost"), riskContext);
    await PATCH_RISK(request("/risks/risk-1", { likelihood: 4 }, "PATCH"), riskContext);
    await TRANSITION_RISK(
      request("/risks/risk-1/transitions", { to_status: "mitigating" }, "POST"),
      riskContext,
    );

    expect(fetchMock.mock.calls.map((call) => String(call[0]))).toEqual([
      "http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/issues",
      "http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/issues",
      "http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/risks/risk%2Fid%20with%20spaces",
      "http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/risks/risk%2Fid%20with%20spaces",
      "http://127.0.0.1:8000/api/projects/project%2Fid%20with%20spaces/risks/risk%2Fid%20with%20spaces/transitions",
    ]);
  });

  it("fails closed without a session and rejects non-JSON bodies before fetch", async () => {
    getCookie.mockReturnValue(undefined);
    expect((await GET_TASKS(new Request("http://localhost"), projectContext)).status).toBe(401);

    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    const invalid = new Request("http://localhost/api/projects/project-1/tasks", {
      method: "POST",
      body: "not-json",
    });
    expect((await POST_TASK(invalid, projectContext)).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
