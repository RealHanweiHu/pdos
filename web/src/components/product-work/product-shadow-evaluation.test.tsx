import { webcrypto } from "node:crypto";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ProductShadowEvaluation } from "./product-shadow-evaluation";

const { bootstrap } = vi.hoisted(() => ({ bootstrap: vi.fn() }));
vi.mock("@/components/governance/model-governance-api", () => ({ requestModelGovernanceBootstrap: bootstrap }));
const space = "33333333-3333-4333-8333-333333333333";
const base = `spaces/${space}`;
const run = "44444444-4444-4444-8444-444444444444";
const digest = "a".repeat(64);
const runtime = "b".repeat(64);
const binding = { provider: "openai", model: "synthetic-test-model", protocol: "openai-compatible" };
const suite = (capability = "research_planning", spaceId = space) => ({
  version: "product-capability-evaluation.v1", review_status: "candidate", suite_version: "human-candidate-1",
  capability, prompt_version: "prompt.v1", runtime_sha256: runtime,
  cases: [{ case_id: "human-case-1", source_sha256: digest, source: { market_space_id: spaceId, selection: capability === "product_matrix" ? { record_id: run, roadmap_ids: [] } : { capability, product_line_id: null, question: "允许的合成问题", sources: [] } }, expected_outputs: [{ note: "合成参考，不是可信资格根" }] }],
});
const report = { evaluation_id: run, status: "passed", qualification_granted: false, report_sha256: digest, cases: [{ case_id: "human-case-1", passed: true, attempts: [{ status: "matched", error_code: null, response: { original_receipt_ref: `/api/product-work/${base}/evaluation/runs/${run}` } }] }] };
let fetcher: ReturnType<typeof vi.fn<typeof fetch>>;
beforeEach(() => {
  vi.stubGlobal("crypto", webcrypto);
  bootstrap.mockReset().mockResolvedValue({ kind: "ready", snapshot: { eligible_models: [binding], selection: { ...binding, available: true }, budget: { exhausted: false } } });
  fetcher = vi.fn<typeof fetch>().mockImplementation(async input => String(input).endsWith("/prepare")
    ? Response.json({ source_sha256: digest, runtime_sha256: runtime, prompt_version: "prompt.v1" }) : Response.json(report));
  vi.stubGlobal("fetch", fetcher);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function file(document: string | Uint8Array, name = "human-reference.json") {
  const bytes = typeof document === "string" ? new TextEncoder().encode(document) : document;
  const result = new File([bytes as BlobPart], name, { type: "application/json" });
  Object.defineProperty(result, "arrayBuffer", { value: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) });
  return result;
}

async function importAndCheck(capability = "research_planning", document = JSON.stringify(suite(capability), null, 2).replaceAll("\n", "\r\n")) {
  fireEvent.click(screen.getByRole("button", { name: "读取当前租户模型" }));
  await screen.findByText("openai · synthetic-test-model");
  fireEvent.change(screen.getByLabelText("人工参考文件"), { target: { files: [file(document)] } });
  await screen.findByText(/human-reference.json ·/);
  fireEvent.change(screen.getByLabelText("已核对的模型配置摘要"), { target: { value: "c".repeat(64) } });
  fireEvent.click(screen.getByRole("button", { name: "核对全部样例来源" }));
  await screen.findByText(/当前来源与执行版本相符/);
  fireEvent.change(screen.getByLabelText("评测编号（继续已有评测时填写）"), { target: { value: run } });
  return document;
}

it("keeps original UTF-8 bytes, checks sources, retrieves private receipts and never promotes a matched suite", async () => {
  fetcher.mockImplementation(async input => String(input).endsWith("/prepare")
    ? Response.json({ source_sha256: digest, runtime_sha256: runtime, prompt_version: "prompt.v1" })
    : String(input).includes(`/runs/${run}`) ? Response.json({ run_id: run, status: "succeeded", error_code: null, invocation_id: run, assessment: { summary: [{ nature: "hypothesis", text: "仍需验证用户需求" }], missing: ["独立调用证明"], coverage_limits: "仅合成参考" }, frozen_source: { note: "原始来源" }, business_actions_created: false, qualification_granted: false }) : Response.json(report));
  render(<ProductShadowEvaluation base={base}/>);
  const document = await importAndCheck();
  expect(fetcher).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "提交影子评测" }));
  await screen.findByText("样例比对通过，仍待人工复核与独立证明。");
  expect(screen.getByText("尚未授予能力资格。")).toBeInTheDocument();
  const body = JSON.parse(String(fetcher.mock.calls[1][1]?.body));
  expect(body.suite_document).toBe(document);
  const actual = await webcrypto.subtle.digest("SHA-256", new TextEncoder().encode(document));
  expect(body.suite_sha256).toBe(Buffer.from(actual).toString("hex"));
  expect(body.binding).toEqual({ ...binding, configuration_sha256: "c".repeat(64) });
  expect(screen.getByLabelText("人工参考文件")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "重新取回本次评测" }));
  await screen.findByText("样例比对通过，仍待人工复核与独立证明。");
  expect(JSON.parse(String(fetcher.mock.calls[2][1]?.body))).toEqual(body);
  fireEvent.click(screen.getByRole("button", { name: "查看human-case-1原回执" }));
  await screen.findByText("待验证：仍需验证用户需求");
  expect(fetcher.mock.calls[3][0]).toBe(`/api/product-work/${base}/evaluation/runs/${run}`);
  expect(screen.queryByRole("button", { name: /应用|发布|授予/ })).not.toBeInTheDocument();
});

