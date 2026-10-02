import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ProductAiPreparation } from "./product-ai-preparation";
import { ProductAiRuns } from "./product-ai-runs";
import type { ProductCatalog } from "./product-work-api";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const catalog = { nodes: [], members: [], line_access: {}, can_create_line: false } as ProductCatalog;
const selection = { capability: "research_planning", product_line_id: null, question: "私有待研究问题", sources: [] };
const prepared = { digest: "a".repeat(64), selection };
const row = { run_id: "run-one", request_id: "request-one", selection, source_digest: prepared.digest, user_instruction: "", created_at: "2026-09-30T00:00:00Z", status: "running", assessment: null, reference_labels: {}, error_code: null, invocation_id: null, sources_current: true };
const history = { rollout: "live", can_request: true, items: [], next_before_id: null };
const source = { id: "source", kind: "research", label: "私有研究来源", as_of: "2026-09-30T00:00:00Z" };
const context = { digest: prepared.digest, warnings: [], coverage_limits: [], references: [{ reference_id: "research:source", label: "私有准备原文", href: "/product-work", fields: { text: "不可保留的私有原文" } }] };
const props = { base: "spaces/one", capability: selection.capability, line: "", prepared };
function setupPreparation() {
  const state = { denied: "", status: 403, readOnly: false };
  const fetcher = vi.fn<typeof fetch>(async url => {
    const path = String(url);
    if (state.denied && path.endsWith(state.denied)) return Response.json({ detail: { message: "产品分析范围已撤权" } }, { status: state.status });
    if (path.endsWith("product-ai-options")) return Response.json({ items: [source], next_offset: null });
    if (path.endsWith("product-ai-context")) return Response.json(context);
    if (path.endsWith("products")) return Response.json(catalog);
    return Response.json({ ...history, can_request: !state.readOnly });
  });
  vi.stubGlobal("fetch", fetcher);
  const view = render(<ProductAiPreparation base={props.base} capability={props.capability} catalog={catalog}/>);
  fireEvent.click(screen.getByText("小Pai · 核对本次产品工作资料"));
  return { state, fetcher, view };
}
async function prepare() {
  fireEvent.click(screen.getByRole("button", { name: "读取可用来源" }));
  fireEvent.click(await screen.findByRole("checkbox"));
  fireEvent.change(screen.getByLabelText("本次需要解决的问题"), { target: { value: selection.question } });
  fireEvent.click(screen.getByRole("button", { name: "核对资料与缺项" }));
  await screen.findByText("私有准备原文");
}
async function loadRuns() {
  fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新我的分析" }));
  await screen.findByText("此能力与产品线尚无你的分析记录。");
}

it.each(["product-ai-history", "product-ai-runs", "product-ai-context", "product-ai-options"])("clears prepared private content, question and run inputs on %s denial", async path => {
  const { state } = setupPreparation(); await prepare(); await loadRuns(); state.denied = path;
  fireEvent.click(screen.getByRole("button", { name: path === "product-ai-runs" ? "基于已核对资料分析" : path === "product-ai-history" ? "读取 / 刷新我的分析" : path === "product-ai-options" ? "读取可用来源" : "核对资料与缺项" }));
  await screen.findByText("产品分析范围已撤权");
  expect(screen.queryByText("私有准备原文")).not.toBeInTheDocument();
  expect(screen.queryByText(/不可保留的私有原文/)).not.toBeInTheDocument();
  expect(screen.getByLabelText("本次需要解决的问题")).toHaveValue("");
  expect(screen.queryByRole("button", { name: /移除私有研究来源/ })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "基于已核对资料分析" })).toBeDisabled();
});

it("does not replace the unconfirmed original request by resuming another historical run", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ ...history, items: [row] })).mockRejectedValueOnce(new TypeError("响应丢失"));
  vi.stubGlobal("fetch", fetcher); render(<ProductAiRuns {...props}/>);
  fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新我的分析" }));
  await screen.findByRole("button", { name: "取回原运行结果" });
  fireEvent.click(screen.getByRole("button", { name: "基于已核对资料分析" })); await screen.findByRole("alert");
  expect(screen.getByRole("button", { name: "取回原运行结果" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "重试原请求" })).toBeEnabled();
});

