import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectNpiPanel } from "./project-npi-panel";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

vi.mock("./build-materials", () => ({
  BuildMaterials: ({ canEdit }: { canEdit: boolean }) => <p>{`build-materials-edit:${canEdit}`}</p>,
}));

const projectId = "88888888-8888-4888-8888-888888888888";
const buildId = "99999999-9999-4999-8999-999999999999";
const sampleId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const planId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const caseId = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";

function snapshot(overrides: Record<string, unknown> = {}) {
  return {
    builds: [
      {
        id: buildId,
        code: "BB-EVT-1",
        phase: "evt",
        status: "planned",
        planned_quantity: 3,
      },
    ],
    samples: [
      {
        id: sampleId,
        build_batch_id: buildId,
        serial_number: "SN-1001",
        status: "built",
      },
    ],
    sample_signoffs: [],
    test_plans: [{ id: planId, title: "EVT 测试计划", phase: "evt", status: "active" }],
    test_cases: [
      { id: caseId, plan_id: planId, title: "气压保持测试", status: "planned" },
    ],
    test_reports: [],
    certifications: [],
    certification_alerts: [],
    ...overrides,
  };
}

describe("ProjectNpiPanel", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState({}, "", "/projects");
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(cleanup);

  it("shows builds, their samples and test cases", async () => {
    fetchMock.mockImplementation(async () => Response.json(snapshot()));

    render(<ProjectNpiPanel canEdit projectId={projectId} />);

    expect(await screen.findByText("BB-EVT-1")).toBeTruthy();
    expect(screen.getByText("EVT 测试计划")).toBeTruthy();
    expect(screen.getByText("气压保持测试")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "展开样机" }));
    expect(within(screen.getByText("BB-EVT-1").closest("li")!).getByText("SN-1001")).toBeTruthy();
  });

  it("starting a build sends the exact payload the backend forbids extras on", async () => {
    fetchMock.mockImplementation(async () => Response.json(snapshot()));
    render(<ProjectNpiPanel canEdit projectId={projectId} />);
    await screen.findByText("BB-EVT-1");

    fireEvent.click(screen.getByRole("button", { name: "开始试制" }));

    await waitFor(() => {
      const write = fetchMock.mock.calls.find((call) => call[1]?.method === "PATCH");
      expect(write).toBeTruthy();
      expect(String(write?.[0])).toBe(`/api/projects/${projectId}/npi/builds/${buildId}`);
      expect(JSON.parse(String(write?.[1]?.body))).toEqual({
        status: "in_progress",
        completed_quantity: 0,
      });
    });
  });

  it("records a failed test run with its actual time and unknown configuration basis", async () => {
    fetchMock.mockImplementation(async (input) => Response.json(String(input).endsWith("/npi") ? snapshot() : { items: [] }));
    render(<ProjectNpiPanel canEdit projectId={projectId} />);
    await screen.findByText("气压保持测试");
    fireEvent.click(screen.getByText("逐次测试与证据"));
    await screen.findByText("尚无逐次测试记录。");
    fireEvent.click(screen.getByRole("button", { name: "新增一次测试" }));
    fireEvent.change(screen.getByLabelText("结果"), { target: { value: "failed" } });
    expect(screen.getByRole("button", { name: "保存测试记录" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("实际测试完成日期"), { target: { value: "2026-09-10" } });
    fireEvent.change(screen.getByLabelText("测试时间及配置选择依据"), { target: { value: "原试验日志注明测试日期，当次配置未保存。" } });
    fireEvent.change(screen.getByLabelText("结果说明"), { target: { value: "压力保持失败" } });
    fireEvent.click(screen.getByRole("button", { name: "保存测试记录" }));
    await waitFor(() => {
      const write = fetchMock.mock.calls.find((call) => call[1]?.method === "POST");
      expect(String(write?.[0])).toBe(`/api/projects/${projectId}/npi/test-cases/${caseId}/runs`);
      expect(JSON.parse(String(write?.[1]?.body))).toEqual({
        status: "failed", executed_at: "2026-09-10T00:00:00Z", execution_time_precision: "day",
        execution_time_reason: "原试验日志注明测试日期，当次配置未保存。", result_notes: "压力保持失败",
        evidence_document_id: null, metrics: [], configuration_mode: "unknown", configuration_revision_id: null,
        configuration_reason: "原试验日志注明测试日期，当次配置未保存。", sample_id: null,
        equipment: null, environment: null, conditions: {}, expected_completion_at: null,
      });
    });
  });

  it("a read-only role sees the data but no write actions", async () => {
    fetchMock.mockImplementation(async () => Response.json(snapshot()));

    render(<ProjectNpiPanel canEdit={false} projectId={projectId} />);
    await screen.findByText("BB-EVT-1");

    expect(screen.queryByRole("button", { name: "开始试制" })).toBeNull();
    expect(screen.queryByRole("button", { name: "判定通过" })).toBeNull();
    // Reading is still possible.
    expect(screen.getByRole("button", { name: "展开样机" })).toBeTruthy();
  });

  it("gives build materials the product-engineering edit right, not project edit", async () => {
    fetchMock.mockImplementation(async () => Response.json(snapshot()));

    // An engineer: no project edit, but may freeze demand, allocate and register movements.
    render(<ProjectNpiPanel canEdit={false} canEditMaterials projectId={projectId} />);
    await screen.findByText("BB-EVT-1");
    fireEvent.click(screen.getByRole("button", { name: "展开样机" }));

    expect(await screen.findByText("build-materials-edit:true")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "开始试制" })).toBeNull();
  });

  it("surfaces a backend refusal instead of failing silently", async () => {
    fetchMock.mockImplementation(async () =>
      Response.json(
        { detail: { code: "PROJECT_ACCESS_DENIED", message: "Project access denied" } },
        { status: 403 },
      ),
    );

    render(<ProjectNpiPanel canEdit projectId={projectId} />);

    expect(await screen.findByText("Project access denied")).toBeTruthy();
    expect(screen.getByRole("button", { name: "重试" })).toBeTruthy();
  });

  it("tolerates a role-narrowed snapshot that omits collections", async () => {
    // Suppliers and customers get sign-offs only; missing keys must not crash.
    fetchMock.mockImplementation(async () =>
      Response.json({ sample_signoffs: [] }),
    );

    render(<ProjectNpiPanel canEdit={false} projectId={projectId} />);

    expect(await screen.findByText("尚无试制批次。")).toBeTruthy();
    expect(screen.getByText("尚无测试计划。")).toBeTruthy();
  });
});
