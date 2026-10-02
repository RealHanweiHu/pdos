import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ResearchCollection } from "./research-collection";
import type { Evidence, Workspace } from "./product-work-api";

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams() }));
vi.mock("./research-search", () => ({ ResearchSearch: () => null }));
vi.mock("./research-subscriptions", () => ({ ResearchSubscriptions: () => null }));
const source = { id: "source", name: "已登记公开来源", base_url: "https://example.com", status: "active", allowed_use: "internal_analysis", license_note: "合成许可说明" };
const content = { snapshot_id: "saved-snapshot", content: "已保存的原文", byte_size: 6, content_digest: "a".repeat(64), taint: "untrusted_external" };
const props = { base: "spaces/space", lineId: null, canCollect: true, evidence: [], onResponsibilityLock: vi.fn(), workspace: { can_manage_sources: true, space: { lifecycle: "active" } } as Workspace };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
async function capture() {
  await screen.findByRole("option", { name: source.name });
  fireEvent.change(screen.getByLabelText("来源", { exact: true }), { target: { value: source.id } });
  fireEvent.submit(screen.getByLabelText("页面地址").closest("form")!);
}
function openCollection() { fireEvent.click(screen.getByText("研究来源与公开页面采集")); }

it.each([true, false])("retains the saved receipt when follow-up refresh fails (body unavailable: %s)", async unavailable => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [source], search_available: false })).mockResolvedValueOnce(Response.json({ snapshot: { id: content.snapshot_id }, reused_existing: false, message: "页面已采集" })).mockResolvedValueOnce(unavailable ? Response.json({}, { status: 503 }) : Response.json(content)).mockResolvedValueOnce(Response.json(content));
  vi.stubGlobal("fetch", fetcher);
  render(<ResearchCollection {...props} refresh={vi.fn().mockRejectedValue(new Error("列表暂不可读"))}/>); openCollection();
  await capture();
  expect(await screen.findByRole("status")).toHaveTextContent("页面已采集");
  expect(await screen.findByRole("alert")).toHaveTextContent("快照已保存");
  expect(screen.getByText(`已保存快照：${content.snapshot_id}`)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "读取已保存快照" }));
  await screen.findByText("已保存的原文");
  expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith("/capture"))).toHaveLength(1);
  expect(fetcher.mock.calls[3][0]).toContain(`/evidence/${content.snapshot_id}/content`);
});

it("clears the receipt and body when follow-up reading loses permission", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [source], search_available: false })).mockResolvedValueOnce(Response.json({ snapshot: { id: content.snapshot_id }, reused_existing: false, message: "页面已采集" })).mockResolvedValueOnce(Response.json({ detail: { message: "空间访问已撤回" } }, { status: 403 }));
  vi.stubGlobal("fetch", fetcher);
  render(<ResearchCollection {...props} refresh={vi.fn().mockResolvedValue(undefined)}/>); openCollection(); await capture();
  await screen.findByText("空间访问已撤回");
  expect(screen.queryByText(`已保存快照：${content.snapshot_id}`)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "读取已保存快照" })).not.toBeInTheDocument();
  expect(screen.queryByText("已保存的原文")).not.toBeInTheDocument();
});

it("retains a successfully registered source if reloading the source list fails", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [], search_available: false })).mockResolvedValueOnce(Response.json(source)).mockResolvedValueOnce(Response.json({}, { status: 503 }));
  vi.stubGlobal("fetch", fetcher);
  render(<ResearchCollection {...props} refresh={vi.fn()}/>); openCollection();
  fireEvent.click(screen.getByText("登记公开来源"));
  fireEvent.change(screen.getByLabelText("来源名称"), { target: { value: source.name } });
  fireEvent.change(screen.getByLabelText("来源地址"), { target: { value: source.base_url } });
  fireEvent.change(screen.getByLabelText("许可依据"), { target: { value: source.license_note } });
  fireEvent.submit(screen.getByLabelText("来源名称").closest("form")!);
  await screen.findByRole("alert");
  expect(screen.getByRole("status")).toHaveTextContent("来源已登记");
  expect(screen.getByLabelText("来源", { exact: true })).toHaveValue(source.id);
  expect(fetcher.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(1);
});


it.each([{ base: "spaces/other", lineId: null }, { base: props.base, lineId: "other-line" }])("clears saved evidence and source selection on scope switch to $base / $lineId", async scope => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(Response.json({ items: [source], search_available: false })).mockResolvedValueOnce(Response.json({ snapshot: { id: content.snapshot_id }, reused_existing: false, message: "页面已采集" })).mockResolvedValueOnce(Response.json(content)).mockResolvedValue(Response.json({ items: [source], search_available: false })));
  const view = render(<ResearchCollection {...props} refresh={vi.fn().mockResolvedValue(undefined)}/>);
  openCollection(); await capture(); await screen.findByText(content.content);
  view.rerender(<ResearchCollection {...props} {...scope} refresh={vi.fn()}/>);
  expect(screen.queryByText(content.content)).not.toBeInTheDocument();
  expect(screen.queryByText(`已保存快照：${content.snapshot_id}`)).not.toBeInTheDocument();
  openCollection();
  expect(screen.getByLabelText("来源", { exact: true })).toHaveValue("");
});

