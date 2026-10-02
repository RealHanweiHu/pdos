import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { DefinitionExports } from "./definition-exports";

const preview = { digest: "original-digest", source: { definition: { title: "私有定义预览" }, status_label: "草稿" }, sections: [{ title: "原规格", text: "私有规格正文" }] };
const saved = { id: "saved-export", format: "docx", created_at: "2026-09-29T00:00:00Z", reason: "私有导出用途", sources_current: true, byte_size: 1024 };
const empty = { items: [] };
const props = { base: "spaces/space", initialDefinitionId: "definition-a" };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

async function prepare() {
  fireEvent.change(screen.getByLabelText("内部用途与版本选择说明"), { target: { value: "内部核对" } });
  fireEvent.click(screen.getByRole("button", { name: "预览内容与状态" }));
  await screen.findByText("私有规格正文");
}
function save() {
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.submit(screen.getByRole("checkbox").closest("form")!);
}

it("removes the old preview and confirmation if a fresh preview fails", async () => {
  vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(preview)).mockResolvedValueOnce(Response.json({ detail: { message: "预览暂不可用" } }, { status: 503 })));
  render(<DefinitionExports {...props}/>); await prepare();
  fireEvent.click(screen.getByRole("button", { name: "预览内容与状态" }));
  await screen.findByText("预览暂不可用");
  expect(screen.queryByText("私有规格正文")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "生成并保存文件" })).not.toBeInTheDocument();
});

it.each([401, 403])("clears private options, preview and history when reading returns %s", async status => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [{ id: "definition-a", title: "私有版本选项", revision_number: 1, version: 1, state: "draft" }] }))
    .mockResolvedValueOnce(Response.json(preview)).mockResolvedValueOnce(Response.json({ items: [saved] }))
    .mockResolvedValueOnce(Response.json({ detail: { message: "导出访问已撤回" } }, { status }));
  vi.stubGlobal("fetch", fetcher);
  render(<DefinitionExports base={props.base}/>);
  fireEvent.click(screen.getByRole("button", { name: "查找实际版本" }));
  await screen.findByRole("option", { name: /私有版本选项/ });
  fireEvent.change(screen.getByLabelText("明确选择定义版本"), { target: { value: "definition-a" } });
  await prepare();
  fireEvent.click(screen.getByRole("button", { name: "查看已生成文件" }));
  await screen.findByText("用途：私有导出用途");
  fireEvent.click(screen.getByRole("button", { name: "查看已生成文件" }));
  await screen.findByText("导出访问已撤回");
  expect(screen.queryByText("私有规格正文")).not.toBeInTheDocument();
  expect(screen.queryByText("用途：私有导出用途")).not.toBeInTheDocument();
  expect(screen.queryByRole("option", { name: /私有版本选项/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /下载/ })).not.toBeInTheDocument();
});

it("keeps a committed export downloadable when history refresh fails, without another save", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(preview)).mockResolvedValueOnce(Response.json(saved))
    .mockResolvedValueOnce(Response.json({}, { status: 503 })).mockResolvedValueOnce(Response.json({ items: [saved] }));
  vi.stubGlobal("fetch", fetcher);
  render(<DefinitionExports {...props}/>); await prepare(); save();
  expect(await screen.findByRole("alert")).toHaveTextContent("文件已保存");
  expect(screen.getByRole("status")).toHaveTextContent(saved.id);
  expect(screen.getByRole("link", { name: "下载本次已保存文件" })).toHaveAttribute("href", `/api/product-work/spaces/space/definition-exports/${saved.id}/download`);
  fireEvent.click(screen.getByRole("button", { name: "查看已生成文件" }));
  await screen.findByText("用途：私有导出用途");
  expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith("/definition-export-save"))).toHaveLength(1);
});

it("clears a saved receipt if the following history read loses permission", async () => {
  vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(preview)).mockResolvedValueOnce(Response.json(saved)).mockResolvedValueOnce(Response.json({ detail: { message: "权限已撤回" } }, { status: 403 })));
  render(<DefinitionExports {...props}/>); await prepare(); save();
  await screen.findByText("权限已撤回");
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /下载/ })).not.toBeInTheDocument();
  expect(screen.queryByText("私有规格正文")).not.toBeInTheDocument();
});

it("requires a new preview after stale sources and gives the changed request a new identity", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(preview)).mockResolvedValueOnce(Response.json({ detail: { message: "来源已变化，请重新预览" } }, { status: 409 }))
    .mockResolvedValueOnce(Response.json({ ...preview, digest: "new-digest" })).mockResolvedValueOnce(Response.json(saved)).mockResolvedValueOnce(Response.json(empty));
  vi.stubGlobal("fetch", fetcher);
  render(<DefinitionExports {...props}/>); await prepare(); save();
  await screen.findByText("来源已变化，请重新预览");
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  await prepare(); save();
  await screen.findByRole("link", { name: "下载本次已保存文件" });
  const first = JSON.parse(String(fetcher.mock.calls[1][1]?.body));
  const second = JSON.parse(String(fetcher.mock.calls[3][1]?.body));
  expect(second.expected_digest).toBe("new-digest");
  expect(second.request_id).not.toBe(first.request_id);
});

it("retries an uncertain save with the exact original request", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(preview)).mockRejectedValueOnce(new TypeError("响应丢失"))
    .mockResolvedValueOnce(Response.json(saved)).mockResolvedValueOnce(Response.json(empty));
  vi.stubGlobal("fetch", fetcher);
  render(<DefinitionExports {...props}/>); await prepare(); save();
  await screen.findByText("响应丢失");
  fireEvent.submit(screen.getByRole("checkbox").closest("form")!);
  await screen.findByRole("link", { name: "下载本次已保存文件" });
  expect(fetcher.mock.calls[1][1]?.body).toBe(fetcher.mock.calls[2][1]?.body);
});

it.each(["space", "definition"])("drops a late old preview when the %s changes", async scope => {
  let finish!: (response: Response) => void;
  const fetcher = vi.fn<typeof fetch>().mockImplementationOnce(() => new Promise(resolve => { finish = resolve; })).mockResolvedValueOnce(Response.json(preview));
  vi.stubGlobal("fetch", fetcher);
  const view = render(<DefinitionExports {...props}/>);
  fireEvent.change(screen.getByLabelText("内部用途与版本选择说明"), { target: { value: "旧范围说明" } });
  fireEvent.click(screen.getByRole("button", { name: "预览内容与状态" }));
  const next = { ...props, ...(scope === "space" ? { base: "spaces/other" } : { initialDefinitionId: "definition-b" }) };
  view.rerender(<DefinitionExports {...next}/>);
  await act(async () => { finish(Response.json(preview)); });
  expect(screen.queryByText("私有规格正文")).not.toBeInTheDocument();
  expect(screen.getByLabelText("内部用途与版本选择说明")).toHaveValue("");
  await prepare();
  expect(fetcher.mock.calls[1][0]).toBe(`/api/product-work/${next.base}/definition-export-preview`);
  expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body)).definition_id).toBe(next.initialDefinitionId);
});
