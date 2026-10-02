import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ResearchSearch } from "./research-search";

const result = { id: "search", request_id: "request", product_line_id: null, query: "公开气泵规格", status: "completed", started_at: "2026-09-29T00:00:00Z", finished_at: "2026-09-29T00:00:01Z", provider_key: "searxng", warnings: [], hits: [{ title: "公开规格", url: "https://example.com/spec", snippet: "仅作线索" }] };
const props = { base: "spaces/space", lineId: null, configured: true, canSearch: true, onPick: vi.fn() };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks(); });
function search() {
  const input = screen.getByLabelText("研究问题 / 关键词");
  fireEvent.change(input, { target: { value: result.query } });
  fireEvent.submit(input.closest("form")!);
}

it("starts a new observation after a terminal result even if history refresh failed", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [] })).mockResolvedValueOnce(Response.json(result)).mockResolvedValueOnce(Response.json({}, { status: 503 })).mockResolvedValueOnce(Response.json(result)).mockResolvedValueOnce(Response.json({ items: [] }));
  vi.stubGlobal("fetch", fetcher); render(<ResearchSearch {...props}/>);
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  search();
  expect(await screen.findByRole("alert")).toHaveTextContent("搜索已返回，查询列表刷新失败");
  expect(screen.getByText("仅作线索")).toBeInTheDocument();
  search();
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(5));
  expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body)).request_id).not.toBe(JSON.parse(String(fetcher.mock.calls[3][1]?.body)).request_id);
});

it("recovers the exact uncertain query from history and makes a later search a new observation", async () => {
  const writes: { request_id: string }[] = [];
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (_url, init) => {
    if (init?.method === "POST") { writes.push(JSON.parse(String(init.body))); if (writes.length === 1) throw new TypeError("响应丢失"); return Response.json({ ...result, request_id: writes.at(-1)!.request_id }); }
    return Response.json({ items: writes.length ? [{ ...result, request_id: writes[0].request_id }] : [] });
  });
  vi.stubGlobal("fetch", fetcher); render(<ResearchSearch {...props}/>);
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1)); search();
  await screen.findByText("响应丢失");
  fireEvent.click(screen.getByRole("button", { name: "刷新结果" }));
  await screen.findByText("仅作线索");
  expect(writes).toHaveLength(1);
  search(); await waitFor(() => expect(writes).toHaveLength(2));
  expect(writes[1].request_id).not.toBe(writes[0].request_id);
});

it.each([401, 403])("clears previously readable query hits when refreshing returns %s", async status => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [result] })).mockResolvedValueOnce(Response.json({ detail: { message: "当前无权读取研究记录" } }, { status }));
  vi.stubGlobal("fetch", fetcher); render(<ResearchSearch {...props}/>);
  await screen.findByRole("option", { name: /公开气泵规格/ });
  fireEvent.change(screen.getByLabelText("此范围的近期查询"), { target: { value: result.id } });
  expect(screen.getByText("仅作线索")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "刷新结果" }));
  await screen.findByText("当前无权读取研究记录");
  expect(screen.queryByText("仅作线索")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "用于页面采集" })).not.toBeInTheDocument();
});

it("keeps unconfigured search distinct from a successful zero-hit observation", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ items: [{ ...result, status: "no_results", hits: [] }] })));
  render(<ResearchSearch {...props} configured={false}/>);
  expect(screen.getByRole("button", { name: "搜索来源" })).toBeDisabled();
  await screen.findByRole("option", { name: /本次查询无命中/ });
  fireEvent.change(screen.getByLabelText("此范围的近期查询"), { target: { value: result.id } });
  expect(screen.getByText(/本次查询无命中 ·/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "用于页面采集" })).not.toBeInTheDocument();
});

it("does not let a late initial history response restore queries after permission was denied", async () => {
  let finish!: (response: Response) => void;
  const fetcher = vi.fn<typeof fetch>().mockReturnValueOnce(new Promise(resolve => { finish = resolve; })).mockResolvedValueOnce(Response.json({ detail: { message: "搜索权限已撤回" } }, { status: 403 }));
  vi.stubGlobal("fetch", fetcher); render(<ResearchSearch {...props}/>);
  search(); await screen.findByText("搜索权限已撤回");
  await act(async () => { finish(Response.json({ items: [result] })); });
  await waitFor(() => expect(screen.queryByRole("option", { name: /公开气泵规格/ })).not.toBeInTheDocument());
  expect(screen.queryByText("仅作线索")).not.toBeInTheDocument();
});

it.each([
  { base: "spaces/another", lineId: null },
  { base: props.base, lineId: "another-line" },
])("discards selected evidence when scope changes to $base / $lineId", async scope => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [result] })).mockResolvedValueOnce(Response.json({ items: [] }));
  vi.stubGlobal("fetch", fetcher);
  const view = render(<ResearchSearch {...props}/>);
  await screen.findByRole("option", { name: /公开气泵规格/ });
  fireEvent.change(screen.getByLabelText("此范围的近期查询"), { target: { value: result.id } });
  expect(screen.getByText("仅作线索")).toBeInTheDocument();
  view.rerender(<ResearchSearch {...props} {...scope}/>);
  expect(screen.queryByText("仅作线索")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "用于页面采集" })).not.toBeInTheDocument();
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
});

it("ignores an old scope's late search response and releases its busy state", async () => {
  let finish!: (response: Response) => void;
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (_url, init) => {
    if (init?.method === "POST") return new Promise(resolve => { finish = resolve; });
    return Response.json({ items: [] });
  });
  vi.stubGlobal("fetch", fetcher);
  const view = render(<ResearchSearch {...props}/>);
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  search();
  expect(screen.getByRole("button", { name: "正在搜索…" })).toBeDisabled();
  view.rerender(<ResearchSearch {...props} lineId="new-line"/>);
  expect(screen.getByRole("button", { name: "搜索来源" })).toBeEnabled();
  await act(async () => { finish(Response.json(result)); });
  expect(screen.queryByText("仅作线索")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "用于页面采集" })).not.toBeInTheDocument();
});
