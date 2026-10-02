import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AiIssueAttention } from "./ai-issue-attention";
vi.mock("./ai-issue-event-runs", () => ({ AiIssueEventRuns: ({ initialRunId, onIssueChanged }: { initialRunId: string; onIssueChanged: (ids: string[]) => Promise<void> }) => <button onClick={() => void onIssueChanged([])}>办理原运行 {initialRunId}</button> }));
const item = { run_id: "run-1", event_row_id: 31, source_title: "密封测试失败", status: "succeeded", sources_current: true, write_execution: { reason_label: "待具名确认" } };
function page(items = [item], next: string | null = null) { return { items, next_before_id: next }; }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
describe("Issue attention queue", () => {
  it("opens the exact original run and refreshes after handling", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(page())).mockResolvedValueOnce(Response.json(page([])));
    vi.stubGlobal("fetch", fetcher); render(<AiIssueAttention projectId="project" />);
    expect(fetcher).not.toHaveBeenCalled(); fireEvent.click(screen.getByText("需要核对的 AI 异常"));
    expect(await screen.findByText("待具名确认")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "查看与办理" }));
    fireEvent.click(screen.getByRole("button", { name: "办理原运行 run-1" }));
    expect(await screen.findByText(/当前没有需要核对的运行记录/)).toBeVisible();
    expect(screen.queryByText("待具名确认")).not.toBeInTheDocument();
    expect(fetcher.mock.calls[0][0]).toBe("/api/projects/project/ai-issue-event-runs?attention=true");
  });
  it("clears cached rows and selected actions when pagination discovers revoked access", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(page([item], "cursor"))).mockResolvedValueOnce(Response.json({ detail: { message: "当前无权读取" } }, { status: 403 }));
    vi.stubGlobal("fetch", fetcher); render(<AiIssueAttention projectId="project" />); fireEvent.click(screen.getByText("需要核对的 AI 异常"));
    fireEvent.click(await screen.findByRole("button", { name: "查看与办理" }));
    fireEvent.click(screen.getByRole("button", { name: "更早的待核对记录" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("当前无权读取");
    expect(screen.queryByRole("button", { name: "办理原运行 run-1" })).not.toBeInTheDocument();
    expect(screen.queryByText("待具名确认")).not.toBeInTheDocument();
  });
  it("does not display malformed records as a successful empty queue", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ items: [{ ...item, event_row_id: 0 }], next_before_id: null }));
    vi.stubGlobal("fetch", fetcher); render(<AiIssueAttention projectId="project" />); fireEvent.click(screen.getByText("需要核对的 AI 异常"));
    expect(await screen.findByRole("alert")).toHaveTextContent("例外记录不完整");
    expect(screen.queryByText(/当前没有需要核对的运行记录/)).not.toBeInTheDocument();
  });
});