it.each([408, 429])("retains the exact original request after an uncertain %s response", async status => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(history)).mockResolvedValueOnce(Response.json({ detail: { message: "回执未确认" } }, { status }));
  vi.stubGlobal("fetch", fetcher); render(<ProductAiRuns {...props}/>); await loadRuns();
  fireEvent.click(screen.getByRole("button", { name: "基于已核对资料分析" })); await screen.findByRole("alert");
  expect(screen.getByRole("button", { name: "重试原请求" })).toBeEnabled();
});

it("ignores a late history response after the run progress query revokes access", async () => {
  let finish!: (value: Response) => void;
  const denied = vi.fn();
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ ...history, items: [row] })).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; })).mockResolvedValueOnce(Response.json({ detail: { message: "进度读取已撤权" } }, { status: 403 }));
  vi.stubGlobal("fetch", fetcher); render(<ProductAiRuns {...props} onAuthorityDenied={denied}/>);
  fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新我的分析" })); await screen.findByRole("button", { name: "查看分析与原依据" });
  fireEvent.click(screen.getByRole("button", { name: "查看分析与原依据" }));
  const summary = screen.getByText("查看运行详情"), details = summary.closest("details")!;
  details.open = true; fireEvent(details, new Event("toggle"));
  await waitFor(() => expect(denied).toHaveBeenCalledOnce());
  await act(async () => finish(Response.json({ ...history, items: [{ ...row, status: "succeeded", frozen_sources: [{ reference_id: "secret", label: "迟到私有原文", fields: { text: "不应恢复" } }] }] })));
  expect(screen.queryByText(/不应恢复/)).not.toBeInTheDocument();
});

it.each(["workspace", "line", "capability"])("resets preparation when the %s changes without a caller key", async kind => {
  const { view } = setupPreparation(); await prepare();
  view.rerender(<ProductAiPreparation base={kind === "workspace" ? "spaces/two" : props.base} capability={kind === "capability" ? "competitor_analysis" : props.capability} initialLine={kind === "line" ? "line-two" : ""} catalog={catalog}/>);
  expect(screen.queryByText("私有准备原文")).not.toBeInTheDocument();
  expect(screen.getByLabelText("本次需要解决的问题")).toHaveValue("");
});

it.each(["research_planning", "competitor_analysis", "rfq_requirements"])("propagates %s candidate denial through real components to the original preparation", async capability => {
  const current = { ...row, selection: { ...selection, capability }, status: "succeeded", assessment: { disposition: "analysis", summary: [], sections: [], next_steps: [], missing: [], coverage_limits: "合成覆盖" } };
  const fetcher = vi.fn<typeof fetch>(async (url, init) => {
    const path = String(url);
    if (path.endsWith("product-ai-context")) return Response.json(context);
    if (path.endsWith("product-ai-options")) return Response.json({ items: [source], next_offset: null });
    if (path.endsWith("product-ai-history")) return Response.json({ ...history, items: [current] });
    if (path.endsWith("-ai-finding")) return Response.json({ detail: { message: "候选来源已撤权" } }, { status: 403 });
    throw new Error(`unexpected request ${path} ${init?.method}`);
  });
  vi.stubGlobal("fetch", fetcher); render(<ProductAiPreparation base={props.base} capability={capability} catalog={catalog}/>);
  fireEvent.click(screen.getByText("小Pai · 核对本次产品工作资料")); await prepare();
  fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新我的分析" }));
  fireEvent.click(await screen.findByRole("button", { name: "查看分析与原依据" }));
  if (capability !== "rfq_requirements") fireEvent.click(await screen.findByRole("button", { name: capability === "research_planning" ? "读取 / 刷新研究候选" : "读取 / 刷新业务候选" }));
  await screen.findByText("候选来源已撤权");
  expect(screen.queryByText("私有准备原文")).not.toBeInTheDocument();
  expect(screen.getByLabelText("本次需要解决的问题")).toHaveValue("");
  expect(screen.queryByText(/合成覆盖/)).not.toBeInTheDocument();
});

