import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ScheduleForecastPanel } from "./schedule-forecast-panel";
import { ScheduleActualCorrections } from "./schedule-actual-corrections";
import { ProjectSourceActualCorrections } from "./project-source-actual-corrections";

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams() }));
vi.mock("@/components/cases/plan-capacity", () => ({ PlanCapacity: () => <p>容量核对入口</p> }));

const project = "project-a";
const forecast = {
  record_id: "record-1", version: 1, previous_record_id: null, previous_version: null,
  created_at: "2026-09-30T09:00:00Z", basis_is_current: false, reason: "资源调整反馈", changes: null,
  inputs: { trigger: "automatic", estimates: {}, estimate_source_record_id: "human-record",
    basis: { resource_basis: { applications: [{ application_id: "application", allocation_id: "allocation", created_at: "2026-09-30T08:00:00Z" }] } } },
  result: { as_of: "2026-09-30T09:00:00Z", complete: false, project_finish: null,
    float_status: "resource_window_not_rechecked", unmapped_material_conditions: [{ node_id: "missing-node", binding_id: "binding", binding_version: 1, issue_id: "issue", status: "waiting" }],
    nodes: [{ node_key: "A", start: null, finish: null, origin: "business_expected_completion",
      expected_completion_at: "2026-10-07T09:00:00Z", unknown_reasons: ["剩余资源输入需核对"], warnings: [],
      resource_conditions: [{ reservation_id: "reservation", resource_name: "真实台架", window_start: "2026-10-07T09:00:00Z", window_end: "2026-10-08T09:00:00Z", blockers: [] }] }] },
};
const page = (items = [forecast]) => ({ basis_digest: "basis", tasks: [{ node_key: "A", node_id: "node", task_id: "task", title: "长期测试", assignee_user_id: "owner", status: "in_progress", actual_start: "2026-09-29T09:00:00Z", actual_finish: null }], items, has_more: false, next_before: null, page_size: 10, errors: [], error_corrections: [], can_recalculate: true });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("shows reservation and estimate provenance and preserves unmapped material impacts", async () => {
  vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(Response.json(page())));
  render(<ScheduleForecastPanel projectId={project} />);
  fireEvent.click(screen.getByRole("button", { name: "估计剩余工作与查看预测" }));
  expect(await screen.findByText(/依据已有变化/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "回查估计原版本" })).toHaveAttribute("href", expect.stringContaining("human-record"));
  expect(screen.getByRole("link", { name: "真实台架 · 正式预约" })).toHaveAttribute("href", expect.stringContaining("reservation"));
  expect(screen.getByText(/原节点 missing-node/)).toHaveTextContent("待明确重新绑定或解除");
  expect(screen.getByRole("link", { name: "原物料问题" })).toHaveAttribute("href", expect.stringContaining("issue"));
  expect(screen.getByText("在途测试预计完成（尚未实际结束）")).toBeInTheDocument();
});

it("refreshes after feedback and removes cached inputs when current access cannot be read", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(page()))
    .mockResolvedValueOnce(Response.json(page([{ ...forecast, record_id: "record-2", version: 2 }])))
    .mockResolvedValueOnce(Response.json({ detail: { message: "无权读取" } }, { status: 403 }));
  vi.stubGlobal("fetch", fetcher);
  render(<ScheduleForecastPanel projectId={project} />);
  fireEvent.click(screen.getByRole("button", { name: "估计剩余工作与查看预测" }));
  await screen.findByText(/预测 v1 ·/);
  fireEvent(window, new Event("pdos:forecast-updated"));
  await screen.findByText(/预测 v2 ·/);
  fireEvent(window, new Event("pdos:forecast-updated"));
  await screen.findByText("自动更新暂时中断，请刷新后核对当前来源和权限。");
  expect(screen.queryByText(/预测 v2 ·/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "保存新的预测版本" })).not.toBeInTheDocument();
});

