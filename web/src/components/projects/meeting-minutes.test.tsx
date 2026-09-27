import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./ai-meeting-drafts", () => ({ AiMeetingDrafts: () => null }));

import { MeetingMinutes } from "./meeting-minutes";

const projectId = "11111111-1111-4111-8111-111111111111";
const meetingId = "22222222-2222-4222-8222-222222222222";
const oldId = "33333333-3333-4333-8333-333333333333";
const latestId = "44444444-4444-4444-8444-444444444444";
const transcriptId = "55555555-5555-4555-8555-555555555555";
const segmentId = "66666666-6666-4666-8666-666666666666";
const base = `/api/projects/${projectId}/meetings/${meetingId}/minutes`;

function item(recordId: string, version: number) {
  return {
    id: recordId, version_no: version, source_finding_id: null,
    body: version === 1 ? "保留的第一版原文" : "第三版的新内容",
    unresolved_points: "验证日期待确认", reason: "具名确认原讨论",
    confirmed_by: "项目负责人", confirmed_at: "2026-09-27T10:00:00Z", source_current: true,
    citations: [{ transcript_id: transcriptId, segment_id: segmentId, source_digest: "a".repeat(64), exact_quote: "样机装配完成", sequence: 1 }],
  };
}

function response(recordId = oldId, version = 1) {
  return {
    current_version: 3, next_before: null, editable: true,
    sources: [{ id: transcriptId, source: "manual", uploaded_at: "2026-09-27T09:00:00Z", segment_count: 1, superseded_at: null }],
    items: [item(recordId, version)],
  };
}

function navigate(minutes: string, meeting = meetingId) {
  window.history.replaceState({}, "", `/projects?project=${projectId}&meeting=${meeting}&minutes=${minutes}`);
}

function mount() {
  return render(<MeetingMinutes projectId={projectId} meetingId={meetingId} canManage isCompleted />);
}

beforeEach(() => { window.history.replaceState({}, "", "/projects"); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("formal minutes deep links", () => {
  it("opens the selected historical record on first render and refreshes the same record", async () => {
    navigate(oldId);
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => Response.json(response()));
    vi.stubGlobal("fetch", fetcher);
    mount();
    expect(await screen.findByText("保留的第一版原文")).toBeVisible();
    expect(screen.getByText("正式纪要与确认版本").closest("details")).toHaveAttribute("open");
    expect(screen.getByText(/第 1 版 · 历史版本/).closest("details")).toHaveAttribute("open");
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0]?.[0]).toBe(`${base}?record_id=${oldId}`);
    expect(screen.queryByRole("button", { name: "基于当前版本修订" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "刷新正式纪要" }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    expect(fetcher.mock.calls[1]?.[0]).toBe(`${base}?record_id=${oldId}`);
    expect(screen.getByRole("link", { name: "查看全部纪要版本" })).toHaveAttribute(
      "href", `/projects?project=${projectId}&tab=decisions&meeting=${meetingId}&minutes=all`,
    );
  });

  it("loads all versions when following the explicit all-versions link", async () => {
    navigate("all");
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json({
      ...response(), items: [item(latestId, 3), item(oldId, 1)],
    }));
    vi.stubGlobal("fetch", fetcher);
    mount();
    expect(await screen.findByText(/第 3 版 · 当前版本/)).toBeVisible();
    expect(screen.getByText(/第 1 版 · 历史版本/)).toBeVisible();
    expect(fetcher.mock.calls[0]?.[0]).toBe(base);
    expect(screen.getByRole("button", { name: "基于当前版本修订" })).toBeEnabled();
    expect(screen.queryByRole("link", { name: "查看全部纪要版本" })).not.toBeInTheDocument();
  });

  it("keeps an unavailable historical record as an error instead of loading the latest", async () => {
    navigate(oldId);
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => Response.json({
      detail: { code: "MEETING_NOT_FOUND", message: "指定纪要不可用" },
    }, { status: 404 }));
    vi.stubGlobal("fetch", fetcher);
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent("指定纪要不可用");
    fireEvent.click(screen.getByRole("button", { name: "刷新正式纪要" }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    expect(fetcher.mock.calls.every(([url]) => url === `${base}?record_id=${oldId}`)).toBe(true);
    expect(screen.queryByText("第三版的新内容")).not.toBeInTheDocument();
  });

  it("ignores a late response from the previously selected record", async () => {
    navigate(oldId);
    let resolveOld!: (response: Response) => void;
    const oldRequest = new Promise<Response>((resolve) => { resolveOld = resolve; });
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url) =>
      String(url).includes(oldId) ? oldRequest : Response.json(response(latestId, 3)),
    );
    vi.stubGlobal("fetch", fetcher);
    mount();
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    act(() => { navigate(latestId); window.dispatchEvent(new PopStateEvent("popstate")); });
    expect(await screen.findByText("第三版的新内容")).toBeVisible();
    await act(async () => { resolveOld(Response.json(response())); await oldRequest; });
    expect(screen.getByText("第三版的新内容")).toBeVisible();
    expect(screen.queryByText("保留的第一版原文")).not.toBeInTheDocument();
  });

  it("does not apply another meeting's record selector", () => {
    navigate(oldId, "77777777-7777-4777-8777-777777777777");
    const fetcher = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetcher);
    mount();
    expect(fetcher).not.toHaveBeenCalled();
    expect(screen.getByText("正式纪要与确认版本").closest("details")).not.toHaveAttribute("open");
  });
});