it("does not run follow-up reads or parent refresh after an old scope capture resolves", async () => {
  let finish!: (response: Response) => void;
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (_url, init) => init?.method === "POST" ? new Promise(resolve => { finish = resolve; }) : Response.json({ items: [source], search_available: false }));
  vi.stubGlobal("fetch", fetcher); const refresh = vi.fn();
  const view = render(<ResearchCollection {...props} refresh={refresh}/>);
  openCollection(); await capture();
  view.rerender(<ResearchCollection {...props} lineId="new-line" refresh={refresh}/>);
  await act(async () => finish(Response.json({ snapshot: { id: content.snapshot_id }, reused_existing: false, message: "页面已采集" })));
  expect(refresh).not.toHaveBeenCalled();
  expect(fetcher.mock.calls.some(([url]) => String(url).includes("/content"))).toBe(false);
  expect(screen.queryByText(`已保存快照：${content.snapshot_id}`)).not.toBeInTheDocument();
});

it("suppresses duplicate capture submissions before the next render", async () => {
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (_url, init) => init?.method === "POST" ? new Promise(() => {}) : Response.json({ items: [source], search_available: false }));
  vi.stubGlobal("fetch", fetcher); render(<ResearchCollection {...props} refresh={vi.fn()}/>);
  openCollection(); await screen.findByRole("option", { name: source.name });
  fireEvent.change(screen.getByLabelText("来源", { exact: true }), { target: { value: source.id } });
  const form = screen.getByLabelText("页面地址").closest("form")!;
  act(() => { fireEvent.submit(form); fireEvent.submit(form); });
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
});

it("cancels a pending body read and ignores its late response without losing the saved receipt", async () => {
  let finish!: (response: Response) => void;
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [source], search_available: false })).mockResolvedValueOnce(Response.json({ snapshot: { id: content.snapshot_id }, reused_existing: false, message: "页面已采集" })).mockResolvedValueOnce(Response.json({}, { status: 503 })).mockReturnValueOnce(new Promise(resolve => { finish = resolve; })).mockResolvedValueOnce(Response.json(content));
  vi.stubGlobal("fetch", fetcher); render(<ResearchCollection {...props} refresh={vi.fn().mockResolvedValue(undefined)}/>);
  openCollection(); await capture(); await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "读取已保存快照" }));
  fireEvent.click(screen.getByRole("button", { name: "取消读取正文" }));
  fireEvent.click(screen.getByRole("button", { name: "读取已保存快照" }));
  await screen.findByText(content.content);
  await act(async () => finish(Response.json({ ...content, content: "已取消的迟到正文" })));
  expect(screen.queryByText("已取消的迟到正文")).not.toBeInTheDocument();
  expect(screen.getByText(`已保存快照：${content.snapshot_id}`)).toBeInTheDocument();
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(5));
});


it("ignores a previous scope's pending body read", async () => {
  let finish!: (response: Response) => void;
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [source], search_available: false })).mockResolvedValueOnce(Response.json({ snapshot: { id: content.snapshot_id }, reused_existing: false, message: "页面已采集" })).mockResolvedValueOnce(Response.json(content)).mockReturnValueOnce(new Promise(resolve => { finish = resolve; })).mockResolvedValueOnce(Response.json({ items: [source], search_available: false }));
  vi.stubGlobal("fetch", fetcher);
  const view = render(<ResearchCollection {...props} refresh={vi.fn().mockResolvedValue(undefined)}/>);
  openCollection(); await capture(); await screen.findByText(content.content);
  fireEvent.click(screen.getByRole("button", { name: "读取已保存快照" }));
  view.rerender(<ResearchCollection {...props} base="spaces/new" refresh={vi.fn()}/>);
  await act(async () => finish(Response.json(content)));
  expect(screen.queryByText(content.content)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "取消读取正文" })).not.toBeInTheDocument();
});

it("does not restore sources from an initial response after refresh denies access", async () => {
  let finish!: (response: Response) => void;
  const fetcher = vi.fn<typeof fetch>().mockReturnValueOnce(new Promise(resolve => { finish = resolve; })).mockResolvedValueOnce(Response.json({ detail: { message: "来源权限已撤回" } }, { status: 403 }));
  vi.stubGlobal("fetch", fetcher); render(<ResearchCollection {...props} refresh={vi.fn()}/>); openCollection();
  fireEvent.click(screen.getByRole("button", { name: "刷新来源与快照" }));
  await screen.findByText("来源权限已撤回");
  await act(async () => finish(Response.json({ items: [source], search_available: true })));
  expect(screen.queryByRole("option", { name: source.name })).not.toBeInTheDocument();
});