it("retains confirmed original results when history refresh only fails with a server error", async () => {
  const current = { ...row, status: "succeeded", frozen_sources: [{ reference_id: "source", label: "已确认原文", fields: { text: "已保存来源内容" } }] };
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ ...history, items: [current] })).mockResolvedValueOnce(Response.json({ ...history, items: [current] })).mockResolvedValueOnce(Response.json({ detail: { message: "历史刷新暂不可用" } }, { status: 503 }));
  vi.stubGlobal("fetch", fetcher); render(<ProductAiRuns {...props}/>);
  fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新我的分析" }));
  fireEvent.click(await screen.findByRole("button", { name: "查看分析与原依据" }));
  await screen.findByText(/已保存来源内容/);
  fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新我的分析" }));
  await screen.findByText("历史刷新暂不可用");
  expect(screen.getByText(/已保存来源内容/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "查看分析与原依据" })).toBeInTheDocument();
});

it("discards a late preparation response after history access revokes the owning scope", async () => {
  const { state, fetcher } = setupPreparation(); await prepare();
  let finish!: (value: Response) => void;
  fetcher.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  fireEvent.click(screen.getByRole("button", { name: "核对资料与缺项" }));
  state.denied = "product-ai-history";
  fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新我的分析" }));
  await screen.findByText("产品分析范围已撤权");
  await act(async () => finish(Response.json(context)));
  expect(screen.queryByText("私有准备原文")).not.toBeInTheDocument();
  expect(screen.getByLabelText("本次需要解决的问题")).toHaveValue("");
});

it("sends only one model request for immediate duplicate clicks and preserves its immutable input", async () => {
  let finish!: (value: Response) => void;
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(history)).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  vi.stubGlobal("fetch", fetcher); render(<ProductAiRuns {...props}/>); await loadRuns();
  const button = screen.getByRole("button", { name: "基于已核对资料分析" });
  act(() => { fireEvent.click(button); fireEvent.click(button); });
  expect(fetcher.mock.calls.filter(([path]) => String(path).endsWith("product-ai-runs"))).toHaveLength(1);
  await act(async () => finish(Response.json({ ...row, status: "succeeded" })));
});

it("propagates a denied stop request to clear prepared private inputs", async () => {
  const { state, fetcher } = setupPreparation(); await prepare();
  fetcher.mockResolvedValueOnce(Response.json({ ...history, items: [row] }));
  fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新我的分析" }));
  await screen.findByRole("button", { name: "停止此次分析" });
  state.denied = "product-ai-cancel";
  fireEvent.click(screen.getByRole("button", { name: "停止此次分析" }));
  await screen.findByText("产品分析范围已撤权");
  expect(screen.queryByText("私有准备原文")).not.toBeInTheDocument();
  expect(screen.getByLabelText("本次需要解决的问题")).toHaveValue("");
});

it("restores empty input only after rereading sources and the currently authorized product catalog", async () => {
  const { state, fetcher, view } = setupPreparation();
  const oldCatalog = { ...catalog, nodes: [{ id: "old-line", level: "line", name: "已撤权私有产品线" }] } as ProductCatalog;
  view.rerender(<ProductAiPreparation base={props.base} capability={props.capability} catalog={oldCatalog}/>);
  await prepare(); state.denied = "product-ai-history";
  fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新我的分析" }));
  await screen.findByText("产品分析范围已撤权");
  state.denied = "";
  fireEvent.click(screen.getByRole("button", { name: "读取可用来源" }));
  const checkbox = await screen.findByRole("checkbox");
  expect(checkbox).not.toBeChecked();
  expect(screen.getByLabelText("本次需要解决的问题")).toBeEnabled();
  expect(screen.getByLabelText("本次需要解决的问题")).toHaveValue("");
  expect(screen.queryByRole("option", { name: "已撤权私有产品线" })).not.toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([path]) => String(path).endsWith("/products"))).toHaveLength(1);
});
