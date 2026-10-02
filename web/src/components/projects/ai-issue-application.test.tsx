import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AiIssueEventRuns } from "./ai-issue-event-runs";
import { AiIssueApplication } from "./ai-issue-application";
const runId = "55555555-5555-4555-8555-555555555555", resultId = "66666666-6666-4666-8666-666666666666";
const path = `/api/projects/project/ai-issue-applications/${runId}`;
function data(canApply = false, application: object | null = null) { return { result_id: resultId, source_digest: "a".repeat(64), can_apply: canApply, notice: canApply ? "请核对本次建议后具名办理。" : "当前尚未开放实际办理，原建议仍可回查。", application, sources_current: true }; }
function receipt(disposition: "created" | "reused" = "created") { return { id: "application", issue_id: "original-issue", disposition, created_at: "2026-09-27T15:00:00Z", writer_name: "PDOS Agent", confirmed_by_name: "项目负责人", run_id: runId, result_id: resultId, requested_by_user_id: "human", output_event_row_id: 101, withdrawn_at: null, can_withdraw: false, withdrawal_notice: "当前问题不可撤回。", withdrawal_receipt: null }; }
function reviewItem(version: number, action: "decline" | "reopen", reason = "保留原依据，后续再核对") { return { id: `review-${version}`, version, action, reason, actor_name: "核对负责人", created_at: "2026-09-27T17:00:00Z" }; }
function review(version = 0, state: "unreviewed" | "declined" | "reopened" = "unreviewed", items: ReturnType<typeof reviewItem>[] = [], next: number | null = null) { return { version, state, can_change: true, notice: "按当前业务权限具名处置；生成未开放不影响核对。", items, next_before_version: next }; }
function open() { fireEvent.click(screen.getByText("实际办理与回链")); }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("AI Issue application receipts", () => {
  it("loads on demand and does not expose an action before server readiness", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json(data()));
    vi.stubGlobal("fetch", fetcher); render(<AiIssueApplication projectId="project" runId={runId} />);
    expect(fetcher).not.toHaveBeenCalled(); open();
    expect(await screen.findByText("当前尚未开放实际办理，原建议仍可回查。")).toBeVisible();
    expect(screen.queryByRole("button", { name: "一次确认并办理" })).not.toBeInTheDocument();
    expect(fetcher.mock.calls[0][0]).toBe(path);
  });
  it.each([false, true])("shows direct AI attribution without a human confirmer and exposes sampling only when selected: %s", async sampled => {
    const automatic = { ...receipt(), capture_mode: "direct", confirmed_by_user_id: null, confirmed_by_name: null, requested_by_name: "原生成请求人", receipt: { route: "automatic", write_receipt: { route: "direct", sampled, reason_label: "已按原登记自动办理" } } };
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json(data(false, automatic))); vi.stubGlobal("fetch", fetcher); render(<AiIssueApplication projectId="project" runId={runId} />); open();
    expect(await screen.findByText("AI 自动办理")).toBeVisible(); expect(screen.getByText("办理署名：PDOS Agent · 请求来源：原生成请求人")).toBeVisible(); expect(screen.queryByText(/确认人：/)).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: "一次确认并办理" })).not.toBeInTheDocument();
    expect(screen.queryByText("具名抽检与历史") !== null).toBe(sampled); expect(fetcher).toHaveBeenCalledTimes(1); expect(screen.queryByRole("button", { name: "认可抽检结果" })).not.toBeInTheDocument();
  });
  it("shows the latched automatic stop immediately after a direct Issue withdrawal refresh", async () => {
    const automatic = { ...receipt(), capture_mode: "direct", confirmed_by_user_id: null, confirmed_by_name: null, requested_by_name: "原请求人", can_withdraw: true, automatic_stop: null, receipt: { route: "automatic", write_receipt: { route: "direct", sampled: false, reason_label: "按原登记自动办理" } } };
    const withdrawn = { id: "withdrawal", created_at: "2026-09-27T16:00:00Z", kind: "single", actor_name: "负责人", items: [{ application_id: "application", issue_id: "original-issue", status: "withdrawn", reason_code: "withdrawn", reason: "原件保留" }] };
    const stop = { id: "stop", receipt: { generated: 10, withdrawn: 1, maximum_retraction_basis_points: 500, recovery_conditions: "完成原因核对并重新核实原登记条件" } };
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(data(false, automatic))).mockResolvedValueOnce(Response.json(withdrawn)).mockResolvedValueOnce(Response.json(data(false, { ...automatic, can_withdraw: false, withdrawn_at: withdrawn.created_at, automatic_stop: stop }))); vi.stubGlobal("fetch", fetcher); render(<AiIssueApplication projectId="project" runId={runId} />); open(); await screen.findByRole("button", { name: "撤回这条AI创建的问题" }); fireEvent.change(screen.getByRole("textbox", { name: /撤回原因/ }), { target: { value: "建议不准确" } }); fireEvent.click(screen.getByRole("button", { name: "撤回这条AI创建的问题" }));
    expect(await screen.findByText("自动建单已暂停，后续转逐次确认")).toBeVisible(); expect(screen.getByText("原统计：自动创建 10 条，撤回 1 条；原撤回率门槛不高于 5%。")).toBeVisible(); expect(screen.getByText("恢复条件：完成原因核对并重新核实原登记条件")).toBeVisible(); expect(screen.getByText("AI 创建的问题已撤回")).toBeVisible(); expect(screen.queryByRole("button", { name: /解锁/ })).not.toBeInTheDocument(); expect(fetcher.mock.calls[2][0]).toBe(path);
  });
  it("rejects an automatic receipt that incorrectly claims human confirmation", async () => {
    const automatic = { ...receipt(), capture_mode: "direct", confirmed_by_user_id: "human", requested_by_name: "请求人", receipt: { route: "automatic", write_receipt: { route: "direct", sampled: true } } };
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(Response.json(data(false, automatic)))); render(<AiIssueApplication projectId="project" runId={runId} />); open(); expect(await screen.findByRole("alert")).toHaveTextContent("自动办理署名或原回执不完整"); expect(screen.queryByText("AI 自动办理")).not.toBeInTheDocument();
  });
  it("submits the server-bound result once and displays actual AI writer, named confirmer and Issue link", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(data(true))).mockResolvedValueOnce(Response.json(data(false, receipt())));
    vi.stubGlobal("fetch", fetcher); render(<AiIssueApplication projectId="project" runId={runId} />); open();
    fireEvent.click(await screen.findByRole("button", { name: "一次确认并办理" }));
    expect(await screen.findByText("AI 已创建问题")).toBeVisible();
    expect(screen.getByText("办理署名：PDOS Agent · 确认人：项目负责人")).toBeVisible();
    expect(screen.getByRole("link", { name: "查看原问题与继续办理" })).toHaveAttribute("href", "/projects?project=project&tab=work-items&entity_id=original-issue");
    expect(screen.queryByRole("button", { name: "一次确认并办理" })).not.toBeInTheDocument();
    expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body))).toEqual({ request_id: expect.any(String), result_id: resultId, expected_digest: "a".repeat(64) });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it("retries the same request after an unknown result and describes reuse without claiming AI creation", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(data(true))).mockRejectedValueOnce(new Error("连接中断")).mockResolvedValueOnce(Response.json(data(false, receipt("reused"))));
    vi.stubGlobal("fetch", fetcher); render(<AiIssueApplication projectId="project" runId={runId} />); open();
    fireEvent.click(await screen.findByRole("button", { name: "一次确认并办理" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("连接中断");
    expect(screen.getByRole("button", { name: "刷新办理条件与回执" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "一次确认并办理" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "沿原请求核对办理结果" }));
    expect(await screen.findByText("已关联已有问题，原问题保持")).toBeVisible();
    expect(screen.queryByText("AI 已创建问题")).not.toBeInTheDocument();
    expect(fetcher.mock.calls[1][1]?.body).toBe(fetcher.mock.calls[2][1]?.body);
  });
  it("preserves a same-source application from another original run instead of treating the selected proposal as reapplied", async () => {
    const originalRun = "88888888-8888-4888-8888-888888888888", originalResult = "99999999-9999-4999-8999-999999999999";
    const original = { ...receipt(), run_id: originalRun, result_id: originalResult };
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json(data(false, original)));
    vi.stubGlobal("fetch", fetcher); render(<AiIssueApplication projectId="project" runId={runId} />); open();
    expect(await screen.findByText("同一来源已有办理回执，沿原问题继续")).toBeVisible();
    expect(screen.getByText("本条原建议未被再次应用；以下保留当时的实际办理记录。")).toBeVisible();
    expect(screen.getByText("办理署名：PDOS Agent · 确认人：项目负责人")).toBeVisible();
    expect(screen.getByRole("link", { name: "查看原问题与继续办理" })).toHaveAttribute("href", "/projects?project=project&tab=work-items&entity_id=original-issue");
    expect(screen.queryByRole("button", { name: "一次确认并办理" })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("shows a known conflict and requires fresh conditions before another confirmation", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(data(true))).mockResolvedValueOnce(Response.json({ detail: "原建议来源已有变化，请刷新核对" }, { status: 409 })).mockResolvedValueOnce(Response.json({ ...data(true), sources_current: false }));
    vi.stubGlobal("fetch", fetcher); render(<AiIssueApplication projectId="project" runId={runId} />); open();
    fireEvent.click(await screen.findByRole("button", { name: "一次确认并办理" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("原建议来源已有变化，请刷新核对");
    expect(screen.queryByRole("button", { name: "一次确认并办理" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "刷新办理条件与回执" }));
    expect(await screen.findByText("当前来源已有变化，原办理记录保留；请核对来源记录。")).toBeVisible();
    expect(screen.queryByRole("button", { name: "一次确认并办理" })).not.toBeInTheDocument();
  });
  it("ignores another run's late response while preserving a historical receipt after source changes", async () => {
    let resolve!: (value: Response) => void;
    const otherId = "77777777-7777-4777-8777-777777777777";
    const fetcher = vi.fn<typeof fetch>().mockImplementationOnce(() => new Promise(done => { resolve = done; })).mockResolvedValueOnce(Response.json({ ...data(false, { ...receipt("reused"), run_id: otherId }), sources_current: false }));
    vi.stubGlobal("fetch", fetcher); const view = render(<AiIssueApplication projectId="project" runId={runId} />); open();
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    view.rerender(<AiIssueApplication projectId="project" runId={otherId} />); open();
    expect(await screen.findByText("已关联已有问题，原问题保持")).toBeVisible();
    await act(async () => resolve(Response.json(data(true))));
    expect(screen.queryByRole("button", { name: "一次确认并办理" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看原问题与继续办理" })).toBeVisible();
  });
  it("withdraws the original application with a named reason even when new writes are unavailable", async () => {
    const originalRun = "88888888-8888-4888-8888-888888888888";
    const applied = { ...receipt(), run_id: originalRun, can_withdraw: true, withdrawal_notice: "可撤回尚未人工办理的问题。" };
    const withdrawn = { id: "withdrawal", created_at: "2026-09-27T16:00:00Z", kind: "single", actor_name: "实际办理人", items: [{ application_id: "application", issue_id: "original-issue", status: "withdrawn", reason_code: "withdrawn", reason: "已撤回，原记录保留" }] };
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(data(false, applied))).mockResolvedValueOnce(Response.json(withdrawn)).mockResolvedValueOnce(Response.json(data(false, { ...applied, can_withdraw: false, withdrawn_at: withdrawn.created_at, withdrawal_receipt: withdrawn })));
    vi.stubGlobal("fetch", fetcher); render(<AiIssueApplication projectId="project" runId={runId} />); open();
    const button = await screen.findByRole("button", { name: "撤回这条AI创建的问题" }); expect(button).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { name: /撤回原因/ }), { target: { value: "来源重复登记" } }); fireEvent.click(button);
    expect(await screen.findByText("AI 创建的问题已撤回")).toBeVisible();
    expect(screen.getByText(/办理人：实际办理人/)).toBeVisible(); expect(screen.getByRole("link", { name: "查看原问题历史" })).toBeVisible();
    expect(fetcher.mock.calls[1][0]).toBe(`/api/projects/project/ai-issue-applications/${originalRun}/withdraw`);
    expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body))).toEqual({ request_id: expect.any(String), application_id: "application", reason: "来源重复登记" });
    expect(fetcher.mock.calls[2][0]).toBe(path);
    expect(screen.queryByRole("button", { name: "撤回这条AI创建的问题" })).not.toBeInTheDocument();
  });
  it("retries an uncertain run withdrawal unchanged and displays each skipped reason", async () => {
    const onIssueChanged = vi.fn(async () => undefined);
    const applied = { ...receipt(), can_withdraw: true };
    const withdrawn = { id: "withdrawal", created_at: "2026-09-27T16:00:00Z", kind: "run", actor_name: "项目负责人", items: [{ application_id: "application", issue_id: "original-issue", status: "skipped", reason_code: "human_edited", reason: "已由人工修改，保持原记录" }] };
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(data(false, applied))).mockRejectedValueOnce(new Error("连接中断")).mockResolvedValueOnce(Response.json(withdrawn)).mockResolvedValueOnce(Response.json(data(false, { ...applied, can_withdraw: false, withdrawal_receipt: withdrawn })));
    vi.stubGlobal("fetch", fetcher); render(<AiIssueApplication projectId="project" runId={runId} onIssueChanged={onIssueChanged} />); open();
    await screen.findByRole("button", { name: "撤销本次运行" });
    fireEvent.change(screen.getByRole("textbox", { name: /撤回原因/ }), { target: { value: "核对本次运行" } }); fireEvent.click(screen.getByRole("button", { name: "撤销本次运行" }));
    const retry = await screen.findByRole("button", { name: "沿原请求核对撤回结果" }); expect(screen.getByRole("button", { name: "刷新办理条件与回执" })).toBeDisabled();
    expect(screen.queryByRole("textbox", { name: /撤回原因/ })).not.toBeInTheDocument(); fireEvent.click(retry);
    expect(await screen.findByText("已跳过：已由人工修改，保持原记录")).toBeVisible();
    expect(onIssueChanged).toHaveBeenCalledWith([]);
    expect(fetcher.mock.calls[1][0]).toBe(`${path}/withdraw-run`); expect(fetcher.mock.calls[2][1]?.body).toBe(fetcher.mock.calls[1][1]?.body);
    expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body))).toEqual({ request_id: expect.any(String), reason: "核对本次运行" });
  });
  it("never offers withdrawal of a reused human Issue even if a malformed response claims eligibility", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(Response.json(data(false, { ...receipt("reused"), can_withdraw: true, withdrawal_notice: "复用原问题不属于本次 AI 创建" }))));
    render(<AiIssueApplication projectId="project" runId={runId} />); open();
    expect(await screen.findByText("复用原问题不属于本次 AI 创建")).toBeVisible();
    expect(screen.queryByRole("button", { name: "撤回这条AI创建的问题" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "撤销本次运行" })).not.toBeInTheDocument();
  });

  it("records a named decline and reopens only for consideration without creating or withdrawing an Issue", async () => {
    const declined = reviewItem(1, "decline", "当前证据不足"), reopened = reviewItem(2, "reopen", "补充资料后重新核对");
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ ...data(), review: review() })).mockResolvedValueOnce(Response.json({ ...data(), review: review(1, "declined", [declined]), review_receipt: declined })).mockResolvedValueOnce(Response.json({ ...data(), review: review(2, "reopened", [reopened, declined]), review_receipt: reopened }));
    vi.stubGlobal("fetch", fetcher); render(<AiIssueApplication projectId="project" runId={runId} />); open();
    expect(await screen.findByRole("button", { name: "不采纳这条建议" })).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { name: /处置原因/ }), { target: { value: declined.reason } }); fireEvent.click(screen.getByRole("button", { name: "不采纳这条建议" }));
    expect(await screen.findByText("已不采纳")).toBeVisible();
    expect(screen.getByText("本次请求回执：不采纳 · 核对负责人")).toBeVisible();
    fireEvent.change(screen.getByRole("textbox", { name: /处置原因/ }), { target: { value: reopened.reason } }); fireEvent.click(screen.getByRole("button", { name: "重新考虑" }));
    expect(await screen.findByText("已重新考虑 · 待核对")).toBeVisible();
    fireEvent.click(screen.getByText("建议处置历史 · 2 次"));
    expect(screen.getByText("1. 不采纳 · 核对负责人")).toBeVisible();
    expect(screen.getByText("2. 重新考虑 · 核对负责人")).toBeVisible();
    const bodies = fetcher.mock.calls.slice(1).map(call => JSON.parse(String(call[1]?.body)));
    expect(bodies).toEqual([{ request_id: expect.any(String), result_id: resultId, expected_digest: "a".repeat(64), expected_version: 0, action: "decline", reason: declined.reason }, { request_id: expect.any(String), result_id: resultId, expected_digest: "a".repeat(64), expected_version: 1, action: "reopen", reason: reopened.reason }]);
    expect(fetcher.mock.calls.slice(1).every(call => call[0] === `${path}/review`)).toBe(true);
    expect(screen.queryByRole("button", { name: "一次确认并办理" })).not.toBeInTheDocument();
  });
  it("retries an uncertain review unchanged and preserves the latest reopened state with the original decline receipt", async () => {
    const original = reviewItem(1, "decline", "需要补证"), latest = reviewItem(2, "reopen", "已补充资料");
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ ...data(true), review: review() })).mockRejectedValueOnce(new Error("连接中断")).mockResolvedValueOnce(Response.json({ ...data(false), review: review(2, "reopened", [latest, original]), review_receipt: original }));
    vi.stubGlobal("fetch", fetcher); render(<AiIssueApplication projectId="project" runId={runId} />); open();
    await screen.findByRole("button", { name: "不采纳这条建议" });
    fireEvent.change(screen.getByRole("textbox", { name: /处置原因/ }), { target: { value: original.reason } }); fireEvent.click(screen.getByRole("button", { name: "不采纳这条建议" }));
    const retry = await screen.findByRole("button", { name: "沿原请求核对处置结果" });
    expect(screen.getByRole("button", { name: "刷新办理条件与回执" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "一次确认并办理" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /处置原因/ })).not.toBeInTheDocument();
    fireEvent.click(retry);
    expect(await screen.findByText("已重新考虑 · 待核对")).toBeVisible();
    expect(screen.getByText("本次请求回执：不采纳 · 核对负责人")).toBeVisible();
    expect(fetcher.mock.calls[1][1]?.body).toBe(fetcher.mock.calls[2][1]?.body);
    expect(screen.queryByText("已不采纳")).not.toBeInTheDocument();
  });
  it("pages immutable review history with the current state and version rather than the historical action", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ ...data(true), review: review(4, "reopened", [reviewItem(4, "reopen"), reviewItem(3, "decline")], 3) })).mockResolvedValueOnce(Response.json(review(5, "declined", [reviewItem(2, "reopen"), reviewItem(1, "decline")])));
    vi.stubGlobal("fetch", fetcher); render(<AiIssueApplication projectId="project" runId={runId} />); open();
    fireEvent.click(await screen.findByText("建议处置历史 · 4 次"));
    fireEvent.click(screen.getByRole("button", { name: "更早的处置记录" }));
    expect(await screen.findByText("1. 不采纳 · 核对负责人")).toBeVisible();
    expect(screen.getByText("4. 重新考虑 · 核对负责人")).toBeVisible();
    expect(screen.getByText("已不采纳")).toBeVisible();
    expect(screen.getByText("建议处置历史 · 5 次")).toBeVisible();
    expect(screen.queryByRole("button", { name: "一次确认并办理" })).not.toBeInTheDocument();
    expect(fetcher.mock.calls[1][0]).toBe(`${path}/review?before_version=3`);
  });
  it("shows the server's reason when a same-source application prevents further review", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(Response.json({ ...data(false, receipt()), review: { ...review(1, "declined", [reviewItem(1, "decline")]), can_change: false, notice: "同一来源已有实际办理，不能再更改建议处置" } })));
    render(<AiIssueApplication projectId="project" runId={runId} />); open();
    expect(await screen.findByText("同一来源已有实际办理，不能再更改建议处置")).toBeVisible();
    expect(screen.queryByRole("button", { name: "重新考虑" })).not.toBeInTheDocument();
    expect(screen.getByText("建议处置历史 · 1 次")).toBeVisible();
  });
  it("offers review for an insufficient-evidence result in a shadow run", async () => {
    const saved = { run_id: runId, request_id: resultId, event_row_id: 31, source_digest: "a".repeat(64), status: "succeeded", error_code: null, created_at: "2026-09-27T12:00:00Z", sources_current: true, requested_by_me: true, proposal: { disposition: "insufficient_evidence", title: null, description: null, severity: null, existing_issue_id: null, citations: [], open_questions: ["缺少判据"] }, frozen_sources: [] };
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async input => {
      const url = String(input);
      if (url.includes("ai-issue-applications")) return Response.json({ ...data(), review: review() });
      if (url.includes("preparation")) return Response.json({ event_row_id: 31, source_digest: "a".repeat(64), source_status: "current", source_title: "原测试失败", rollout: "shadow", can_request: false, notice: "当前不生成新建议", references: [], existing_issue_id: null });
      return Response.json({ items: [saved], next_before_id: null, rollout: "shadow", can_request: false });
    }));
    render(<AiIssueEventRuns projectId="project" eventRowId={31} />);
    fireEvent.click(screen.getByText("AI 建议与运行记录"));
    fireEvent.click(await screen.findByRole("button", { name: "查看本次建议与回执" }));
    expect(await screen.findByText("资料不足，尚未形成建单建议")).toBeVisible(); open();
    expect(await screen.findByRole("button", { name: "不采纳这条建议" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "生成问题建议" })).not.toBeInTheDocument();
  });

  it("requires refreshing after a review-version conflict before offering another action", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ ...data(), review: review() })).mockResolvedValueOnce(Response.json({ detail: "处置版本已有变化，请刷新核对" }, { status: 409 })).mockResolvedValueOnce(Response.json({ ...data(), review: review(1, "declined", [reviewItem(1, "decline")]) }));
    vi.stubGlobal("fetch", fetcher); render(<AiIssueApplication projectId="project" runId={runId} />); open();
    await screen.findByRole("button", { name: "不采纳这条建议" });
    fireEvent.change(screen.getByRole("textbox", { name: /处置原因/ }), { target: { value: "需要补证" } }); fireEvent.click(screen.getByRole("button", { name: "不采纳这条建议" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("处置版本已有变化，请刷新核对");
    expect(screen.queryByRole("button", { name: "不采纳这条建议" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "沿原请求核对处置结果" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "刷新办理条件与回执" }));
    expect(await screen.findByRole("button", { name: "重新考虑" })).toBeVisible();
    expect(fetcher.mock.calls.filter(call => call[1]?.method === "POST")).toHaveLength(1);
  });

});
