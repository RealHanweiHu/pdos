import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FmeaDesignRules } from "./fmea-design-rules";

const page = () => ({ digest: "a".repeat(64), publication: { id: "publication" }, version: { version: 2, body: { title: "密封设计", design_function: "保持密封", failure_mode: "泄漏", control_gaps: "仅验证低压" } }, basis: "b".repeat(32), source_gaps: [], items: [], can_draft: true });
const open = () => fireEvent.click(screen.getByText("转为设计规则候选与专业审核", { selector: "summary" }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
describe("FMEA design-rule candidate", () => {
  it("requires scoped human content and saves a draft linked to the actual publication", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(page())).mockResolvedValueOnce(Response.json({ memory: { id: "memory", title: "密封规则", status: "draft" } })); vi.stubGlobal("fetch", fetcher);
    render(<FmeaDesignRules projectId="project" entryId="entry"/>); expect(fetcher).not.toHaveBeenCalled(); open();
    await screen.findByText("采用已发布 v2：密封设计");
    expect(screen.getByRole("button", { name: "保存设计规则候选" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("候选名称"), { target: { value: "密封规则" } });
    fireEvent.change(screen.getByLabelText("设计约束、方法与对应依据"), { target: { value: "验证泄漏率低于上限" } });
    fireEvent.change(screen.getByLabelText("适用产品、工况与不适用边界"), { target: { value: "只适用于低压；高压未验证" } });
    fireEvent.click(screen.getByRole("button", { name: "保存设计规则候选" }));
    expect(await screen.findByText("密封规则 · 待独立审核")).toBeVisible();
    expect(screen.getByRole("link", { name: "打开原知识候选与审核记录" })).toHaveAttribute("href", "/knowledge?project=project&memory=memory");
    const sent = JSON.parse(String(fetcher.mock.calls[1][1]?.body)); expect(sent).toEqual({ publication_id: "publication", expected_digest: "a".repeat(64), title: "密封规则", content: "验证泄漏率低于上限", applicability: "只适用于低压；高压未验证" });
    expect(fetcher.mock.calls[1][0]).toBe("/api/projects/project/quality/fmea/entry/design-rules");
    expect(screen.queryByRole("button", { name: "保存设计规则候选" })).not.toBeInTheDocument();
  });
  it("blocks unpublished and stale sources and reuses an existing publication's candidate", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ ...page(), publication: null, version: null, basis: null })).mockResolvedValueOnce(Response.json({ ...page(), source_gaps: ["ncr:changed"] })).mockResolvedValueOnce(Response.json({ ...page(), items: [{ id: "original", publication_id: "publication", title: "已有候选", status: "verified" }] })); vi.stubGlobal("fetch", fetcher);
    render(<FmeaDesignRules projectId="project" entryId="entry"/>); open(); await screen.findByText(/尚无已发布 FMEA/); expect(screen.queryByRole("button", { name: "保存设计规则候选" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "读取发布依据与原候选" })); expect(await screen.findByRole("alert")).toHaveTextContent("发布依据或其质量证据已变化");
    fireEvent.click(screen.getByRole("button", { name: "读取发布依据与原候选" })); await screen.findByText(/已有候选 · 已有审核记录/); expect(screen.queryByRole("button", { name: "保存设计规则候选" })).not.toBeInTheDocument();
  });
  it("discards late prior-scope responses and clears evidence when access is revoked", async () => {
    let resolve!: (response: Response) => void;
    const fetcher = vi.fn<typeof fetch>().mockImplementationOnce(() => new Promise(done => { resolve = done; })).mockResolvedValueOnce(Response.json(page())).mockResolvedValueOnce(Response.json({ detail: { message: "当前没有此项目或操作权限" } }, { status: 403 })); vi.stubGlobal("fetch", fetcher);
    const view = render(<FmeaDesignRules projectId="old" entryId="entry"/>); open(); await waitFor(() => expect(resolve).toBeDefined());
    view.rerender(<FmeaDesignRules projectId="current" entryId="other"/>); open(); await screen.findByText("采用已发布 v2：密封设计");
    await act(async () => resolve(Response.json({ ...page(), version: { version: 1, body: { title: "OLD PRIVATE DATA" } } })));
    expect(screen.queryByText(/OLD PRIVATE DATA/)).not.toBeInTheDocument(); fireEvent.click(screen.getByRole("button", { name: "读取发布依据与原候选" })); expect(await screen.findByRole("alert")).toHaveTextContent("当前没有此项目或操作权限"); expect(screen.queryByLabelText("候选名称")).not.toBeInTheDocument();
  });
});
