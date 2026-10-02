import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AiIssueEventRuns } from "./ai-issue-event-runs";
const base = "/api/projects/project/ai-issue-event-runs";
const runId = "55555555-5555-4555-8555-555555555555";
const requestId = "66666666-6666-4666-8666-666666666666";
const reference = { reference_id: "test.result", label: "原测试结果", excerpt: "耐久测试失败，振动超过判据。" };
function preparation(live = true) { return { event_row_id: 31, source_digest: "a".repeat(64), source_status: "current", source_title: "耐久失败事件", rollout: live ? "live" : "shadow", can_request: live, notice: "建议仅供核对，尚未创建问题。", references: [reference], existing_issue_id: null, prompt_version: "event-issue-v1" }; }
function receipt(overrides: object = {}) { return { run_id: runId, request_id: requestId, project_id: "project", event_row_id: 31, event_id: "original-event", event_type: "TEST_FAILED", event_at: "2026-09-27T11:00:00Z", source_title: "耐久失败事件", source_digest: "a".repeat(64), status: "succeeded", created_at: "2026-09-27T12:00:00Z", completed_at: "2026-09-27T12:00:01Z", error_code: null, result_id: "result", invocation_id: "invocation", proposal: { disposition: "create_issue", title: "耐久振动异常", description: "测试失败，需要核对原判据与样机。", severity: "high", existing_issue_id: null, citations: [{ reference_id: reference.reference_id, exact_quote: reference.excerpt }], open_questions: [] }, disposition: "create_issue", open_questions: [], reference_labels: { "test.result": "原测试结果" }, existing_issue_id: null, sources_current: true, requested_by_me: true, frozen_sources: [reference], ...overrides }; }
function page(items: ReturnType<typeof receipt>[] = [], next: string | null = null, live = true) { return { items, next_before_id: next, rollout: live ? "live" : "shadow", can_request: live, prompt_version: "event-issue-v1" }; }
function open() { fireEvent.click(screen.getByText("AI 建议与运行记录")); }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("issue event suggestions", () => {
  it("opens a trigger history's original run through the existing reader without generating another request", async () => {
    const fetcher = vi.fn<typeof fetch>(async input => { const url = String(input); if (url.includes("ai-issue-event-history")) return Response.json({ items: [{ id: requestId, created_at: "2026-09-27T12:01:00Z", event_at: "2026-09-27T12:00:00Z", event_type: "TEST_FAILED", status: "reused", reason: "已有原运行，沿原回执继续。", reason_code: "reused", source_href: null, run: { id: runId, status: "succeeded", error: null } }], next_before_id: null }); return Response.json(url.includes("preparation") ? preparation(false) : page(url.includes("run_id=") ? [receipt()] : [], null, false)); });
    vi.stubGlobal("fetch", fetcher); render(<AiIssueEventRuns projectId="project" eventRowId={31} />); open(); await screen.findByText("本条异常暂无运行记录。"); expect(fetcher.mock.calls.some(call => String(call[0]).includes("ai-issue-event-history"))).toBe(false); fireEvent.click(screen.getByText("自动触发记录", { selector: "summary" })); fireEvent.click(await screen.findByRole("button", { name: "查看关联运行回执" })); expect(await screen.findByText("原建议：新建问题")).toBeVisible(); expect(fetcher.mock.calls.some(call => call[0] === `${base}?run_id=${runId}`)).toBe(true); expect(fetcher.mock.calls.every(call => call[1]?.method !== "POST")).toBe(true);
  });
  it("refreshes the same-page Issue list after a completed automatic application without asking for confirmation", async () => {
    const onIssueChanged = vi.fn(async () => undefined), original = receipt({ write_execution: { route: "direct", application_id: "applied", reason_label: "按原登记自动办理" } }); let generated = false;
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => { if (init?.method === "POST") { generated = true; return Response.json(original); } return Response.json(String(input).includes("preparation") ? preparation() : page(generated ? [original] : [])); })); render(<AiIssueEventRuns projectId="project" eventRowId={31} onIssueChanged={onIssueChanged} />); open(); fireEvent.click(await screen.findByRole("button", { name: "生成问题建议" })); expect(await screen.findByText("原建议：新建问题")).toBeVisible(); await waitFor(() => expect(onIssueChanged).toHaveBeenCalledWith([])); expect(screen.getAllByText("AI 自动办理已完成：按原登记自动办理")).toHaveLength(2); expect(screen.queryByRole("button", { name: "一次确认并办理" })).not.toBeInTheDocument();
  });
  it.each(["confirm", "exception"])("preserves automatic-write fallback reasons in the original run: %s", async route => {
    const original = receipt({ write_execution: { route, reason_label: "原登记或当前来源未满足自动办理条件" } });
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async input => Response.json(String(input).includes("preparation") ? preparation(false) : page([original], null, false)))); render(<AiIssueEventRuns projectId="project" eventRowId={31} />); open();
    expect(await screen.findByText(new RegExp(`${route === "confirm" ? "已转逐次确认" : "自动办理遇到例外"}：原登记或当前来源未满足自动办理条件`))).toBeVisible(); fireEvent.click(screen.getByRole("button", { name: "查看本次建议与回执" })); expect(await screen.findByText("原建议：新建问题")).toBeVisible(); expect(screen.getAllByText(/原登记或当前来源未满足自动办理条件/)).toHaveLength(2); expect(screen.queryByText(/AI 自动办理已完成/)).not.toBeInTheDocument();
  });
  it("loads shadow preparation on demand without exposing a generation or creation action", async () => {
    const fetcher = vi.fn<typeof fetch>(async input => Response.json(String(input).includes("preparation") ? preparation(false) : page([], null, false)));
    vi.stubGlobal("fetch", fetcher); render(<AiIssueEventRuns projectId="project" eventRowId={31} />);
    expect(fetcher).not.toHaveBeenCalled(); open();
    expect(await screen.findByText("此能力尚未开放生成，当前可核对资料和回查原运行。")).toBeVisible();
    expect(screen.queryByRole("button", { name: "生成问题建议" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("查看本次固定依据 · 1 项"));
    expect(screen.getByText(reference.excerpt)).toBeVisible();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it.each(["create_issue", "reuse_issue", "insufficient_evidence"])("shows the actual %s result and frozen source without claiming creation", async disposition => {
    const proposal = disposition === "create_issue" ? receipt().proposal : { disposition, title: null, description: null, severity: null, existing_issue_id: disposition === "reuse_issue" ? "issue-original" : null, citations: disposition === "reuse_issue" ? receipt().proposal.citations : [], open_questions: disposition === "insufficient_evidence" ? ["补充原始判据"] : [] };
    const saved = receipt({ proposal });
    const fetcher = vi.fn<typeof fetch>(async input => Response.json(String(input).includes("preparation") ? preparation() : page([saved])));
    vi.stubGlobal("fetch", fetcher); render(<AiIssueEventRuns projectId="project" eventRowId={31} />); open();
    fireEvent.click(await screen.findByRole("button", { name: "查看本次建议与回执" }));
    expect(await screen.findByText(disposition === "create_issue" ? "原建议：新建问题" : disposition === "reuse_issue" ? "建议沿用已有问题" : "资料不足，尚未形成建单建议")).toBeVisible();
    expect(fetcher.mock.calls.some(([url]) => String(url) === `${base}?run_id=${runId}`)).toBe(true);
    if (disposition === "reuse_issue") expect(screen.getByRole("link", { name: "查看建议复用的问题" })).toHaveAttribute("href", "/projects?project=project&tab=work-items&entity_id=issue-original");
    if (disposition === "insufficient_evidence") expect(screen.getByText("待补：补充原始判据")).toBeVisible();
    expect(screen.queryByRole("button", { name: /创建问题|撤回/ })).not.toBeInTheDocument();
  });

  it("retries an unknown outcome with the identical request and then loads its original receipt", async () => {
    const posts: string[] = [];
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      if (init?.method === "POST") { posts.push(String(init.body)); if (posts.length === 1) throw new Error("连接中断"); return Response.json(receipt()); }
      return Response.json(String(input).includes("preparation") ? preparation() : page(String(input).includes("run_id") || posts.length > 1 ? [receipt()] : []));
    });
    vi.stubGlobal("fetch", fetcher); render(<AiIssueEventRuns projectId="project" eventRowId={31} />); open();
    fireEvent.click(await screen.findByRole("button", { name: "生成问题建议" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("连接中断");
    expect(screen.getByRole("button", { name: "核对资料并刷新记录" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "生成问题建议" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "沿原请求核对结果" }));
    expect(await screen.findByText("原建议：新建问题")).toBeVisible();
    expect(posts).toHaveLength(2); expect(posts[0]).toBe(posts[1]);
    expect(JSON.parse(posts[0])).toEqual({ request_id: expect.any(String), event_row_id: 31, expected_digest: "a".repeat(64) });
  });

  it("uses the saved request for lease recovery and keeps its original source digest", async () => {
    const historical = receipt({ status: "degraded", error_code: "APPLICATION_RUN_LEASE_EXPIRED", proposal: null, source_digest: "b".repeat(64) });
    let posted: object | undefined;
    const fetcher = vi.fn<typeof fetch>(async (input, init) => { if (init?.method === "POST") { posted = JSON.parse(String(init.body)); return Response.json(receipt()); } return Response.json(String(input).includes("preparation") ? preparation() : page([historical])); });
    vi.stubGlobal("fetch", fetcher); render(<AiIssueEventRuns projectId="project" eventRowId={31} />); open();
    fireEvent.click(await screen.findByRole("button", { name: "查看本次建议与回执" }));
    fireEvent.click(await screen.findByRole("button", { name: "沿原请求核对或恢复" }));
    await waitFor(() => expect(posted).toEqual({ request_id: requestId, event_row_id: 31, expected_digest: "b".repeat(64) }));
  });

  it("uses the shared cancellation endpoint for an owned running request", async () => {
    let stopped = false;
    const fetcher = vi.fn<typeof fetch>(async input => { if (String(input).endsWith("/cancel")) { stopped = true; return Response.json({ cancelled: true }); } return Response.json(String(input).includes("preparation") ? preparation() : page([receipt({ status: stopped ? "degraded" : "running", error_code: stopped ? "APPLICATION_RUN_CANCELLED" : null, proposal: null })])); });
    vi.stubGlobal("fetch", fetcher); render(<AiIssueEventRuns projectId="project" eventRowId={31} />); open();
    fireEvent.click(await screen.findByRole("button", { name: "查看本次建议与回执" }));
    fireEvent.click(await screen.findByRole("button", { name: "停止本次运行" }));
    expect(await screen.findByText("本次运行已停止。")).toBeVisible();
    expect(fetcher.mock.calls.some(([url, init]) => String(url) === `/api/ai/runs/${runId}/cancel` && init?.method === "POST")).toBe(true);
    expect(screen.queryByRole("button", { name: "沿原请求核对或恢复" })).not.toBeInTheDocument();
  });

  it("can discover and stop the original run while the generation response is still pending", async () => {
    let posted = false, resolve!: (response: Response) => void;
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input);
      if (path.endsWith("/cancel")) return Response.json({ cancelled: true });
      if (init?.method === "POST") { posted = true; return new Promise(done => { resolve = done; }); }
      return Response.json(path.includes("preparation") ? preparation() : page(posted ? [receipt({ status: "running", proposal: null })] : []));
    });
    vi.stubGlobal("fetch", fetcher); render(<AiIssueEventRuns projectId="project" eventRowId={31} />); open();
    fireEvent.click(await screen.findByRole("button", { name: "生成问题建议" }));
    expect(await screen.findByText("正在核对本次请求，可在原运行中查看预算和进度。")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "核对资料并刷新记录" }));
    fireEvent.click(await screen.findByRole("button", { name: "查看本次建议与回执" }));
    fireEvent.click(await screen.findByRole("button", { name: "停止本次运行" }));
    await waitFor(() => expect(fetcher.mock.calls.some(([url]) => String(url) === `/api/ai/runs/${runId}/cancel`)).toBe(true));
    await act(async () => resolve(Response.json(receipt({ status: "degraded", error_code: "APPLICATION_RUN_CANCELLED", proposal: null }))));
  });

  it("preserves UUID history pagination and ignores a pending response after source switching", async () => {
    let resolve!: (value: Response) => void;
    const fetcher = vi.fn<typeof fetch>(async input => {
      const path = String(input);
      if (path.includes("preparation")) return Response.json(preparation());
      if (path.includes("before_id")) return new Promise(done => { resolve = done; });
      return Response.json(path.includes("event_row_id=32") ? page([]) : page([receipt()], runId));
    });
    vi.stubGlobal("fetch", fetcher); const view = render(<AiIssueEventRuns projectId="project" eventRowId={31} />); open();
    fireEvent.click(await screen.findByRole("button", { name: "更早的运行记录" }));
    await waitFor(() => expect(fetcher.mock.calls.some(([url]) => String(url) === `${base}?event_row_id=31&before_id=${runId}`)).toBe(true));
    view.rerender(<AiIssueEventRuns projectId="project" eventRowId={32} />); open();
    expect(await screen.findByText("本条异常暂无运行记录。")).toBeVisible();
    await act(async () => resolve(Response.json(page([receipt({ run_id: "old-extra" })]))));
    expect(screen.queryByRole("button", { name: "查看本次建议与回执" })).not.toBeInTheDocument();
  });
  it.each([
    ["trial_candidate", "试运行候选", "当时已固定试运行政策和项目授权，仍需当前具名办理"],
    ["evidence_only", "仅保留建议证据", "生成时试运行适配尚未就绪，仅保留建议证据"],
    ["not_recorded", "未留存", "此历史运行未固定生成时政策与授权，不补记为试运行候选"],
  ])("shows the original %s generation basis separately from today's shadow readiness", async (status, label, reason) => {
    const generation_binding = { status, capture_kind: status === "not_recorded" ? null : status, binding_id: "RAW_BINDING_ID", principal_id: "RAW_PRINCIPAL_ID", reason_code: "RAW_REASON_CODE", reason, created_at: status === "not_recorded" ? null : "2026-09-20T12:00:00Z", policy_id: "RAW_POLICY_ID", scope_revision_id: "RAW_SCOPE_ID", policy: status === "not_recorded" ? null : { id: "RAW_POLICY_ID", revision: 3, mode: "tiered" }, scope: status === "not_recorded" ? null : { id: "RAW_SCOPE_ID", revision: 7, enabled: true }, rollout: "live", trial_ready: status === "trial_candidate" };
    const saved = receipt({ generation_binding });
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async input => Response.json(String(input).includes("preparation") ? preparation(false) : page([saved], null, false))));
    render(<AiIssueEventRuns projectId="project" eventRowId={31} />); open();
    expect(await screen.findByText(`生成时：${label}`)).toBeVisible();
    expect(screen.getByText("此能力尚未开放生成，当前可核对资料和回查原运行。")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "查看本次建议与回执" }));
    fireEvent.click(await screen.findByText(`生成时依据 · ${label}`));
    expect(screen.getByText(reason)).toBeVisible();
    expect(screen.getByText("这是原生成时的记录；当前能否办理须另行核对，不代表已取得自动写入资格。")).toBeVisible();
    if (status !== "not_recorded") { expect(screen.getByText("第 3 版")).toBeVisible(); expect(screen.getByText("第 7 版")).toBeVisible(); expect(screen.getByText("依据留存时间").nextElementSibling?.firstElementChild).toHaveAttribute("dateTime", "2026-09-20T12:00:00Z"); }
    else expect(screen.queryByText("当时政策版本")).not.toBeInTheDocument();
    expect(screen.queryByText(/RAW_/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "生成问题建议" })).not.toBeInTheDocument();
  });
  it("does not backfill a legacy run with today's live preparation", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async input => Response.json(String(input).includes("preparation") ? preparation(true) : page([receipt()]))));
    render(<AiIssueEventRuns projectId="project" eventRowId={31} />); open();
    expect(await screen.findByRole("button", { name: "生成问题建议" })).toBeVisible();
    expect(screen.getByText("生成时：未留存")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "查看本次建议与回执" }));
    fireEvent.click(await screen.findByText("生成时依据 · 未留存"));
    expect(screen.getByText("此历史运行未留存生成时政策与项目授权，不补记为试运行候选。")).toBeVisible();
    expect(screen.queryByText("生成时：试运行候选")).not.toBeInTheDocument();
  });

});