it("retries the exact evaluation after a lost response and uses a supplied resume identifier", async () => {
  let calls = 0;
  fetcher.mockImplementation(async input => String(input).endsWith("/prepare") ? Response.json({ source_sha256: digest, runtime_sha256: runtime, prompt_version: "prompt.v1" }) : ++calls === 1
    ? Response.json({ detail: { message: "回执未返回" } }, { status: 503 }) : Response.json(report));
  render(<ProductShadowEvaluation base={base}/>);
  await importAndCheck();
  fireEvent.change(screen.getByLabelText("评测编号（继续已有评测时填写）"), { target: { value: run } });
  fireEvent.click(screen.getByRole("button", { name: "提交影子评测" }));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("已核对的模型配置摘要")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "重试原评测请求" }));
  await screen.findByText("样例比对通过，仍待人工复核与独立证明。");
  const body = JSON.parse(String(fetcher.mock.calls[1][1]?.body));
  expect(body.evaluation_id).toBe(run);
  expect(JSON.parse(String(fetcher.mock.calls[2][1]?.body))).toEqual(body);
});

it.each(["research_planning", "product_matrix"])("blocks execution when %s sources have changed", async capability => {
  fetcher.mockResolvedValue(Response.json({ source_sha256: "d".repeat(64), runtime_sha256: runtime, prompt_version: "prompt.v1" }));
  render(<ProductShadowEvaluation base={base}/>);
  fireEvent.change(screen.getByLabelText("人工参考文件"), { target: { files: [file(JSON.stringify(suite(capability)))] } });
  await screen.findByText(/human-reference.json ·/);
  fireEvent.click(screen.getByRole("button", { name: "核对全部样例来源" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("来源或执行版本已变化");
  expect(screen.getByRole("button", { name: "提交影子评测" })).toBeDisabled();
  expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual({ capability, [capability === "product_matrix" ? "matrix" : "work"]: suite(capability).cases[0].source.selection });
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("clears previously visible reports and receipts when current authority is refused", async () => {
  render(<ProductShadowEvaluation base={base}/>);
  await importAndCheck();
  fireEvent.click(screen.getByRole("button", { name: "提交影子评测" }));
  await screen.findByText("样例比对通过，仍待人工复核与独立证明。");
  fetcher.mockResolvedValue(Response.json({ detail: { message: "来源权限已撤回" } }, { status: 403 }));
  fireEvent.click(screen.getByRole("button", { name: "查看human-case-1原回执" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("来源权限已撤回");
  expect(screen.queryByText(/human-reference.json ·/)).not.toBeInTheDocument();
  expect(screen.queryByText("样例比对通过，仍待人工复核与独立证明。")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "重试原评测请求" })).not.toBeInTheDocument();
});

it("rechecks current source authority before exporting a previously matched report", async () => {
  render(<ProductShadowEvaluation base={base}/>);
  await importAndCheck();
  fireEvent.click(screen.getByRole("button", { name: "提交影子评测" }));
  await screen.findByText("样例比对通过，仍待人工复核与独立证明。");
  fetcher.mockResolvedValue(Response.json({ detail: { message: "导出前来源权限已撤回" } }, { status: 403 }));
  fireEvent.click(screen.getByRole("button", { name: "下载评测报告" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("导出前来源权限已撤回");
  expect(fetcher.mock.calls[2][0]).toBe(`/api/product-work/${base}/evaluation/prepare`);
  expect(screen.queryByRole("button", { name: "下载评测报告" })).not.toBeInTheDocument();
  expect(screen.queryByText(/human-reference.json ·/)).not.toBeInTheDocument();
});

it.each(["wrong-space", "invalid-json", "invalid-utf8", "too-large"])("rejects %s reference files before any server request", async kind => {
  render(<ProductShadowEvaluation base={base}/>);
  const original = kind === "invalid-utf8" ? file(new Uint8Array([0xff, 0xfe])) : file(kind === "invalid-json" ? "not json" : JSON.stringify(suite("research_planning", kind === "wrong-space" ? run : space)));
  if (kind === "too-large") Object.defineProperty(original, "size", { value: 4 * 1024 * 1024 + 1 });
  fireEvent.change(screen.getByLabelText("人工参考文件"), { target: { files: [original] } });
  await screen.findByRole("alert");
  expect(screen.getByRole("button", { name: "提交影子评测" })).toBeDisabled();
  expect(fetcher).not.toHaveBeenCalled();
});

it("does not request a provider when the current model budget is exhausted", async () => {
  bootstrap.mockResolvedValue({ kind: "ready", snapshot: { eligible_models: [binding], selection: { ...binding, available: true }, budget: { exhausted: true } } });
  render(<ProductShadowEvaluation base={base}/>);
  fireEvent.click(screen.getByRole("button", { name: "读取当前租户模型" }));
  await screen.findByText("当前模型预算已用完。");
  expect(screen.getByRole("button", { name: "提交影子评测" })).toBeDisabled();
  expect(fetcher).not.toHaveBeenCalled();
});

it("does not turn an external or another space's receipt link into a request", async () => {
  fetcher.mockImplementation(async input => String(input).endsWith("/prepare")
    ? Response.json({ source_sha256: digest, runtime_sha256: runtime, prompt_version: "prompt.v1" })
    : Response.json({ ...report, cases: [{ ...report.cases[0], attempts: [{ ...report.cases[0].attempts[0], response: { original_receipt_ref: `https://example.invalid/api/product-work/${base}/evaluation/runs/${run}` } }] }] }));
  render(<ProductShadowEvaluation base={base}/>);
  await importAndCheck();
  fireEvent.click(screen.getByRole("button", { name: "提交影子评测" }));
  await screen.findByText("样例比对通过，仍待人工复核与独立证明。");
  expect(screen.queryByRole("button", { name: "查看human-case-1原回执" })).not.toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it.each([503, 408, 429, "network", "json", 409] as const)("preserves original bytes and pending semantics for %s", async failure => {
  const pending = vi.fn();
  const view = render(<ProductShadowEvaluation base={base} onPendingChange={pending}/>);
  await importAndCheck();
  fetcher.mockImplementation(async () => {
    if (failure === "network") throw new TypeError("lost response");
    if (failure === "json") return new Response("not JSON");
    return Response.json({ detail: { message: "未确认" } }, { status: failure });
  });
  fireEvent.click(screen.getByRole("button", { name: "提交影子评测" }));
  await screen.findByRole("alert");
  expect(pending.mock.calls).toEqual(failure === 409 ? [[true], [false]] : [[true]]);
  expect(screen.getByText(`本次评测编号：${run}`)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "准备另一轮评测" })).toHaveProperty("disabled", failure !== 409);
  view.rerender(<ProductShadowEvaluation base={base} onPendingChange={pending}/>);
  const original = fetcher.mock.calls[1][1]?.body;
  fetcher.mockResolvedValue(Response.json(report));
  fireEvent.click(screen.getByRole("button", { name: "重试原评测请求" }));
  await screen.findByText("样例比对通过，仍待人工复核与独立证明。");
  expect(fetcher.mock.calls[2][1]?.body).toBe(original);
  expect(pending).toHaveBeenLastCalledWith(false);
  expect(screen.getByRole("button", { name: "准备另一轮评测" })).toBeEnabled();
});
it.each([401, 403])("clears private evaluation state and releases parent on %s", async status => {
  const pending = vi.fn(), denied = vi.fn();
  render(<ProductShadowEvaluation base={base} onPendingChange={pending} onAuthorityLost={denied}/>);
  await importAndCheck();
  fireEvent.change(screen.getByLabelText("原运行编号"), { target: { value: run } });
  fetcher.mockResolvedValue(Response.json({ detail: { message: "评测访问撤回" } }, { status }));
  fireEvent.click(screen.getByRole("button", { name: "提交影子评测" }));
  await screen.findByRole("alert");
  expect(pending.mock.calls).toEqual([[true], [false]]);
  expect(denied).toHaveBeenCalledWith("评测访问撤回");
  for (const label of ["已核对的模型配置摘要", "评测编号（继续已有评测时填写）", "原运行编号"]) expect(screen.getByLabelText(label)).toHaveValue("");
  expect(screen.queryByText(/human-reference.json ·/)).not.toBeInTheDocument();
  expect(screen.queryByText("openai · synthetic-test-model")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "重试原评测请求" })).not.toBeInTheDocument();
});
it("fences a late report on base change and releases previous pending scope", async () => {
  let finish!: (response: Response) => void;
  const pending = vi.fn();
  const view = render(<ProductShadowEvaluation base={base} onPendingChange={pending}/>);
  await importAndCheck();
  fetcher.mockReturnValueOnce(new Promise<Response>(resolve => { finish = resolve; }));
  fireEvent.click(screen.getByRole("button", { name: "提交影子评测" }));
  expect(pending).toHaveBeenLastCalledWith(true);
  view.rerender(<ProductShadowEvaluation base={`spaces/${run}`} onPendingChange={pending}/>);
  expect(pending).toHaveBeenLastCalledWith(false);
  await act(async () => finish(Response.json(report)));
  expect(screen.queryByText("样例比对通过，仍待人工复核与独立证明。")).not.toBeInTheDocument();
  expect(screen.getByLabelText("评测编号（继续已有评测时填写）")).toHaveValue("");
});
