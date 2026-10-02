import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProductAiRuns, type ProductSelection } from "./product-ai-runs";

const selection: ProductSelection = { capability: "research_planning", product_line_id: null, question: "研究下一步", sources: [] };
const prepared = { digest: "a".repeat(64), selection };
const run = { run_id: "run-one", request_id: "request-one", selection, source_digest: prepared.digest, created_at: "2026-09-29T00:00:00Z", status: "running", assessment: null, reference_labels: {}, error_code: null, invocation_id: null, sources_current: true, user_instruction: "" };
const history = { rollout: "live", can_request: true, items: [], next_before_id: null };
const props = { base: "spaces/one", capability: "research_planning", line: "", prepared };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
async function load() { fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新我的分析" })); await screen.findByText("此能力与产品线尚无你的分析记录。"); }

describe("product analysis runs", () => {
  it("shows shadow unavailability and never submits a model request", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ ...history, rollout: "shadow" }));
    vi.stubGlobal("fetch", fetcher); render(<ProductAiRuns {...props}/>);
    await load();
    expect(screen.getByText(/真实模型资格与启用待完成/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "基于已核对资料分析" })).toBeDisabled();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("retries the exact original request after network uncertainty even when preparation changes", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(history))
      .mockRejectedValueOnce(new Error("网络中断"))
      .mockResolvedValueOnce(Response.json({ ...run, status: "degraded", error_code: "MODEL_UNAVAILABLE" }));
    vi.stubGlobal("fetch", fetcher); const view = render(<ProductAiRuns {...props}/>); await load();
    fireEvent.click(screen.getByRole("button", { name: "基于已核对资料分析" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("网络中断");
    const original = JSON.parse(String(fetcher.mock.calls[1][1]?.body));
    expect(original.selection).toEqual(selection); expect(original.expected_digest).toBe(prepared.digest);
    view.rerender(<ProductAiRuns {...props} prepared={{ digest: "b".repeat(64), selection: { ...selection, question: "新问题" } }}/>);
    fireEvent.click(screen.getByRole("button", { name: "重试原请求" }));
    await screen.findByText(/本次未形成可用分析/);
    expect(JSON.parse(String(fetcher.mock.calls[2][1]?.body))).toEqual(original);
  });
  it("lets corrected input proceed after a definitive source-version rejection", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(history))
      .mockResolvedValueOnce(Response.json({ detail: { message: "资料已变化" } }, { status: 409 }));
    vi.stubGlobal("fetch", fetcher); render(<ProductAiRuns {...props}/>); await load();
    fireEvent.click(screen.getByRole("button", { name: "基于已核对资料分析" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("资料已变化");
    expect(screen.queryByRole("button", { name: "重试原请求" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "基于已核对资料分析" })).toBeEnabled();
  });
  it("allows history lookup and stopping while a generation response is pending", async () => {
    let resolve!: (response: Response) => void;
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(history))
      .mockImplementationOnce(() => new Promise(r => { resolve = r; }))
      .mockResolvedValueOnce(Response.json({ ...history, items: [run] }))
      .mockResolvedValueOnce(Response.json({ run: { ...run, status: "degraded", error_code: "APPLICATION_CANCELLED" } }));
    vi.stubGlobal("fetch", fetcher); render(<ProductAiRuns {...props}/>); await load();
    fireEvent.click(screen.getByRole("button", { name: "基于已核对资料分析" }));
    fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新我的分析" }));
    fireEvent.click(await screen.findByRole("button", { name: "停止此次分析" }));
    await screen.findByText(/本次未形成可用分析：APPLICATION_CANCELLED/);
    await act(async () => resolve(Response.json({ ...run, status: "degraded", error_code: "APPLICATION_CANCELLED" })));
    expect(fetcher.mock.calls[3][0]).toBe("/api/product-work/spaces/one/product-ai-cancel");
  });
  it("clears original sources after authorization failure and discards responses from an old scope", async () => {
    let resolve!: (response: Response) => void;
    const fetcher = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({ ...history, items: [run] }))
      .mockResolvedValueOnce(Response.json({ ...history, items: [{ ...run, frozen_sources: [{ reference_id: "a", label: "原始来源", href: "/product-work", fields: { content: "私有内容" } }] }] }))
      .mockResolvedValueOnce(Response.json({ detail: { message: "资料权限已撤销" } }, { status: 403 }))
      .mockImplementationOnce(() => new Promise(r => { resolve = r; }));
    vi.stubGlobal("fetch", fetcher); const view = render(<ProductAiRuns key="one" {...props}/>);
    fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新我的分析" }));
    fireEvent.click(await screen.findByRole("button", { name: "查看分析与原依据" }));
    await screen.findByText("原依据：原始来源");
    fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新我的分析" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("资料权限已撤销");
    expect(screen.queryByText(/私有内容/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新我的分析" }));
    view.rerender(<ProductAiRuns key="two" {...props} base="spaces/two"/>);
    await act(async () => resolve(Response.json({ ...history, items: [run] })));
    expect(screen.queryByText(/研究下一步/)).not.toBeInTheDocument();
  });
});

