import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AgentRunProgressPanel } from "./agent-run-progress";

const fetcher = vi.fn<typeof fetch>();
const value = {
  run_id: "run", status: "succeeded", phase: "completed", as_of: "2026-09-11T00:00:00Z", stop_code: null,
  saved_tool_steps: 1, tool_dispatches: 2, observations: 3, model_receipts: 2, saved_results: 1, last_tool: "get_recent_events",
  budget: { lineage_id: "lineage", token_limit: 200, charged_tokens: 60, held_tokens: 80, remaining_tokens: 60,
    unresolved_calls: 1, active_seconds: 1.5, active_limit_seconds: 60, remaining_active_seconds: 58.5,
    absolute_deadline: "2026-09-12T00:00:00Z", priced_model_cost_microusd: 1200, model_cost_complete: false },
};
function open() {
  const details = screen.getByText("查看运行详情").closest("details")!;
  details.open = true;
  fireEvent(details, new Event("toggle"));
}
beforeEach(() => { fetcher.mockReset(); vi.stubGlobal("fetch", fetcher); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });

it("loads only when expanded and shows held cumulative usage and incomplete cost", async () => {
  fetcher.mockResolvedValue(Response.json(value));
  render(<AgentRunProgressPanel projectId="project" runId="run" />);
  expect(fetcher).not.toHaveBeenCalled();
  open();
  expect(await screen.findByText("本次运行已完成")).toBeInTheDocument();
  expect(screen.getByText(/已计入 60 · 预留 80 · 剩余 60/)).toBeInTheDocument();
  expect(screen.getByText(/费用记录尚不完整/)).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledWith("/api/ai/projects/project/runs/run", expect.objectContaining({ cache: "no-store" }));
});

it("keeps legacy unknown usage explicit", async () => {
  fetcher.mockResolvedValue(Response.json({ ...value, budget: null }));
  render(<AgentRunProgressPanel projectId="project" runId="run" />);
  open();
  expect(await screen.findByText("本次运行没有完整预算记录，历史用量未知。")).toBeInTheDocument();
  expect(screen.queryByText(/模型已知费用/)).not.toBeInTheDocument();
});

it("retains a previous snapshot after an error and permits a fresh lookup", async () => {
  fetcher.mockResolvedValueOnce(Response.json(value)).mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce(Response.json({ ...value, status: "cancelled", phase: "cancelled", stop_code: "EVENT_RUN_CANCELLED" }));
  render(<AgentRunProgressPanel projectId="project" runId="run" />);
  open();
  await screen.findByText("本次运行已完成");
  fireEvent.click(screen.getByRole("button", { name: "重新查询" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("以下为上次查询记录");
  fireEvent.click(screen.getByRole("button", { name: "重新查询" }));
  expect(await screen.findByText("本次运行已取消")).toBeInTheDocument();
});

it("refreshes active runs and stops polling after completion", async () => {
  vi.useFakeTimers();
  fetcher.mockResolvedValueOnce(Response.json({ ...value, status: "running", phase: "model" }))
    .mockResolvedValueOnce(Response.json(value));
  render(<AgentRunProgressPanel projectId="project" runId="run" />);
  await act(async () => { open(); });
  expect(screen.getByText("等待模型返回")).toBeInTheDocument();
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(screen.getByText("本次运行已完成")).toBeInTheDocument();
  await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
  expect(fetcher).toHaveBeenCalledTimes(2);
});
