import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { Evidence } from "./product-work-api";
import { afterEach, expect, it, vi } from "vitest";
import { SourceCitations } from "./source-citations";
const reference = { tenant_id: "tenant", kind: "evidence_snapshot", ref_id: "snapshot", as_of: "2026-09-29T12:00:00Z", digest: "a".repeat(64) };
const metadata: Evidence = { id: reference.ref_id, name: "受限引用名称", url: "https://private.example.com/original", captured_at: reference.as_of, source_version: "v1", taint: "untrusted_external", is_stale: false, superseded: false, has_conflict: false, reference };
function stubFetch(fetcher: typeof fetch) {
  vi.stubGlobal("fetch", (url: RequestInfo | URL, init?: RequestInit) => String(url).includes("/evidence?") ? Promise.resolve(Response.json({ items: [metadata] })) : fetcher(url, init));
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("opens the exact cited snapshot even when it is absent from the recent-source list", async () => {
  const fetcher = vi.fn().mockResolvedValue(Response.json({ snapshot_id: "snapshot", content_digest: reference.digest, content: "原工况25℃，不得被新版覆盖" }));
  stubFetch(fetcher);
  render(<SourceCitations base="spaces/space" references={[reference]} evidence={[]}/>);
  fireEvent.click(screen.getByRole("button", { name: "查看此引用的原快照" }));
  expect(await screen.findByText("原工况25℃，不得被新版覆盖")).toBeInTheDocument();
  expect(fetcher.mock.calls[0][0]).toBe("/api/product-work/spaces/space/evidence/snapshot/content");
});
it("does not display a mismatched source body as the cited evidence", async () => {
  stubFetch(vi.fn().mockResolvedValue(Response.json({ snapshot_id: "snapshot", content_digest: "b".repeat(64), content: "不应显示的新版" })));
  render(<SourceCitations base="spaces/space" references={[reference]} evidence={[]}/>);
  fireEvent.click(screen.getByRole("button", { name: "查看此引用的原快照" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("原版本不一致");
  expect(screen.queryByText("不应显示的新版")).not.toBeInTheDocument();
});


it("cancels a pending citation read and keeps a new read when the cancelled response arrives", async () => {
  let finish!: (response: Response) => void;
  const body = { snapshot_id: "snapshot", content_digest: reference.digest, content: "重新读取的正文" };
  const fetcher = vi.fn().mockReturnValueOnce(new Promise(resolve => { finish = resolve; })).mockResolvedValueOnce(Response.json(body));
  stubFetch(fetcher); render(<SourceCitations base="spaces/space" references={[reference]} evidence={[]}/>);
  fireEvent.click(screen.getByRole("button", { name: "查看此引用的原快照" }));
  fireEvent.click(screen.getByRole("button", { name: "取消读取原快照" }));
  fireEvent.click(screen.getByRole("button", { name: "查看此引用的原快照" }));
  await screen.findByText(body.content);
  await act(async () => finish(Response.json({ ...body, content: "已取消的引用正文" })));
  expect(screen.queryByText("已取消的引用正文")).not.toBeInTheDocument();
});

it("suppresses repeated citation reads before a render", () => {
  const fetcher = vi.fn().mockReturnValue(new Promise(() => {}));
  stubFetch(fetcher); render(<SourceCitations base="spaces/space" references={[reference]} evidence={[]}/>);
  const button = screen.getByRole("button", { name: "查看此引用的原快照" });
  act(() => { fireEvent.click(button); fireEvent.click(button); });
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it.each([401, 403])("quarantines all citation metadata and web links after denial %s until explicit recovery", async status => {
  const evidence: Evidence = { id: reference.ref_id, name: "受限引用名称", url: "https://private.example.com/original", captured_at: reference.as_of, taint: "untrusted_external", is_stale: false, superseded: false, has_conflict: false, reference };
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ snapshot_id: reference.ref_id, content_digest: reference.digest, content: "先前可读原文" }))
    .mockResolvedValueOnce(Response.json({ detail: { message: "引用访问已撤回" } }, { status }))
    .mockResolvedValueOnce(Response.json({ snapshot_id: reference.ref_id, content_digest: reference.digest, content: "恢复后的原文" }));
  stubFetch(fetcher); const onAuthorityLost = vi.fn();
  const view = render(<SourceCitations base="spaces/space" references={[reference]} evidence={[evidence]} onAuthorityLost={onAuthorityLost}/>);
  fireEvent.click(screen.getByRole("button", { name: "查看此引用的原快照" })); await screen.findByText("先前可读原文");
  fireEvent.click(screen.getByRole("button", { name: "查看此引用的原快照" })); await screen.findByText("引用访问已撤回");
  expect(onAuthorityLost).toHaveBeenCalledWith("引用访问已撤回"); expect(screen.queryByText("先前可读原文")).not.toBeInTheDocument(); expect(screen.queryByText(/受限引用名称/)).not.toBeInTheDocument(); expect(screen.queryByRole("link", { name: "打开来源网页" })).not.toBeInTheDocument(); expect(screen.queryByText(new RegExp(reference.digest.slice(0, 12)))).not.toBeInTheDocument();
  view.rerender(<SourceCitations base="spaces/space" references={[{ ...reference }]} evidence={[{ ...evidence }]} onAuthorityLost={onAuthorityLost}/>);
  expect(screen.queryByText(/受限引用名称/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "重新核对引用权限" })); await screen.findByText("恢复后的原文"); expect(screen.getByRole("link", { name: "打开来源网页" })).toHaveAttribute("href", evidence.url);
});

it("discards a late citation body and clears busy state on direct scope change", async () => {
  let finish!: (response: Response) => void;
  const fetcher = vi.fn<typeof fetch>().mockReturnValueOnce(new Promise(resolve => { finish = resolve; })).mockResolvedValueOnce(Response.json({ snapshot_id: "next-snapshot", content_digest: reference.digest, content: "新范围原文" }));
  stubFetch(fetcher); const view = render(<SourceCitations base="spaces/old" references={[reference]} evidence={[]}/>);
  fireEvent.click(screen.getByRole("button", { name: "查看此引用的原快照" }));
  view.rerender(<SourceCitations base="spaces/new" references={[{ ...reference, ref_id: "next-snapshot" }]} evidence={[]}/>);
  fireEvent.click(screen.getByRole("button", { name: "查看此引用的原快照" })); await screen.findByText("新范围原文");
  await act(async () => finish(Response.json({ snapshot_id: reference.ref_id, content_digest: reference.digest, content: "旧范围迟到原文" })));
  expect(screen.queryByText("旧范围迟到原文")).not.toBeInTheDocument(); expect(screen.getByRole("button", { name: "查看此引用的原快照" })).toBeEnabled();
});

it("keeps denied citations hidden when the same references are reordered or reserialized", async () => {
  const second = { ...reference, ref_id: "second-snapshot" };
  const metadata = [reference, second].map((ref, index) => ({ id: ref.ref_id, name: `已拒绝资料${index}`, url: `https://private.example.com/${index}`, reference: ref } as Evidence));
  stubFetch(vi.fn().mockResolvedValue(Response.json({ detail: { message: "访问已拒绝" } }, { status: 403 })));
  const view = render(<SourceCitations base="spaces/space" references={[reference, second]} evidence={metadata}/>);
  fireEvent.click(screen.getAllByRole("button", { name: "查看此引用的原快照" })[0]);
  await screen.findByText("访问已拒绝");
  const reserialized = { digest: reference.digest, as_of: reference.as_of, ref_id: reference.ref_id, kind: reference.kind, tenant_id: reference.tenant_id };
  view.rerender(<SourceCitations base="spaces/space" references={[second, reserialized]} evidence={metadata}/>);
  expect(screen.queryByText(/已拒绝资料/)).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "打开来源网页" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "重新核对引用权限" })).toBeVisible();
});

