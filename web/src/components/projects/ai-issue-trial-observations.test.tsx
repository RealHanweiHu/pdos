import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AiIssueTrialObservations } from "./ai-issue-trial-observations";

const id = "55555555-5555-4555-8555-555555555555", olderId = "66666666-6666-4666-8666-666666666666";
const base = "/api/projects/project/ai-issue-observations";
function summary(identity = id, total = 0) { return { id: identity, created_at: "2026-09-27T12:00:00Z", actor_name: "项目核对人", window_start: "2026-09-20T00:00:00Z", window_end: "2026-09-27T00:00:00Z", total_runs: total }; }
function sample(index: number) { return { run_id: `run-${index}`, event_row_id: index + 1, status: index === 0 ? "failed" : "succeeded", result_id: index === 0 ? null : `result-${index}`, disposition: index === 0 ? null : index === 1 ? "insufficient_evidence" : "create_issue", binding_kind: "not_recorded", review_state: "unreviewed", application_kind: null, same_source_applied: false, withdrawn: false, human_edited: false, created_at: "2026-09-21T10:00:00Z", issue_id: null, source_title: `观察来源 ${index + 1}`, source_href: index === 0 ? "/projects?project=project&tab=test-runs" : null }; }
function detail(identity = id, total = 0) { return { ...summary(identity, total), as_of: "2026-09-27T12:00:00Z", counts: { total_runs: total, succeeded_runs: Math.max(total - 1, 0), failed_runs: total ? 1 : 0, pending_runs: 0, proposal_runs: Math.max(total - 1, 0), insufficient_runs: total > 1 ? 1 : 0, created_issues: 0, reused_issues: 0, same_source_applied_runs: 0, declined_runs: 0, reopened_runs: 0, unhandled_proposals: Math.max(total - 1, 0), withdrawn_issues: 0, human_edited_issues: 0, trial_candidates: 0, evidence_only_runs: 0, unrecorded_bindings: total }, ratios: { handled_proposals: 0, confirmed_proposals: 0, confirmation_basis_points: null, withdrawal_basis_points: null, descriptive_only: true }, items: Array.from({ length: total }, (_, index) => sample(index)), notice: "原窗口全部运行，包含失败、补证及未办理，不代表自动资格。", qualification_granted: false }; }
function history(items = [summary()], canCapture = true, next: string | null = null) { return { items, can_capture: canCapture, next_before_id: next }; }
function open() { fireEvent.click(screen.getByText("项目问题运行观察")); }
function windowInputs() { fireEvent.change(screen.getByLabelText("窗口开始"), { target: { value: "2026-09-20T10:30" } }); fireEvent.change(screen.getByLabelText("窗口结束（不含）"), { target: { value: "2026-09-21T10:30" } }); }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("Issue run observations", () => {
  it("loads only when expanded, defaults to seven local days and respects view-only access", async () => {
    vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date("2026-09-27T12:00:00Z"));
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json(history([], false)));
    vi.stubGlobal("fetch", fetcher); render(<AiIssueTrialObservations projectId="project" />);
    expect(fetcher).not.toHaveBeenCalled(); open();
    expect(await screen.findByText("当前账号仅可查看运行观察，不能保存。")).toBeVisible();
    expect(screen.getByRole("button", { name: "保存本窗口观察" })).toBeDisabled();
    const start = screen.getByLabelText("窗口开始") as HTMLInputElement, end = screen.getByLabelText("窗口结束（不含）") as HTMLInputElement;
    expect(new Date(end.value).getTime() - new Date(start.value).getTime()).toBe(7 * 86400000);
    expect(fetcher.mock.calls[0][0]).toBe(`${base}?limit=20`);
  });
  it("pages original observations and all samples locally while keeping failure, insufficiency and absent ratios explicit", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(history([summary(id, 21)], false, id))).mockResolvedValueOnce(Response.json(history([summary(olderId)], false))).mockResolvedValueOnce(Response.json(detail(id, 21)));
    vi.stubGlobal("fetch", fetcher); render(<AiIssueTrialObservations projectId="project" />); open();
    fireEvent.click(await screen.findByRole("button", { name: "更早的观察记录" }));
    await waitFor(() => expect(screen.getAllByRole("button", { name: "查看原观察" })).toHaveLength(2));
    expect(fetcher.mock.calls[1][0]).toBe(`${base}?limit=20&before_id=${id}`);
    fireEvent.click(screen.getAllByRole("button", { name: "查看原观察" })[0]);
    expect(await screen.findByText("全部样本 · 共 21 条，当前第 1 / 2 页（每页 20 条）")).toBeVisible();
    expect(screen.getAllByText("—")).toHaveLength(2);
    expect(screen.getByText(/运行失败 · 尚无建议结果/)).toBeVisible(); expect(screen.getByText(/生成成功 · 资料不足/)).toBeVisible();
    expect(screen.getByRole("link", { name: "查看来源记录" })).toHaveAttribute("href", "/projects?project=project&tab=test-runs");
    expect(screen.queryByText("观察来源 21")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "下一页样本" }));
    expect(screen.getByText("观察来源 21")).toBeVisible(); expect(screen.queryByText("观察来源 1")).not.toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(3);
  });
  it.each(["network", "concurrency"])("retries %s with the original request and locked window without modifying business records", async failure => {
    const posts: string[] = [];
    const fetcher = vi.fn<typeof fetch>(async (_url, init) => {
      if (init?.method === "POST") { posts.push(String(init.body)); if (posts.length === 1) { if (failure === "network") throw new Error("连接中断"); return Response.json({ detail: { code: "OBSERVATION_RETRY", message: "观察记录正被更新，请沿原请求重新核对" } }, { status: 409 }); } return Response.json({ ...detail(), ...JSON.parse(posts[0]) }); }
      return Response.json(history([]));
    });
    vi.stubGlobal("fetch", fetcher); render(<AiIssueTrialObservations projectId="project" />); open();
    await screen.findByText("尚无保存的观察记录。"); windowInputs(); fireEvent.click(screen.getByRole("button", { name: "保存本窗口观察" }));
    const retry = await screen.findByRole("button", { name: "沿原请求核对观察结果" });
    expect(screen.getByLabelText("窗口开始")).toBeDisabled(); expect(screen.getByRole("button", { name: "保存本窗口观察" })).toBeDisabled();
    fireEvent.click(retry);
    expect(await screen.findByText("项目核对人 保存的运行观察")).toBeVisible();
    expect(posts).toHaveLength(2); expect(posts[0]).toBe(posts[1]);
    expect(JSON.parse(posts[0])).toEqual({ request_id: expect.any(String), window_start: new Date("2026-09-20T10:30").toISOString(), window_end: new Date("2026-09-21T10:30").toISOString() });
    expect(screen.getByText("比率只描述本窗口，模拟记录和观察结果不等于真实模型成绩，也不授予自动写入资格。")).toBeVisible();
    expect(fetcher.mock.calls.every(call => String(call[0]).startsWith(base))).toBe(true);
  });
  it("validates the window locally and exposes capacity conflicts without presenting a truncated observation", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(history([]))).mockResolvedValueOnce(Response.json({ detail: "窗口超过5000条，请缩小窗口；未保存截断结果" }, { status: 409 }));
    vi.stubGlobal("fetch", fetcher); render(<AiIssueTrialObservations projectId="project" />); open();
    await screen.findByText("尚无保存的观察记录。");
    fireEvent.change(screen.getByLabelText("窗口开始"), { target: { value: "2099-01-01T10:30" } }); fireEvent.click(screen.getByRole("button", { name: "保存本窗口观察" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("开始早于结束"); expect(fetcher).toHaveBeenCalledTimes(1);
    windowInputs(); fireEvent.click(screen.getByRole("button", { name: "保存本窗口观察" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("窗口超过5000条");
    expect(screen.queryByRole("region", { name: "原运行观察详情" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("窗口开始")).toBeEnabled();
  });
  it("ignores an earlier project's delayed detail and rejects incomplete sample sets", async () => {
    let resolve!: (response: Response) => void;
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(history())).mockImplementationOnce(() => new Promise(done => { resolve = done; })).mockResolvedValueOnce(Response.json(history([summary(olderId, 2)]))).mockResolvedValueOnce(Response.json({ ...detail(olderId, 2), items: [sample(0)] }));
    vi.stubGlobal("fetch", fetcher); const view = render(<AiIssueTrialObservations projectId="project" />); open();
    fireEvent.click(await screen.findByRole("button", { name: "查看原观察" }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    view.rerender(<AiIssueTrialObservations projectId="other" />); open();
    await screen.findByRole("button", { name: "查看原观察" });
    await act(async () => resolve(Response.json({ ...detail(), actor_name: "旧项目人员" })));
    expect(screen.queryByText("旧项目人员 保存的运行观察")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看原观察" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("不会展示截断结果");
    expect(screen.queryByRole("region", { name: "原运行观察详情" })).not.toBeInTheDocument();
  });
});