it("retains a saved receipt but refuses a body belonging to another snapshot", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(Response.json({ items: [source], search_available: false })).mockResolvedValueOnce(Response.json({ snapshot: { id: content.snapshot_id }, reused_existing: false, message: "页面已采集" })).mockResolvedValueOnce(Response.json({ ...content, snapshot_id: "another-snapshot" })));
  render(<ResearchCollection {...props} refresh={vi.fn().mockResolvedValue(undefined)}/>); openCollection(); await capture();
  expect(await screen.findByRole("alert")).toHaveTextContent("正文与保存快照不一致");
  expect(screen.getByText(`已保存快照：${content.snapshot_id}`)).toBeInTheDocument();
  expect(screen.queryByText(content.content)).not.toBeInTheDocument();
});

it.each([401, 403])("hides denied snapshot metadata across prop refreshes until explicit permission recovery (%s)", async status => {
  const evidence: Evidence = { id: "saved-snapshot", name: "受限客户来源", url: "https://private.example.com/spec", captured_at: "2026-09-29T12:00:00Z", taint: "untrusted_external", is_stale: false, superseded: false, has_conflict: false, reference: { tenant_id: "tenant", kind: "evidence_snapshot", ref_id: "saved-snapshot", as_of: "2026-09-29T12:00:00Z", digest: content.content_digest } };
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [source], search_available: false }))
    .mockResolvedValueOnce(Response.json({ detail: { message: "资料访问已撤回" } }, { status }))
    .mockResolvedValueOnce(Response.json({ items: [source], search_available: false }));
  vi.stubGlobal("fetch", fetcher); const onAuthorityLost = vi.fn(), refresh = vi.fn().mockResolvedValue(undefined);
  const view = render(<ResearchCollection {...props} evidence={[evidence]} refresh={refresh} onAuthorityLost={onAuthorityLost}/>); openCollection();
  await screen.findByRole("option", { name: source.name });
  fireEvent.click(screen.getByRole("button", { name: "查看快照正文" })); await screen.findByText("资料访问已撤回");
  expect(onAuthorityLost).toHaveBeenCalledWith("资料访问已撤回"); expect(screen.queryByText(evidence.name)).not.toBeInTheDocument(); expect(screen.queryByText(/private.example.com/)).not.toBeInTheDocument();
  view.rerender(<ResearchCollection {...props} evidence={[{ ...evidence }]} refresh={refresh} onAuthorityLost={onAuthorityLost}/>);
  expect(screen.queryByText(evidence.name)).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: "查看快照正文" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "重新核对来源权限" })); await screen.findByText(evidence.name); expect(refresh).toHaveBeenCalledTimes(1);
});

it("does not release denied metadata when explicit recovery fails", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [source], search_available: false }))
    .mockResolvedValueOnce(Response.json({ detail: { message: "来源已撤权" } }, { status: 403 }))
    .mockResolvedValueOnce(Response.json({ items: [source], search_available: false }));
  vi.stubGlobal("fetch", fetcher); const refresh = vi.fn().mockRejectedValue(new Error("权限刷新暂不可用"));
  render(<ResearchCollection {...props} refresh={refresh}/>); openCollection(); await screen.findByRole("option", { name: source.name });
  fireEvent.click(screen.getByRole("button", { name: "刷新来源与快照" })); await screen.findByText("来源已撤权");
  fireEvent.click(screen.getByRole("button", { name: "重新核对来源权限" })); await screen.findByText("权限刷新暂不可用");
  expect(screen.queryByRole("option", { name: source.name })).not.toBeInTheDocument(); expect(screen.getByRole("button", { name: "重新核对来源权限" })).toBeEnabled();
});

it("invalidates an in-flight body read when the independent initial source lookup denies access", async () => {
  let deny!: (response: Response) => void, finish!: (response: Response) => void;
  const evidence: Evidence = { id: content.snapshot_id, name: "在途受限来源", url: "https://private.example.com/spec", captured_at: "2026-09-29T12:00:00Z", taint: "untrusted_external", is_stale: false, superseded: false, has_conflict: false, reference: { tenant_id: "tenant", kind: "evidence_snapshot", ref_id: content.snapshot_id, as_of: "2026-09-29T12:00:00Z", digest: content.content_digest } };
  const fetcher = vi.fn<typeof fetch>().mockReturnValueOnce(new Promise(resolve => { deny = resolve; })).mockReturnValueOnce(new Promise(resolve => { finish = resolve; })).mockResolvedValueOnce(Response.json({ items: [source], search_available: false }));
  vi.stubGlobal("fetch", fetcher); render(<ResearchCollection {...props} evidence={[evidence]} refresh={vi.fn().mockResolvedValue(undefined)}/>); openCollection();
  fireEvent.click(screen.getByRole("button", { name: "查看快照正文" }));
  await act(async () => deny(Response.json({ detail: { message: "来源范围已撤权" } }, { status: 403 })));
  expect(screen.getByRole("button", { name: "重新核对来源权限" })).toBeEnabled();
  await act(async () => finish(Response.json(content)));
  fireEvent.click(screen.getByRole("button", { name: "重新核对来源权限" })); await screen.findByText(evidence.name);
  expect(screen.queryByText(content.content)).not.toBeInTheDocument();
});