it("resolves quality of an old citation omitted from more than 200 recent snapshots", async () => {
  const old = { ...metadata, name: "旧原工况", source_version: "2024-R2", is_stale: true, superseded: true, has_conflict: true };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ items: [old] })));
  render(<SourceCitations base="spaces/space" references={[reference]} evidence={Array.from({ length: 200 }, (_, index) => ({ ...metadata, id: `recent-${index}` }))}/>);
  expect(screen.getByText(/来源质量尚未核对/)).toBeInTheDocument();
  expect(await screen.findByText(/旧原工况/)).toHaveTextContent("已陈旧");
  expect(screen.getByText(/旧原工况/)).toHaveTextContent("有新版");
  expect(screen.getByText(/旧原工况/)).toHaveTextContent("有冲突");
  expect(screen.getByText(/旧原工况/)).toHaveTextContent("2024-R2");
});
it("does not treat absent or mismatched metadata as verified clean quality", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ items: [{ ...metadata, reference: { ...reference, digest: "b".repeat(64) } }] })));
  render(<SourceCitations base="spaces/space" references={[reference]} evidence={[metadata]}/>);
  await act(async () => {});
  expect(screen.getByText(/来源质量尚未核对/)).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "打开来源网页" })).not.toBeInTheDocument();
});
it("does not automatically query again after denial when parent props and callbacks rerender", async () => {
  const fetcher = vi.fn().mockResolvedValue(Response.json({ detail: { message: "已撤权" } }, { status: 403 }));
  vi.stubGlobal("fetch", fetcher);
  const view = render(<SourceCitations base="spaces/space" references={[reference]} evidence={[metadata]} onAuthorityLost={vi.fn()}/>);
  await screen.findByText("已撤权");
  view.rerender(<SourceCitations base="spaces/space" references={[{ ...reference }]} evidence={[{ ...metadata }]} onAuthorityLost={vi.fn()}/>);
  await act(async () => {});
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("link", { name: "打开来源网页" })).not.toBeInTheDocument();
});
it("ignores a stale metadata denial after a newer explicit read has verified the source", async () => {
  let finish!: (response: Response) => void;
  const lost = vi.fn();
  vi.stubGlobal("fetch", vi.fn().mockReturnValueOnce(new Promise<Response>(resolve => { finish = resolve; }))
    .mockResolvedValueOnce(Response.json({ snapshot_id: reference.ref_id, content_digest: reference.digest, content: "后来确认的原文" }))
    .mockResolvedValueOnce(Response.json({ items: [metadata] })));
  render(<SourceCitations base="spaces/space" references={[reference]} evidence={[]} onAuthorityLost={lost}/>);
  fireEvent.click(screen.getByRole("button", { name: "查看此引用的原快照" }));
  await screen.findByText(/受限引用名称/);
  await act(async () => finish(Response.json({ detail: { message: "旧请求迟到拒绝" } }, { status: 403 })));
  expect(screen.getByText("后来确认的原文")).toBeInTheDocument();
  expect(lost).not.toHaveBeenCalled();
});
it.each(["tenant_id", "project_id", "kind"] as const)("does not accept metadata with mismatched canonical %s", async field => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ items: [{ ...metadata, reference: { ...reference, [field]: "other-scope" } }] })));
  render(<SourceCitations base="spaces/space" references={[reference]} evidence={[metadata]}/>);
  await act(async () => {});
  expect(screen.getByText(/来源质量尚未核对/)).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "打开来源网页" })).not.toBeInTheDocument();
});
it("drops old verified quality when a fresh original read cannot verify metadata", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(Response.json({ items: [{ ...metadata, is_stale: true }] }))
    .mockResolvedValueOnce(Response.json({ snapshot_id: reference.ref_id, content_digest: reference.digest, content: "原文" }))
    .mockResolvedValueOnce(Response.json({ items: [] })));
  render(<SourceCitations base="spaces/space" references={[reference]} evidence={[]}/>);
  await screen.findByText(/已陈旧/);
  fireEvent.click(screen.getByRole("button", { name: "查看此引用的原快照" }));
  await screen.findByRole("alert");
  expect(screen.getAllByText(/来源质量尚未核对/)).toHaveLength(2);
  expect(screen.queryByText(/已陈旧/)).not.toBeInTheDocument();
});