it("clears parent original-source content when a candidate cannot be reread", async () => {
  const current = { ...run, selection: { ...selection, capability: "competitor_analysis" }, status: "succeeded", assessment: { disposition: "analysis", summary: [], sections: [], next_steps: [], missing: [], coverage_limits: "仅原资料" }, frozen_sources: [{ reference_id: "evidence:a", label: "私有竞品来源", href: "/product-work", fields: { content: "仅原发起人可读" } }] };
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ ...history, items: [current] })).mockResolvedValueOnce(Response.json({ ...history, items: [current] })).mockResolvedValueOnce(Response.json({ detail: { message: "来源不可再读" } }, { status: 403 }));
  vi.stubGlobal("fetch", fetcher); render(<ProductAiRuns {...props} capability="competitor_analysis"/>);
  fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新我的分析" }));
  fireEvent.click(await screen.findByRole("button", { name: "查看分析与原依据" }));
  await screen.findByText(/仅原发起人可读/);
  fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新业务候选" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("来源不可再读");
  expect(screen.queryByText(/仅原发起人可读/)).not.toBeInTheDocument();
});

it("recovers the uncertain request from history without submitting it again", async () => {
  let originalId = "";
  let reads = 0;
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url, init) => {
    if (String(url).endsWith("/product-ai-runs")) {
      originalId = JSON.parse(String(init?.body)).request_id;
      throw new Error("响应中断");
    }
    reads += 1;
    return Response.json({ ...history, items: reads === 1 ? [] : [{ ...run, request_id: reads === 2 ? "another-request" : originalId, status: "succeeded" }] });
  });
  vi.stubGlobal("fetch", fetcher); render(<ProductAiRuns {...props}/>); await load();
  fireEvent.click(screen.getByRole("button", { name: "基于已核对资料分析" }));
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新我的分析" }));
  await screen.findByRole("button", { name: "查看分析与原依据" });
  expect(screen.getByRole("button", { name: "重试原请求" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新我的分析" }));
  await screen.findByText("分析已保存 · 研究下一步");
  expect(screen.queryByRole("button", { name: "重试原请求" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "基于已核对资料分析" })).toBeEnabled();
  expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith("/product-ai-runs"))).toHaveLength(1);
});

it("keeps the confirmed cancellation when an older generation response arrives late", async () => {
  let originalId = "";
  let finish!: (response: Response) => void;
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(history))
    .mockImplementationOnce((_url, init) => {
      originalId = JSON.parse(String(init?.body)).request_id;
      return new Promise(resolve => { finish = resolve; });
    })
    .mockImplementationOnce(async () => Response.json({ ...history, items: [{ ...run, request_id: originalId }] }))
    .mockImplementationOnce(async () => Response.json({ run: { ...run, request_id: originalId, status: "degraded", error_code: "APPLICATION_CANCELLED" } }));
  vi.stubGlobal("fetch", fetcher); render(<ProductAiRuns {...props}/>); await load();
  fireEvent.click(screen.getByRole("button", { name: "基于已核对资料分析" }));
  fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新我的分析" }));
  fireEvent.click(await screen.findByRole("button", { name: "停止此次分析" }));
  await screen.findByText("本次未形成可用分析：APPLICATION_CANCELLED");
  await act(async () => finish(Response.json({ ...run, request_id: originalId, status: "succeeded" })));
  expect(screen.getByText("本次未形成可用分析：APPLICATION_CANCELLED")).toBeInTheDocument();
  expect(screen.queryByText("分析已保存 · 研究下一步")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "重试原请求" })).not.toBeInTheDocument();
});

it("does not restore private results from an in-flight response after history access is revoked", async () => {
  let finish!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(history))
    .mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
    .mockResolvedValueOnce(Response.json({ detail: { message: "当前资料访问已撤销" } }, { status: 403 })));
  render(<ProductAiRuns {...props}/>); await load();
  fireEvent.click(screen.getByRole("button", { name: "基于已核对资料分析" }));
  fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新我的分析" }));
  await screen.findByText("当前资料访问已撤销");
  await act(async () => finish(Response.json({ ...run, status: "succeeded", frozen_sources: [{ reference_id: "private", label: "已撤权原文", fields: { text: "不应重新显示" } }] })));
  expect(screen.queryByText(/不应重新显示/)).not.toBeInTheDocument();
  expect(screen.queryByText("分析已保存 · 研究下一步")).not.toBeInTheDocument();
});

it("discards an in-flight result when stopping is denied after access revocation", async () => {
  let finish!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(history))
    .mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
    .mockResolvedValueOnce(Response.json({ ...history, items: [run] }))
    .mockResolvedValueOnce(Response.json({ detail: { message: "停止时权限已撤销" } }, { status: 403 })));
  render(<ProductAiRuns {...props}/>); await load();
  fireEvent.click(screen.getByRole("button", { name: "基于已核对资料分析" }));
  fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新我的分析" }));
  fireEvent.click(await screen.findByRole("button", { name: "停止此次分析" }));
  await screen.findByText("停止时权限已撤销");
  await act(async () => finish(Response.json({ ...run, status: "succeeded" })));
  expect(screen.queryByText("分析已保存 · 研究下一步")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "基于已核对资料分析" })).toBeDisabled();
});
