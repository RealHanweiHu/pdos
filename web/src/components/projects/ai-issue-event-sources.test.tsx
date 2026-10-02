import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AiIssueEventSources } from "./ai-issue-event-sources";
import { IssuePanel } from "./project-work-items";

const base = "/api/projects/project/ai-issue-event-sources?limit=20";
function item(id = 31, overrides: object = {}) { return { event_row_id: id, event_id: "internal-event", event_type: "TEST_FAILED", event_at: "2026-09-27T12:00:00Z", source_kind: "test_failure", title: "样机耐久测试失败", source_status: "current", reason: "失败记录与原问题一致", existing_issue: { id: "issue", title: "耐久问题", status: "analysis", href: "/projects?project=project&tab=work-items&entity_id=issue" }, source_href: "/projects?project=project&tab=test-runs", summary: [{ label: "测试结果", value: "未通过" }], source: { private_field: "RAW_SOURCE_NOT_FOR_UI" }, source_digest: "HASH_NOT_FOR_UI", ...overrides }; }
function page(items = [item()], next: number | null = null) { return { items, next_before: next, notice: "来源按当前有权资料核对。" }; }
function open() { fireEvent.click(screen.getByText("异常来源与已有问题")); }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("issue event sources", () => {
  it("is available in an empty issue panel, loads on demand, and reuses the actual issue link", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json(page()));
    vi.stubGlobal("fetch", fetcher);
    render(<IssuePanel projectId="project" busy={false} issues={[]} onCreate={async () => false} onTransition={async () => false} />);
    expect(screen.getByText("还没有问题。")).toBeVisible();
    expect(fetcher).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "查看异常处理记录" })); open();
    expect(await screen.findByText("样机耐久测试失败")).toBeVisible();
    expect(fetcher.mock.calls[0][0]).toBe(base);
    expect(screen.getByRole("link", { name: "继续办理已有问题：耐久问题" })).toHaveAttribute("href", "/projects?project=project&tab=work-items&entity_id=issue");
    expect(screen.getByText("已有问题 · 分析中")).toBeVisible();
    fireEvent.click(screen.getByText("来源要点"));
    expect(screen.getByText("未通过")).toBeVisible();
    expect(screen.queryByText("RAW_SOURCE_NOT_FOR_UI")).not.toBeInTheDocument();
    expect(screen.queryByText("HASH_NOT_FOR_UI")).not.toBeInTheDocument();
    expect(screen.getByText("核对测试失败和物料异常，沿已有问题继续办理，避免重复建单。")).toBeVisible();
  });

  it("paginates changed and unavailable sources without losing earlier rows or showing unsafe links", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(page([item(31, { source_status: "changed", reason: "测试结果已有后续修订" })], 31))).mockResolvedValueOnce(Response.json(page([item(20, { source_kind: "material_exception", event_type: "NPI_RECORD_CHANGED", title: "批次物料短缺", source_status: "unavailable", reason: "原分配记录当前不可读取", existing_issue: null, source_href: "javascript:alert(1)", summary: [] })])));
    vi.stubGlobal("fetch", fetcher);
    render(<AiIssueEventSources projectId="project" />); open();
    expect(await screen.findByText("来源已有变化")).toHaveClass("text-primary");
    fireEvent.click(screen.getByRole("button", { name: "更早的异常来源" }));
    expect(await screen.findByText("批次物料短缺")).toBeVisible();
    expect(screen.getByText("样机耐久测试失败")).toBeVisible();
    expect(screen.getByText("来源暂不可核对")).toHaveClass("text-primary");
    expect(screen.getAllByRole("link", { name: "查看来源记录" })).toHaveLength(1);
    expect(fetcher.mock.calls[1][0]).toBe(`${base}&before=31`);
    expect(screen.queryByRole("button", { name: "更早的异常来源" })).not.toBeInTheDocument();
  });

  it("ignores a previous project's pending response", async () => {
    let resolve!: (value: Response) => void;
    const fetcher = vi.fn<typeof fetch>().mockImplementationOnce(() => new Promise(done => { resolve = done; })).mockResolvedValueOnce(Response.json(page([])));
    vi.stubGlobal("fetch", fetcher);
    const view = render(<AiIssueEventSources projectId="project" />); open();
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    view.rerender(<AiIssueEventSources projectId="other" />); open();
    expect(await screen.findByText("暂无可回查的异常来源。")).toBeVisible();
    await act(async () => resolve(Response.json(page())));
    expect(screen.queryByText("样机耐久测试失败")).not.toBeInTheDocument();
    expect(fetcher.mock.calls[1][0]).toBe("/api/projects/other/ai-issue-event-sources?limit=20");
  });

  it("preserves a plain-text backend cursor conflict so the user can refresh", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(page([item()], 31))).mockResolvedValueOnce(Response.json({ detail: "分页位置已不可用，请刷新后重试" }, { status: 409 })).mockResolvedValueOnce(Response.json(page([])));
    vi.stubGlobal("fetch", fetcher);
    render(<AiIssueEventSources projectId="project" />); open();
    await screen.findByText("样机耐久测试失败");
    fireEvent.click(screen.getByRole("button", { name: "更早的异常来源" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("分页位置已不可用，请刷新后重试");
    fireEvent.click(screen.getByRole("button", { name: "刷新异常来源" }));
    expect(await screen.findByText("暂无可回查的异常来源。")).toBeVisible();
    expect(fetcher.mock.calls[2][0]).toBe(base);
  });

  it("clears cached source links after access is revoked and allows a clean retry", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(page())).mockResolvedValueOnce(Response.json({ detail: { message: "项目资料权限已变更" } }, { status: 403 })).mockResolvedValueOnce(Response.json(page([])));
    vi.stubGlobal("fetch", fetcher);
    render(<AiIssueEventSources projectId="project" />); open();
    await screen.findByText("样机耐久测试失败");
    fireEvent.click(screen.getByRole("button", { name: "刷新异常来源" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("项目资料权限已变更");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "刷新异常来源" }));
    expect(await screen.findByText("暂无可回查的异常来源。")).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
