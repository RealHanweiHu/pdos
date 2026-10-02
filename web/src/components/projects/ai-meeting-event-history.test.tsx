import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AiMeetingEventHistory } from "./ai-meeting-event-history";

const base = "/api/projects/project/meetings/meeting";
function entry(id = "first", overrides: object = {}) {
  return { id, created_at: "2026-09-27T10:00:01Z", event_at: "2026-09-27T10:00:00Z", event_action: "status_completed", operation_key: "meeting.minutes.draft", status: "queued", reason: "已进入生成队列", transcript_id: "transcript", run: { id: "run-original", status: "succeeded", error: null }, ...overrides };
}
function open() { fireEvent.click(screen.getByText("会后 AI 触发历史")); }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("meeting event history", () => {
  it("loads only when opened and separates original trigger from current run, with precise source and draft entry", async () => {
    const onOpenDrafts = vi.fn();
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [entry()], next_before: null })).mockResolvedValueOnce(Response.json({ content: "这次转写的原始发言" }));
    vi.stubGlobal("fetch", fetcher);
    render(<AiMeetingEventHistory projectId="project" meetingId="meeting" onOpenDrafts={onOpenDrafts} />);
    expect(fetcher).not.toHaveBeenCalled();
    open();
    expect(await screen.findByText("当时触发结果：已排队")).toBeVisible();
    expect(screen.getByText("当前运行：运行完成")).toBeVisible();
    expect(fetcher.mock.calls[0][0]).toBe(`${base}/ai-event-history`);
    fireEvent.click(screen.getByText("查看本次转写原文"));
    expect(await screen.findByText("这次转写的原始发言")).toBeVisible();
    expect(fetcher.mock.calls[1][0]).toBe(`${base}/transcripts/transcript`);
    fireEvent.click(screen.getByRole("button", { name: "查看对应纪要草稿" }));
    expect(onOpenDrafts).toHaveBeenCalledWith("minutes");
    expect(screen.queryByText("run-original")).not.toBeInTheDocument();
  });

  it("preserves skipped and reused histories with cursor pagination and readable failures", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [entry("skip", { status: "skipped", reason: "当前为观察模式，未自动生成", run: null, transcript_id: null })], next_before: "skip" })).mockResolvedValueOnce(Response.json({ items: [entry("reuse", { status: "reused", operation_key: "meeting.actions.draft", reason: "复用相同原文的已有运行", run: { id: "run", status: "failed", error: "NEW_PROVIDER_ERROR" } })], next_before: null }));
    vi.stubGlobal("fetch", fetcher);
    render(<AiMeetingEventHistory projectId="project" meetingId="meeting" onOpenDrafts={vi.fn()} />); open();
    expect(await screen.findByText("当前为观察模式，未自动生成")).toHaveClass("text-primary");
    expect(screen.queryByRole("button", { name: /查看对应/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "更早的触发记录" }));
    expect(await screen.findByText("当时触发结果：复用已有运行")).toBeVisible();
    expect(screen.getByText("当时触发结果：本次未触发")).toBeVisible();
    expect(screen.getByText("当前运行：运行失败")).toBeVisible();
    expect(screen.getByText("本次生成未能完成，请核对运行配置与原始资料。")).toBeVisible();
    expect(screen.getByText("NEW_PROVIDER_ERROR")).not.toBeVisible();
    expect(fetcher.mock.calls[1][0]).toBe(`${base}/ai-event-history?before=skip`);
  });

  it("ignores old responses after changing meetings", async () => {
    let resolve!: (value: Response) => void;
    const fetcher = vi.fn<typeof fetch>().mockImplementationOnce(() => new Promise(done => { resolve = done; })).mockResolvedValueOnce(Response.json({ items: [], next_before: null }));
    vi.stubGlobal("fetch", fetcher);
    const view = render(<AiMeetingEventHistory projectId="project" meetingId="meeting" onOpenDrafts={vi.fn()} />); open();
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    view.rerender(<AiMeetingEventHistory projectId="project" meetingId="other" onOpenDrafts={vi.fn()} />); open();
    expect(await screen.findByText(/暂无会后触发记录/)).toBeVisible();
    await act(async () => resolve(Response.json({ items: [entry()], next_before: null })));
    expect(screen.queryByText("当时触发结果：已排队")).not.toBeInTheDocument();
    expect(fetcher.mock.calls[1][0]).toBe("/api/projects/project/meetings/other/ai-event-history");
  });

  it("allows retry after a read failure and shows an empty history", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ detail: { message: "当前暂不可读取" } }, { status: 503 })).mockResolvedValueOnce(Response.json({ items: [], next_before: null }));
    vi.stubGlobal("fetch", fetcher);
    render(<AiMeetingEventHistory projectId="project" meetingId="meeting" onOpenDrafts={vi.fn()} />); open();
    expect(await screen.findByRole("alert")).toHaveTextContent("当前暂不可读取");
    fireEvent.click(screen.getByRole("button", { name: "刷新触发历史" }));
    expect(await screen.findByText("暂无会后触发记录。")).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
