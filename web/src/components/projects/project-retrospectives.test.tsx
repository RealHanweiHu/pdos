import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/ai/project-conversation", () => ({ ProjectConversation: () => null }));
vi.mock("./meeting-planning", () => ({ MeetingPlanning: () => null }));
vi.mock("./meeting-planning-origin", () => ({ MeetingPlanningOrigin: () => null }));
vi.mock("./meeting-notifications", () => ({ MeetingNotifications: () => null }));
vi.mock("./meeting-conference-requests", () => ({ MeetingConferenceRequests: () => null }));
vi.mock("./meeting-rescheduling", () => ({ MeetingRescheduling: () => null }));
vi.mock("./meeting-preparation", () => ({ MeetingPreparation: () => null }));
vi.mock("./meeting-followup", () => ({ MeetingFollowup: () => null }));
vi.mock("./meeting-transcripts", () => ({ MeetingTranscripts: () => null }));
vi.mock("./meeting-minutes", () => ({ MeetingMinutes: () => null }));

import { ProjectMeetings } from "./project-retrospectives";

const projectId = "11111111-1111-4111-8111-111111111111";
const meetingId = "22222222-2222-4222-8222-222222222222";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.replaceState({}, "", "/"); });

describe("meeting receipt entry", () => {
  it("opens and loads the linked meeting on the initial page visit", async () => {
    window.history.replaceState({}, "", `/projects?project=${projectId}&meeting=${meetingId}`);
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json({
      id: meetingId, meeting_type: "weekly", title: "历史纪要所属会议", status: "completed",
      scheduled_start_at: "2026-09-27T08:00:00Z", scheduled_end_at: "2026-09-27T09:00:00Z",
      external_provider: null, archived_at: null, retrospective_version: 0,
      retrospective_conclusion: null, retrospective_applicability: null, retrospective_source_refs: [],
    }));
    vi.stubGlobal("fetch", fetcher);
    render(<ProjectMeetings projectId={projectId} canManage={false} canUpload={false} />);
    expect(await screen.findByText("历史纪要所属会议")).toBeVisible();
    expect(screen.getByText("会议准备与复盘").closest("details")).toHaveAttribute("open");
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0]?.[0]).toBe(`/api/projects/${projectId}/meetings/${meetingId}`);
  });

  it("keeps an unavailable linked meeting visible as an error without listing unrelated meetings", async () => {
    window.history.replaceState({}, "", `/projects?project=${projectId}&meeting=${meetingId}`);
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json({
      detail: { code: "MEETING_NOT_FOUND", message: "链接中的会议不可用" },
    }, { status: 404 }));
    vi.stubGlobal("fetch", fetcher);
    render(<ProjectMeetings projectId={projectId} canManage={false} canUpload={false} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("链接中的会议不可用");
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(screen.getByText("会议准备与复盘").closest("details")).toHaveAttribute("open");
  });
});
