import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IssueQualityProgress } from "./issue-quality-progress";
import { IssueQualityLinks } from "./issue-quality-links";

function page(ncrId = "ncr") {
  return {
    ncr: { id: ncrId, code: "NCR-1", status: "verification", effectiveness_criteria: "零失效", observation_due_at: "2026-09-28T12:00:00Z" },
    server_time: "2026-09-28T13:00:00Z", people: { engineer: "措施责任人", quality: "独立品质人员" },
    root_causes: [{ id: "root", version: 1, status: "draft", analyst_user_id: "engineer", analysis: "实测待审核", root_cause: "待证实判断" }],
    actions: [{ id: "action", action_type: "corrective", status: "completed", owner_user_id: "engineer", description: "追加复测", completion_summary: "实际完成说明" }],
    reviews: [
      { id: "review1", review_number: 1, result: "ineffective", reviewer_user_id: "quality", actual_result: "首次仍有失效" },
      { id: "review2", review_number: 2, result: "effective", reviewer_user_id: "quality", actual_result: "第二次复测有效" },
    ],
    followup_action_ids: ["action"],
    record_evidence: { action: [{ kind: "event", reference: "event-1", available: true, value: { event_type: "TEST_RUN_RECORDED", payload: { result: "passed" } } }], review1: [{ kind: "document", reference: "missing", available: false }], review2: [{ kind: "test_run", reference: "test", available: true, value: { id: "test", test_case_id: "case", run_number: 3, status: "passed", draft_state: "confirmed", metrics: [{ name: "leak_rate", value: 0.05, unit: "sccm", target: 0.1, verdict: "pass" }] } }] },
  };
}
function open() { fireEvent.click(screen.getByText("回查整改、复测与独立验证证据", { selector: "summary" })); }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Issue quality evidence feedback", () => {
  it("opens evidence from the original Issue relation without triggering mutations or eager NCR loads", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [{ id: "link", reason: "来自原问题", issue: { id: "issue", title: "原问题", status: "open" }, ncr: { id: "ncr", code: "NCR-1", status: "action" }, snapshot: {}, retraction: null }], people: {} })).mockResolvedValueOnce(Response.json(page())); vi.stubGlobal("fetch", fetcher);
    render(<IssueQualityLinks projectId="project" issueId="issue"/>);
    fireEvent.click(screen.getByText("质量升级与 NCR/CAPA 关联", { selector: "summary" }));
    fireEvent.click(await screen.findByText(/NCR-1 · 有效关联/, { selector: "summary" }));
    expect(fetcher).toHaveBeenCalledTimes(1); open();
    await screen.findByText(/NCR-1 · 有效性验证/);
    expect(fetcher.mock.calls.map(call => call[0])).toEqual(["/api/projects/project/quality/issue-links?issue_id=issue&offset=0", "/api/projects/project/quality/ncrs/ncr/workspace"]);
    expect(screen.getByRole("link", { name: "打开原 NCR/CAPA" })).toHaveAttribute("href", "/projects?project=project&tab=quality&ncr=ncr");
  });

  it("lazily reads the linked NCR and keeps completion, failed/effective reviews and closure separate", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json(page())); vi.stubGlobal("fetch", fetcher);
    render(<IssueQualityProgress projectId="project" ncrId="ncr"/>); expect(fetcher).not.toHaveBeenCalled(); open();
    await screen.findByText(/NCR-1 · 有效性验证/);
    for (const label of ["纠正、预防与补充措施（1）", "独立有效性验证历史（2）", "根因调查与独立审核（1）"]) fireEvent.click(screen.getByText(label));
    expect(screen.getByText(/措施已完成/)).toBeVisible(); expect(screen.getByText(/验证无效，需补充措施/)).toBeVisible(); expect(screen.getByText(/第 2 次 · 验证有效/)).toBeVisible(); expect(screen.getByText(/待独立审核/)).toBeVisible(); expect(screen.queryByText(/NCR-1 · NCR 已关闭/)).not.toBeInTheDocument();
    expect(screen.getByText("最近一次无效复核后新增的补充措施")).toBeVisible();
    for (const summary of screen.getAllByText("所用证据当前记录（1）")) fireEvent.click(summary);
    expect(screen.getByText(/原事件：TEST_RUN_RECORDED/)).toBeVisible(); expect(screen.getByText(/原证据当前不可用/)).toBeVisible();
    expect(screen.getByText("leak_rate")).toBeVisible(); expect(screen.getByText("0.05")).toBeVisible();
    expect(fetcher).toHaveBeenCalledTimes(1); expect(fetcher.mock.calls[0]).toEqual(["/api/projects/project/quality/ncrs/ncr/workspace", { cache: "no-store" }]);
  });
  it("removes cached evidence when refresh is denied and allows retry", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(page())).mockResolvedValueOnce(Response.json({ detail: { message: "当前人员没有此质量操作权限" } }, { status: 403 })).mockResolvedValueOnce(Response.json(page())); vi.stubGlobal("fetch", fetcher);
    render(<IssueQualityProgress projectId="project" ncrId="ncr"/>); open(); await screen.findByText(/NCR-1 · 有效性验证/);
    fireEvent.click(screen.getByRole("button", { name: "刷新质量证据" })); expect(await screen.findByRole("alert")).toHaveTextContent("当前人员没有此质量操作权限"); expect(screen.queryByText(/首次仍有失效/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "刷新质量证据" })); await screen.findByText(/NCR-1 · 有效性验证/);
  });
  it("ignores a previous project's delayed response and rejects a mismatched NCR", async () => {
    let resolve!: (value: Response) => void;
    const fetcher = vi.fn<typeof fetch>().mockImplementationOnce(() => new Promise(done => { resolve = done; })).mockResolvedValueOnce(Response.json(page("other-ncr"))).mockResolvedValueOnce(Response.json(page("wrong"))); vi.stubGlobal("fetch", fetcher);
    const view = render(<IssueQualityProgress projectId="project" ncrId="ncr"/>); open(); await waitFor(() => expect(resolve).toBeDefined());
    view.rerender(<IssueQualityProgress projectId="other" ncrId="other-ncr"/>); open(); await screen.findByText(/NCR-1 · 有效性验证/);
    await act(async () => resolve(Response.json({ ...page(), ncr: { id: "ncr", code: "OLD-PROJECT", status: "closed" } })));
    expect(screen.queryByText(/OLD-PROJECT/)).not.toBeInTheDocument(); expect(fetcher.mock.calls[1][0]).toBe("/api/projects/other/quality/ncrs/other-ncr/workspace");
    fireEvent.click(screen.getByRole("button", { name: "刷新质量证据" })); expect(await screen.findByRole("alert")).toHaveTextContent("质量进展返回不完整"); expect(screen.queryByText(/NCR-1/)).not.toBeInTheDocument();
  });
});
