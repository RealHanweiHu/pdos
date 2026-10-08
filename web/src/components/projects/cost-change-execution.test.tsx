import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProfessionalChangeRoute } from "./professional-change-route";

const route = { basis: { ready: true }, digest: "current", route: { id: "route", reason: "报价适用范围" }, routed_ecr: { id: "ecr", code: "ECR-COST", title: "议价实施", status: "approved" }, ecrs: [] };
const execution = { scope: { id: "scope", revision_number: 1, coverage: "文件协同", exclusions: "实际收益另验" }, required_count: 1, all_required_verified: true, scope_gaps: [], source_changes: [], historical_binding_count: 0, read_at: "2026-10-01", counts: { verified: 1 }, people: [{ id: "peer", display_name: "独立确认人" }], items: [{ item: { key: "key", kind: "document", action: "coordination", snapshot: { filename: "报价.pdf" } }, required: true, status: "verified", binding_id: "binding", task: { id: "task", title: "议价实施文件核对", status: "done", assignee_user_id: "owner" }, result: { id: "result", revision_number: 1, created_by_user_id: "owner", reviewer_user_id: "peer" }, result_scope: { completed_scope: "文件范围已回应", excluded_scope: "品质与真实降本未覆盖", criteria_response: "判据逐一回应", follow_up: "按原流程核对实际成本" }, confirmation: { outcome: "verified", created_by_user_id: "peer", note: "具名独立确认原范围" }, evidence: [], gaps: [] }] };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
async function openRoute() {
  const user = userEvent.setup();
  await user.click(screen.getByText("转入正式工程变更"));
  await screen.findByText("本资料已转入");
  await user.click(screen.getByText("获批范围执行汇总"));
  await screen.findByText(/本版要求执行的各条目均已有独立确认/);
  return user;
}
function mount(sourceId = "alternative") {
  return render(<ProfessionalChangeRoute projectId="project" sourceId={sourceId} kind="cost_alternative" canEdit={false}/>);
}

describe("cost alternative execution return path", () => {
  it("shows exact approved scope and actual named results with a working cross-page action link", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(Response.json(route)).mockResolvedValueOnce(Response.json(execution));
    vi.stubGlobal("fetch", fetcher);
    mount();
    await openRoute();
    expect(fetcher.mock.calls[1]).toEqual(["/api/projects/project/changes/ecrs/ecr/execution-overview", { cache: "no-store" }]);
    expect(screen.getByText("已完成：文件范围已回应")).toBeVisible();
    expect(screen.getByText("未覆盖：品质与真实降本未覆盖")).toBeVisible();
    expect(screen.getByRole("link", { name: "前往本条任务、原证据与结果办理" })).toHaveAttribute("href", "/projects?project=project&tab=engineering&change_ecr_id=ecr&change_task_id=task&change_binding_id=binding#ecr-ecr");
    expect(screen.getByText(/费用差额仍为备选预期/)).toBeVisible();
  });

  it("refreshes source and execution together, removing the valid-confirmation status after drift", async () => {
    const invalid = { ...execution, all_required_verified: false, scope_gaps: ["获批来源需重核"], source_changes: [{ kind: "cost_alternative", id: "alternative", blocking: true, before: { source: { title: "同物料议价方案", revision_number: 1 } } }], items: [{ ...execution.items[0], status: "evidence_gaps", gaps: ["获批专业来源已有变化"] }] };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(Response.json(route)).mockResolvedValueOnce(Response.json(execution)).mockResolvedValueOnce(Response.json(route)).mockResolvedValueOnce(Response.json(invalid)));
    mount();
    const user = await openRoute();
    await user.click(screen.getByRole("button", { name: "刷新来源与办理回执" }));
    await screen.findByText("获批来源需重核");
    expect(screen.queryByText(/本版要求执行的各条目均已有独立确认/)).not.toBeInTheDocument();
    expect(screen.getByText(/原确认：独立确认人/)).toBeVisible();
    await user.click(screen.getByText("获批来源的当前变化（1）"));
    expect(screen.getByText(/降本方案 · 同物料议价方案/)).toBeVisible();
  });

  it("clears denied route and execution records and allows a later successful refresh", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(Response.json(route)).mockResolvedValueOnce(Response.json(execution)).mockResolvedValueOnce(Response.json({ detail: { message: "当前来源不可读" } }, { status: 403 })).mockResolvedValueOnce(Response.json(route)));
    mount();
    const user = await openRoute();
    await user.click(screen.getByRole("button", { name: "刷新来源与办理回执" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("当前来源不可读");
    expect(screen.queryByText("ECR-COST · 议价实施")).not.toBeInTheDocument();
    expect(screen.queryByText("获批范围执行汇总")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "刷新来源与办理回执" }));
    await screen.findByText("ECR-COST · 议价实施");
  });

  it("resets route state when switching to a different source, including a late old request", async () => {
    let resolveOld: (response: Response) => void = () => undefined;
    const old = new Promise<Response>(resolve => { resolveOld = resolve; });
    const fetcher = vi.fn().mockReturnValueOnce(old).mockResolvedValueOnce(Response.json({ basis: { ready: true }, route: null, ecrs: [] }));
    vi.stubGlobal("fetch", fetcher);
    const view = mount("old");
    const user = userEvent.setup();
    await user.click(screen.getByText("转入正式工程变更"));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    view.rerender(<ProfessionalChangeRoute projectId="project" sourceId="new" kind="cost_alternative" canEdit={false}/>);
    await user.click(screen.getByText("转入正式工程变更"));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    resolveOld(Response.json(route));
    await waitFor(() => expect(screen.queryByText("ECR-COST · 议价实施")).not.toBeInTheDocument());
    expect(screen.queryByText("获批范围执行汇总")).not.toBeInTheDocument();
  });
});
