import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AiMeetingDrafts } from "./ai-meeting-drafts";

const project = "11111111-1111-4111-8111-111111111111";
const meeting = "22222222-2222-4222-8222-222222222222";
const draftId = "33333333-3333-4333-8333-333333333333";
const actor = "44444444-4444-4444-8444-444444444444";
const base = `/api/projects/${project}/meetings/${meeting}/ai-minutes-drafts`;
const payload = { body: "原稿：样机装配已完成。", unresolved_points: "验证日期待确定。", citations: [{ segment_id: "55555555-5555-4555-8555-555555555555", exact_quote: "样机装配已完成。" }] };
function draft(changes: Record<string, unknown> = {}) {
  return { id: draftId, run_id: "66666666-6666-4666-8666-666666666666", finding_id: "77777777-7777-4777-8777-777777777777", revision: 0, state: "active", capture_mode: "direct", review_required: false, writer_name: "PDOS Agent", created_at: "2026-09-27T08:00:00Z", body: payload.body, unresolved_points: payload.unresolved_points, payload, current_payload: payload, source_current: true, human_edited: false, published_entity_id: null, history: [], history_next_before: null, write_receipt: { route: "direct", sampled: false, reason: "qualified", qualification: "not-shown" }, ...changes };
}
function data(item: ReturnType<typeof draft>, canManage = true) {
  return { current_user_id: actor, items: [item], next_before: null, notice: "AI 按当前政策保存草稿，正式发布仍由具名人员办理。", policy_ready: true, scope: { enabled: true, revision: 1 }, can_manage_scope: false, can_manage: canManage };
}
function open(kind = "纪要") {
  const details = screen.getByText(`AI ${kind}草稿`).closest("details");
  if (!details) throw new Error("draft section missing");
  details.open = true;
  fireEvent(details, new Event("toggle"));
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("AI direct meeting drafts", () => {
  it("shows a current automatic-write pause alongside unchanged published and withdrawn history", async () => {
    const stopReason = "该版本自动草稿因撤回比例超限已暂停，后续生成需逐次确认。";
    const published = draft({ state: "published", automatic_stop_reason: stopReason, published_entity_id: "88888888-8888-4888-8888-888888888888" });
    const withdrawn = draft({ id: "99999999-9999-4999-8999-999999999999", state: "withdrawn", automatic_stop_reason: stopReason });
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(Response.json({ ...data(published), items: [published, withdrawn] })));
    render(<AiMeetingDrafts projectId={project} meetingId={meeting} onPublished={vi.fn()} />);
    open();
    expect(await screen.findByText("PDOS Agent · 已正式发布")).toBeVisible();
    expect(screen.getByText("PDOS Agent · 已撤回")).toBeVisible();
    expect(screen.getAllByText(stopReason)).toHaveLength(2);
    for (const warning of screen.getAllByText(stopReason)) expect(warning).toHaveClass("text-primary");
    expect(screen.getByRole("link", { name: "打开正式纪要记录" })).toHaveAttribute("href", expect.stringContaining("minutes=88888888-8888-4888-8888-888888888888"));
    expect(screen.queryByRole("button", { name: "确认采用此草稿" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "正式发布纪要" })).not.toBeInTheDocument();
  });

  it("shows unsampled direct drafts as already written and permits a human edit without adoption", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json(data(draft())));
    vi.stubGlobal("fetch", fetcher);
    render(<AiMeetingDrafts projectId={project} meetingId={meeting} onPublished={vi.fn()} />);
    open();
    expect(await screen.findByText("PDOS Agent · AI已写入草稿")).toBeVisible();
    expect(screen.queryByRole("button", { name: "确认采用此草稿" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "确认抽检结果" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "正式发布纪要" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "撤回 AI 草稿" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "人工修订" }));
    expect(screen.getByLabelText("修订正文")).toHaveValue(payload.body);
    expect(screen.getByLabelText("办理依据")).toBeEnabled();
    expect(fetcher.mock.calls[0][0]).toBe(`${base}?kind=minutes`);
    expect(screen.queryByText("not-shown")).not.toBeInTheDocument();
  });

  it("confirms a sampled direct draft, retries the original request and retains named history", async () => {
    let saved = false, attempts = 0;
    const onPublished = vi.fn(async () => {});
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (_url, init) => {
      if (init?.method === "POST") {
        if (++attempts === 1) throw new TypeError("network down");
        saved = true;
        return Response.json({ receipt: { revision: 1, action: "confirm", actor_user_id: actor }, reused: true });
      }
      return Response.json(data(draft({ review_required: !saved, revision: saved ? 1 : 0, write_receipt: { route: "direct", sampled: true }, history: saved ? [{ payload: null, revision: 1, action: "confirm", actor_name: "品质负责人", created_at: "2026-09-27T09:00:00Z", reason: "已逐句核对原文", body: payload.body, unresolved_points: payload.unresolved_points }] : [] })));
    });
    vi.stubGlobal("fetch", fetcher);
    render(<AiMeetingDrafts projectId={project} meetingId={meeting} onPublished={onPublished} />);
    open();
    expect(await screen.findByText(/抽检待核对/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "确认抽检结果" }));
    fireEvent.change(screen.getByLabelText("办理依据"), { target: { value: "已逐句核对原文" } });
    fireEvent.click(screen.getByRole("button", { name: "保存抽检确认" }));
    expect(await screen.findByText(/保存结果尚未确认/)).toBeVisible();
    expect(screen.getByLabelText("办理依据")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "重试原请求" }));
    await waitFor(() => expect(screen.queryByText(/抽检待核对/)).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "确认抽检结果" })).not.toBeInTheDocument();
    expect(screen.getByText(/第 1 次 · 抽检确认 · 品质负责人/)).toBeInTheDocument();
    const mutations = fetcher.mock.calls.filter(([, init]) => init?.method === "POST");
    expect(mutations).toHaveLength(2);
    expect(mutations[0][0]).toBe(`${base}/${draftId}/actions?kind=minutes`);
    expect(mutations[0][1]?.body).toBe(mutations[1][1]?.body);
    expect(JSON.parse(String(mutations[0][1]?.body))).toEqual({ request_id: expect.any(String), expected_revision: 0, action: "confirm", reason: "已逐句核对原文" });
    expect(onPublished).toHaveBeenCalledTimes(1);
  });

  it("keeps trial adoption and shows a readable quality-stop fallback reason", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(Response.json(data(draft({ capture_mode: "trial", state: "pending_confirmation", write_receipt: { route: "confirm", reason: "quality_stop", reason_label: "质量观察超限，本稿改为确认后采用。" } })))));
    render(<AiMeetingDrafts projectId={project} meetingId={meeting} onPublished={vi.fn()} />);
    open();
    expect(await screen.findByText("PDOS Agent · 待确认草稿")).toBeVisible();
    expect(screen.getByText("质量观察超限，本稿改为确认后采用。")).toHaveClass("text-primary");
    expect(screen.getByRole("button", { name: "确认采用此草稿" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "正式发布纪要" })).not.toBeInTheDocument();
    expect(screen.queryByText("quality_stop")).not.toBeInTheDocument();
  });

  it("preserves the designated human approver gate for directly written decisions", async () => {
    const decision = { ...payload, meeting_id: meeting, title: "技术方案", decision_kind: "technical_choice", context: "原讨论", trade_offs: "按测试结果比较", outcome: "待具名批准", rationale: "依据验证结果", consequence: "进入下一轮验证", approver_id: "other-human", options: ["方案甲", "方案乙"], details_confirmed: true, follow_up_pending: false, member_options: [{ id: "other-human", display_name: "指定负责人" }] };
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(Response.json(data(draft({ payload: decision, current_payload: decision })))));
    render(<AiMeetingDrafts projectId={project} meetingId={meeting} kind="decisions" onPublished={vi.fn()} />);
    open("决策");
    expect(await screen.findByText("PDOS Agent · AI已写入草稿")).toBeVisible();
    expect(screen.getByText("等待草稿中指定的批准人本人办理。")).toBeVisible();
    expect(screen.getByRole("button", { name: "本人批准决策" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "人工修订" })).toBeEnabled();
  });

  it("keeps changed-source direct drafts blocked and read-only viewers without actions", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json(data(draft({ source_current: false, review_required: true }))));
    vi.stubGlobal("fetch", fetcher);
    const rendered = render(<AiMeetingDrafts projectId={project} meetingId={meeting} onPublished={vi.fn()} />);
    open();
    await screen.findByText(/原转录、说话人或正式来源已变化/);
    expect(screen.getByRole("button", { name: "确认抽检结果" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "人工修订" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "正式发布纪要" })).toBeDisabled();
    rendered.unmount();
    fetcher.mockResolvedValue(Response.json(data(draft(), false)));
    render(<AiMeetingDrafts projectId={project} meetingId={meeting} onPublished={vi.fn()} />);
    open();
    await screen.findByText("PDOS Agent · AI已写入草稿");
    expect(screen.queryByRole("button", { name: "人工修订" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "撤回 AI 草稿" })).not.toBeInTheDocument();
  });
});
