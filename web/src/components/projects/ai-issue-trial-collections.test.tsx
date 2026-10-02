import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AiIssueTrialCollections } from "./ai-issue-trial-collections";
const protocol = "44444444-4444-4444-8444-444444444444", id = "55555555-5555-4555-8555-555555555555", older = "66666666-6666-4666-8666-666666666666", base = `/api/projects/project/ai-issue-trials/${protocol}/collections`;
function summary(identity = id, total = 0) { return { id: identity, created_at: "2026-09-27T12:00:00Z", actor_name: "采集负责人", as_of: "2026-09-27T12:00:00Z", total_runs: total, matching_runs: Math.max(total - 1, 0), qualification_granted: false }; }
function counts(total = 0) { return { total_runs: total, succeeded_runs: Math.max(total - 1, 0), failed_runs: total ? 1 : 0, pending_runs: 0, proposal_runs: Math.max(total - 1, 0), insufficient_runs: total > 1 ? 1 : 0, created_issues: 0, reused_issues: 0, same_source_applied_runs: 0, declined_runs: 0, reopened_runs: 0, unhandled_proposals: Math.max(total - 1, 0), withdrawn_issues: 0, human_edited_issues: 0, trial_candidates: 0, evidence_only_runs: 0, unrecorded_bindings: total }; }
function sample(index: number) { return { run_id: `run-${index}`, created_at: "2026-09-21T12:00:00Z", status: index ? "succeeded" : "failed", source_title: `原来源 ${index + 1}`, source_href: index ? null : "/projects?project=project&tab=test-runs", result_id: null, disposition: index ? "insufficient_evidence" : null, binding_kind: "not_recorded", review_state: "unreviewed", application_kind: null, same_source_applied: false, withdrawn: false, human_edited: false, match: { matches_protocol: index > 0, reasons: index ? [] : [{ code: "binding_missing", message: "未留存原生成版本，无法匹配" }], followup_complete: true }, provenance: { provider_verified: false, provenance_verified: false, reasons: [{ code: "call_not_verified", message: "调用原件尚未核实" }] } }; }
function detail(identity = id, total = 0) { return { ...summary(identity, total), window_start: "2026-09-20T00:00:00Z", window_end: "2026-09-22T00:00:00Z", counts: counts(total), matching_counts: counts(Math.max(total - 1, 0)), criteria: { minimum_handled_runs: { actual: 0, required: 12, met: false }, followup_complete: true, confirmation: { numerator: 0, denominator: 0, basis_points: null, required: 9000, met: null }, withdrawal: { numerator: 0, denominator: 0, basis_points: null, required: 500, met: null } }, formula: { handled: "原运行自身应用或当前不采纳，计一次", confirmation: "确认分子按原登记口径，分母为匹配运行办理数", retained_original: "未撤回或人工修改的自身应用", withdrawal: "撤回的自建问题数 / 匹配运行自建问题数", same_source: "其他运行同源应用不计本运行确认", sampling: "全量采集不代表已执行持续抽检" }, blockers: [{ code: "insufficient_handled", message: "匹配版本的办理数量不足" }], items: Array.from({ length: total }, (_, index) => sample(index)), notice: "固定原登记的完整窗口，不授予资格。" }; }
function history(items = [summary()], canCollect = true, next: string | null = null) { return { items, can_collect: canCollect, next_before_id: next }; }
function open() { fireEvent.click(screen.getByText("按原登记采集")); }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
describe("Issue registered trial collections", () => {
  it("reads only on demand and never collects for view-only users", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json(history([], false))); vi.stubGlobal("fetch", fetcher);
    render(<AiIssueTrialCollections projectId="project" protocolId={protocol} />); expect(fetcher).not.toHaveBeenCalled(); open();
    expect(await screen.findByText(/当前仅可回查采集记录/)).toBeVisible(); expect(screen.getByRole("button", { name: "采集当前记录" })).toBeDisabled();
    expect(fetcher).toHaveBeenCalledTimes(1); expect(fetcher.mock.calls[0][0]).toBe(`${base}?limit=20`);
  });
  it("pages original receipts and the complete sample set with separate matching counts and unknown ratios", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(history([summary(id, 21)], false, id))).mockResolvedValueOnce(Response.json(history([summary(older)], false))).mockResolvedValueOnce(Response.json(detail(id, 21))); vi.stubGlobal("fetch", fetcher);
    render(<AiIssueTrialCollections projectId="project" protocolId={protocol} />); open(); fireEvent.click(await screen.findByRole("button", { name: "更早的采集记录" }));
    await waitFor(() => expect(screen.getAllByRole("button", { name: "查看原采集" })).toHaveLength(2)); expect(fetcher.mock.calls[1][0]).toBe(`${base}?limit=20&before_id=${id}`);
    fireEvent.click(screen.getAllByRole("button", { name: "查看原采集" })[0]); expect(await screen.findByText("全窗口样本 · 共 21 条，当前第 1 / 2 页（每页 20 条）")).toBeVisible();
    fireEvent.click(screen.getByText("全窗口 21 个原请求 · 匹配原登记 20 个")); expect(screen.getByRole("columnheader", { name: "全窗口" })).toBeVisible(); expect(screen.getByRole("columnheader", { name: "匹配版本" })).toBeVisible(); expect(screen.getAllByText("—")).toHaveLength(2); fireEvent.click(screen.getByText("原采集统计口径")); expect(screen.getByText("全量采集不代表已执行持续抽检")).toBeVisible();
    expect(screen.getByText(/运行失败 · 尚无建议结果/)).toBeVisible(); expect(screen.getByText("未留存原生成版本，无法匹配")).toBeVisible(); expect(screen.getByText("匹配版本的办理数量不足")).toBeVisible(); expect(screen.getByText(/服务商调用真实性尚未核验/)).toBeVisible();
    expect(screen.getByRole("link", { name: "查看来源记录" })).toHaveAttribute("href", "/projects?project=project&tab=test-runs"); expect(screen.queryByText("原来源 21")).not.toBeInTheDocument(); fireEvent.click(screen.getByRole("button", { name: "下一页采集样本" })); expect(screen.getByText("原来源 21")).toBeVisible(); expect(screen.queryByText("原来源 1")).not.toBeInTheDocument(); expect(fetcher).toHaveBeenCalledTimes(3);
  });
  it.each(["network", "concurrency"])("preserves the exact request through %s uncertainty and never submits client as_of", async failure => {
    const posts: string[] = []; vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (_url, init) => {
      if (init?.method === "POST") { posts.push(String(init.body)); if (posts.length === 1) { if (failure === "network") throw new Error("连接中断"); return Response.json({ detail: { code: "COLLECTION_RETRY", message: "正在更新，请沿原请求核对" } }, { status: 409 }); } return Response.json({ collection: detail(), replayed: true }); }
      return Response.json(history([]));
    }));
    render(<AiIssueTrialCollections projectId="project" protocolId={protocol} />); open(); await screen.findByText("尚无原登记采集记录。"); fireEvent.click(screen.getByRole("button", { name: "采集当前记录" })); const retry = await screen.findByRole("button", { name: "沿原请求核对采集结果" }); expect(screen.getByRole("button", { name: "刷新采集历史" })).toBeDisabled(); fireEvent.click(retry);
    expect(await screen.findByText("已核对原采集回执，没有重复保存。")).toBeVisible(); expect(posts).toHaveLength(2); expect(posts[0]).toBe(posts[1]); expect(JSON.parse(posts[0])).toEqual({ request_id: expect.any(String) });
  });
  it.each(["原窗口尚未结束，请在窗口结束后采集", "原窗口超过5000条，未保存部分结果"])("exposes the definite rejection: %s", async message => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(history([]))).mockResolvedValueOnce(Response.json({ detail: message }, { status: 409 })); vi.stubGlobal("fetch", fetcher); render(<AiIssueTrialCollections projectId="project" protocolId={protocol} />); open(); await screen.findByText("尚无原登记采集记录。"); fireEvent.click(screen.getByRole("button", { name: "采集当前记录" })); expect(await screen.findByRole("alert")).toHaveTextContent(message); expect(screen.queryByRole("button", { name: "沿原请求核对采集结果" })).not.toBeInTheDocument(); expect(screen.queryByRole("region", { name: "原登记采集详情" })).not.toBeInTheDocument(); expect(screen.getByRole("button", { name: "采集当前记录" })).toBeEnabled();
  });
  it("separates new operational requirements while keeping an old receipt's original blockers", async () => {
    const oldBlocker = { code: "sampling_evidence_missing", message: "原回执记载：持续抽检尚无执行回执" };
    const body = { ...detail(), blockers: [oldBlocker], operational_requirements: [{ code: "t0_continuous_sampling", message: "自动写入后按登记比例持续抽检" }] };
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(history())).mockResolvedValueOnce(Response.json(body)); vi.stubGlobal("fetch", fetcher);
    render(<AiIssueTrialCollections projectId="project" protocolId={protocol} />); open(); fireEvent.click(await screen.findByRole("button", { name: "查看原采集" }));
    const requirements = await screen.findByRole("region", { name: "自动写入后的运行要求" });
    expect(within(requirements).getByText("自动写入后按登记比例持续抽检")).toBeVisible(); expect(within(requirements).getByText("这些要求用于后续自动写入运行，不作为逐次确认办理的前置条件。")).toBeVisible();
    expect(screen.getByText(oldBlocker.message)).toBeVisible(); expect(within(requirements).queryByText(oldBlocker.message)).not.toBeInTheDocument();
  });
  it("ignores the prior protocol's late response and rejects an incomplete sample set", async () => {
    let resolve!: (value: Response) => void;
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(history())).mockImplementationOnce(() => new Promise(done => { resolve = done; })).mockResolvedValueOnce(Response.json(history([summary(older, 2)]))).mockResolvedValueOnce(Response.json({ ...detail(older, 2), items: [sample(0)] })); vi.stubGlobal("fetch", fetcher);
    const view = render(<AiIssueTrialCollections projectId="project" protocolId={protocol} />); open(); fireEvent.click(await screen.findByRole("button", { name: "查看原采集" })); await waitFor(() => expect(resolve).toBeDefined());
    view.rerender(<AiIssueTrialCollections projectId="project" protocolId={older} />); open(); await screen.findByRole("button", { name: "查看原采集" }); await act(async () => resolve(Response.json({ ...detail(), actor_name: "旧登记采集人" }))); expect(screen.queryByText("旧登记采集人 保存的原登记采集")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看原采集" })); expect(await screen.findByRole("alert")).toHaveTextContent("不会展示截断结果"); expect(screen.queryByRole("region", { name: "原登记采集详情" })).not.toBeInTheDocument();
  });
});