it("preserves a saved forecast receipt when the following history read fails", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(page()))
    .mockResolvedValueOnce(Response.json({ record_id: "saved" }))
    .mockResolvedValueOnce(Response.json({ detail: { message: "历史刷新失败" } }, { status: 503 }));
  vi.stubGlobal("fetch", fetcher);
  render(<ScheduleForecastPanel projectId={project} />);
  fireEvent.click(screen.getByRole("button", { name: "估计剩余工作与查看预测" }));
  const reason = await screen.findByLabelText("本次重算说明");
  fireEvent.change(reason, { target: { value: "核对当前剩余工作" } });
  fireEvent.click(screen.getByRole("button", { name: "保存新的预测版本" }));
  await screen.findByText("历史刷新失败");
  expect(screen.getByText("新的预测版本已保存。")).toHaveAttribute("role", "status");
});

it("retries correction with its original request and signals only a confirmed saved correction", async () => {
  const point = { id: "point", task_id: "task", point: "start", title: "任务", observed_at: "2026-09-29T09:00:00Z", original_observed_at: "2026-09-29T09:00:00Z", original_event_row_id: 11, event_row_id: 11, correction_version: 0, digest: "current", can_correct: true };
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ points: [point], items: [], has_more: false }))
    .mockResolvedValueOnce(Response.json({ detail: { message: "响应未确认" } }, { status: 503 }))
    .mockResolvedValueOnce(Response.json({ id: "correction" }))
    .mockResolvedValueOnce(Response.json({ detail: { message: "纠错历史刷新失败" } }, { status: 503 }));
  vi.stubGlobal("fetch", fetcher);
  const listener = vi.fn(); window.addEventListener("pdos:forecast-updated", listener);
  try {
    render(<ScheduleActualCorrections projectId={project} onCorrected={() => {}} />);
    const selection = await screen.findByLabelText("更正哪项记录");
    fireEvent.change(selection, { target: { value: "point" } });
    fireEvent.change(screen.getByLabelText("更正后的时间"), { target: { value: "2026-09-29T01:30:00" } });
    fireEvent.change(screen.getByLabelText("纠错原因"), { target: { value: "核对现场记录" } });
    fireEvent.change(screen.getByLabelText("核对依据"), { target: { value: "交接记录" } });
    fireEvent.click(screen.getByRole("button", { name: "保存纠错并更新预测" }));
    await screen.findByText("响应未确认");
    expect(listener).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "保存纠错并更新预测" }));
    await screen.findByText("纠错历史刷新失败");
    await waitFor(() => expect(listener).toHaveBeenCalledTimes(1));
    expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body))).toEqual(JSON.parse(String(fetcher.mock.calls[2][1]?.body)));
    expect(screen.getByRole("status")).toHaveTextContent("纠错已保存");
  } finally { window.removeEventListener("pdos:forecast-updated", listener); }
});

it("retains the business-correction receipt and refresh signal when history cannot be read", async () => {
  const item = { node_id: "test-node", node_kind: "test_run", title: "长期测试", expected_digest: "current", can_correct: true,
    actual: { id: "observation", version: 1, started_at: "2026-09-29T09:00:00.123Z", finished_at: null } };
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [item], history: [], has_more: false }))
    .mockResolvedValueOnce(Response.json({ id: "correction" }))
    .mockResolvedValueOnce(Response.json({ detail: { message: "业务观察历史不可读取" } }, { status: 403 }));
  vi.stubGlobal("fetch", fetcher);
  const changed = vi.fn(); const listener = vi.fn(); window.addEventListener("pdos:forecast-updated", listener);
  try {
    render(<ProjectSourceActualCorrections projectId={project} onChanged={changed} />);
    fireEvent.click(screen.getByRole("button", { name: "更正业务实际时间" }));
    await screen.findByText(/长期测试 · 观察 v1/);
    fireEvent.change(screen.getByLabelText("更正原因"), { target: { value: "核对长期测试开始" } });
    fireEvent.change(screen.getByLabelText("实际时间依据"), { target: { value: "现场原始记录" } });
    fireEvent.click(screen.getByRole("button", { name: "保存更正与依据" }));
    await screen.findByText("业务观察历史不可读取");
    expect(screen.getByRole("status")).toHaveTextContent("更正及依据已追加");
    expect(screen.queryByRole("button", { name: "保存更正与依据" })).not.toBeInTheDocument();
    expect(changed).toHaveBeenCalledTimes(1); expect(listener).toHaveBeenCalledTimes(1);
    expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body)).started_at).toBe(item.actual.started_at);
  } finally { window.removeEventListener("pdos:forecast-updated", listener); }
});
