import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ProductSourceFiles } from "./product-source-files";
import { ProductRfqProposal } from "./product-rfq-proposal";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const file = { id: "original", filename: "私有客户RFQ.xlsx", classification: "internal", status: "extracted", error_code: null, revoked_at: null, size_bytes: 100, fragment_count: 2 };
const original = { ...file, fragments: [{ ordinal: 1, locator: "cell:C1", text: "私有客户原文120 kPa" }], next_after: 1 };
const selection = { capability: "rfq_requirements", product_line_id: "line", question: "私有抽取问题", sources: [{ kind: "file", id: file.id, ordinals: [1] }] };
const item = { title: "私有压力候选", description: "120 kPa", priority: "high", acceptance_criteria: [], missing: ["工况待澄清"], category_label: null, basis: { nature: "observed", text: "原文要求", citations: [{ reference_id: "file:original:1", digest: "a".repeat(64), field_path: ["text"], quoted_value: "私有候选引用120 kPa" }] } };
const detail = { finding: { id: "finding", status: "pending_review", proposed_digest: "b".repeat(64) }, items: [item], sources_current: true, references: [{ reference_id: "file:original:1", label: "客户原件cell:C1" }], records: [] };
const run = { run_id: "run-one", request_id: "request-one", selection, source_digest: "a".repeat(64), user_instruction: "", created_at: "2026-09-30T00:00:00Z", status: "succeeded", assessment: { disposition: "analysis", summary: [], sections: [], next_steps: [], missing: [], coverage_limits: "合成分析覆盖" }, reference_labels: {}, error_code: null, invocation_id: null, sources_current: true, frozen_sources: [{ reference_id: "file:original:1", label: "私有固定原文", href: "/product-work", fields: { text: "私有固定快照" } }] };
const history = { rollout: "live", can_request: true, items: [run], next_before_id: null };
const props = { base: "spaces/one", lineId: "line" };
function setup() {
  const state = { denied: "", status: 403, nonJson: false, unknown: false, applied: false, readOnly: false };
  const fetcher = vi.fn<typeof fetch>(async (url, init) => {
    const path = String(url);
    if (state.denied && path.includes(state.denied)) return state.nonJson ? new Response("permission denied", { status: state.status }) : Response.json({ detail: { message: "RFQ范围已撤权" } }, { status: state.status });
    if (path.includes("source-files/original?")) return Response.json(original);
    if (path.includes("source-files")) return Response.json({ items: [file], truncated: false });
    if (path.endsWith("product-ai-context")) return Response.json({ digest: "a".repeat(64) });
    if (path.endsWith("product-ai-history")) return Response.json({ ...history, can_request: !state.readOnly });
    if (path.endsWith("product-ai-runs")) return Response.json(run);
    if (path.endsWith("rfq-ai-finding")) return Response.json(state.applied ? { ...detail, finding: { ...detail.finding, status: "applied" }, items: [{ ...item, title: "服务端实际登记" }], records: [{ requirement_id: "requirement", accepted_item: item }] } : detail);
    if (path.endsWith("rfq-ai-confirm")) return state.unknown ? Response.json({ detail: { message: "确认回执未知" } }, { status: 503 }) : Response.json({ finding: { ...detail.finding, status: "applied" }, records: [{ requirement_id: "requirement", accepted_item: item }] });
    throw new Error(`unexpected ${path} ${init?.method}`);
  });
  vi.stubGlobal("fetch", fetcher);
  const pending = vi.fn(), view = render(<ProductSourceFiles {...props} onPendingChange={pending}/>);
  return { state, fetcher, pending, view };
}
const click = (name: string) => fireEvent.click(screen.getByRole("button", { name }));
async function prepare() {
  fireEvent.click(await screen.findByRole("button", { name: "核对原文与出处" }));
  fireEvent.click(await screen.findByLabelText("cell:C1"));
  fireEvent.change(screen.getByLabelText("抽取要求"), { target: { value: selection.question } });
  click("核对所选原文范围"); await screen.findByText(/已核对1段原文/);
}
async function candidate(wait = true) {
  click("读取 / 刷新我的分析");
  fireEvent.click(await screen.findByRole("button", { name: "查看分析与原依据" }));
  if (wait) await screen.findByLabelText("核对说明");
}
async function uncertain(state: { unknown: boolean }) {
  state.unknown = true;
  fireEvent.change(screen.getByLabelText("名称"), { target: { value: "人工核对压力" } });
  fireEvent.change(screen.getByLabelText("核对说明"), { target: { value: "人工已核对原文" } });
  click("确认并登记需求草稿"); await screen.findByText("确认回执未知");
}
function cleared() {
  for (const text of ["私有客户原文120 kPa", "私有候选引用120 kPa"]) expect(screen.queryByText(text)).not.toBeInTheDocument();
  for (const label of ["抽取要求", "名称"]) expect(screen.queryByLabelText(label)).not.toBeInTheDocument();
  expect(screen.queryByText(/已核对1段原文/)).not.toBeInTheDocument();
  expect(screen.queryByText(/私有固定快照/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "上传RFQ或客户原件" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: "重试原确认" })).not.toBeInTheDocument();
}
it.each(["source-files/original?", "product-ai-context", "product-ai-history", "rfq-ai-finding", "rfq-ai-confirm"])("clears the actual file parent on %s denial", async path => {
  const { state } = setup(); await prepare();
  if (path === "rfq-ai-finding") { state.denied = path; await candidate(false); }
  if (path === "rfq-ai-confirm") await candidate();
  state.denied = path;
  if (path === "source-files/original?") click("读取后续原文");
  if (path === "product-ai-context") click("核对所选原文范围");
  if (path === "product-ai-history") click("读取 / 刷新我的分析");
  if (path === "rfq-ai-confirm") { fireEvent.change(screen.getByLabelText("核对说明"), { target: { value: "已核对" } }); click("确认并登记需求草稿"); }
  await screen.findByText("RFQ范围已撤权"); cleared();
});
it.each([401, 403])("recognizes a non-JSON %s original-confirmation query denial", async status => {
  const { state } = setup(); await prepare(); await candidate(); await uncertain(state);
  Object.assign(state, { denied: "rfq-ai-finding", status, nonJson: true }); click("查询确认结果");
  await screen.findByText("产品工作暂不可用，请重试"); cleared();
});
it("locks originals and run switching while exact original confirmation retry remains available", async () => {
  const { state, fetcher, pending } = setup(); await prepare(); await candidate(); await uncertain(state);
  for (const label of ["资料级别", "cell:C1", "抽取要求"]) expect(screen.getByLabelText(label)).toBeDisabled();
  for (const name of ["停止引用此原件", "收起原文", "查看分析与原依据", "基于已核对资料分析"]) expect(screen.getByRole("button", { name })).toBeDisabled();
  expect(screen.getByRole("button", { name: "重试原确认" })).toBeEnabled(); expect(pending).toHaveBeenLastCalledWith(true);
  state.unknown = false; click("重试原确认"); await screen.findByText(/已登记1项需求草稿/);
  const writes = fetcher.mock.calls.filter(([path]) => String(path).endsWith("rfq-ai-confirm"));
  expect(writes).toHaveLength(2); expect(writes[0][1]?.body).toBe(writes[1][1]?.body);
  expect(screen.getByLabelText("抽取要求")).toBeEnabled(); await waitFor(() => expect(pending).toHaveBeenLastCalledWith(false));
});
it("queries a committed confirmation while current capability becomes read-only", async () => {
  const { state, fetcher } = setup(); await prepare(); await candidate(); await uncertain(state);
  state.readOnly = true; state.applied = true; click("读取 / 刷新我的分析"); await screen.findByText("当前范围只读，不能发起分析。");
  expect(screen.getByRole("button", { name: "重试原确认" })).toBeDisabled(); click("查询确认结果"); await screen.findByText(/已登记1项需求草稿/);
  expect(screen.getByLabelText("名称")).toHaveValue("服务端实际登记"); expect(fetcher.mock.calls.filter(([path]) => String(path).endsWith("rfq-ai-confirm"))).toHaveLength(1);
});
it("ignores late original context after a history access denial", async () => {
  const { state, fetcher } = setup(); await prepare(); let finish!: (response: Response) => void;
  fetcher.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; })); click("核对所选原文范围");
  state.denied = "product-ai-history"; click("读取 / 刷新我的分析"); await screen.findByText("RFQ范围已撤权");
  await act(async () => finish(Response.json({ digest: "a".repeat(64) }))); cleared();
});
it.each(["workspace", "line"])("resets RFQ content and ignores late reads after %s changes without a caller key", async scope => {
  const { fetcher, view } = setup(); await prepare(); let finish!: (response: Response) => void;
  fetcher.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; })); click("读取后续原文");
  view.rerender(<ProductSourceFiles base={scope === "workspace" ? "spaces/two" : props.base} lineId={scope === "line" ? "line-two" : props.lineId}/>);
  await screen.findByRole("button", { name: "核对原文与出处" });
  await act(async () => finish(Response.json({ ...original, fragments: [{ ordinal: 2, locator: "cell:C2", text: "旧范围迟到原文" }] })));
  expect(screen.queryByText("旧范围迟到原文")).not.toBeInTheDocument(); expect(screen.queryByLabelText("抽取要求")).not.toBeInTheDocument(); expect(screen.queryByText(/已核对1段原文/)).not.toBeInTheDocument();
});
it("keeps a pending RFQ confirmation when an already-requested history read returns another run", async () => {
  const { fetcher, state } = setup(); await prepare(); await candidate(); let finish!: (response: Response) => void;
  fetcher.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; })); click("查看分析与原依据"); await uncertain(state);
  await act(async () => finish(Response.json({ ...history, items: [{ ...run, run_id: "other-run", selection: { ...selection, question: "其他分析" } }] })));
  expect(screen.getByRole("button", { name: "重试原确认" })).toBeEnabled(); expect(screen.getByLabelText("名称")).toHaveValue("人工核对压力");
});
it.each([408, 429])("retains an immutable original confirmation after %s", async status => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(detail)).mockResolvedValueOnce(Response.json({}, { status })).mockResolvedValueOnce(Response.json({ finding: { ...detail.finding, status: "applied" }, records: [] }));
  vi.stubGlobal("fetch", fetcher); render(<ProductRfqProposal base={props.base} runId="run-one" onFailure={vi.fn()}/>);
  fireEvent.change(await screen.findByLabelText("核对说明"), { target: { value: "已核对" } }); click("确认并登记需求草稿"); await screen.findByRole("alert");
  expect(screen.getByRole("button", { name: "重试原确认" })).toBeEnabled(); fireEvent.change(screen.getByLabelText("名称"), { target: { value: "不能替换原请求" } }); click("重试原确认");
  await screen.findByText(/已登记0项需求草稿/); expect(fetcher.mock.calls[1][1]?.body).toBe(fetcher.mock.calls[2][1]?.body);
});
it("sends only one decision for synchronous duplicate accept and reject clicks", async () => {
  let finish!: (response: Response) => void;
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(detail)).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  vi.stubGlobal("fetch", fetcher); render(<ProductRfqProposal base={props.base} runId="run-one" onFailure={vi.fn()}/>);
  fireEvent.change(await screen.findByLabelText("核对说明"), { target: { value: "已核对" } });
  const accept = screen.getByRole("button", { name: "确认并登记需求草稿" }), reject = screen.getByRole("button", { name: "拒绝此批候选" });
  act(() => { fireEvent.click(accept); fireEvent.click(reject); fireEvent.click(accept); }); expect(fetcher).toHaveBeenCalledTimes(2);
  await act(async () => finish(Response.json({ finding: { ...detail.finding, status: "applied" }, records: [] })));
});
it("restores authorized files without restoring a denied private question or selection", async () => {
  const { state } = setup(); await prepare(); state.denied = "product-ai-history"; click("读取 / 刷新我的分析"); await screen.findByText("RFQ范围已撤权");
  state.denied = ""; click("重新核对文件权限"); fireEvent.click(await screen.findByRole("button", { name: "核对原文与出处" }));
  expect(await screen.findByLabelText("抽取要求")).toHaveValue(""); expect(screen.getByLabelText("cell:C1")).not.toBeChecked();
});
it("opens a linked private attachment RFQ run through the real candidate and confirms once without sharing its original file", async () => {
  const privateRun = { ...run, selection: { ...selection, sources: [{ kind: "private_attachment", conversation_id: "private-cid", id: "private-file", ordinals: [4] }] } }; const fetcher = vi.fn<typeof fetch>(async url => String(url).includes("source-files") ? Response.json({ items: [], truncated: false }) : String(url).endsWith("rfq-ai-finding") ? Response.json(detail) : String(url).endsWith("rfq-ai-confirm") ? Response.json({ finding: { ...detail.finding, status: "applied" }, records: [{ requirement_id: "requirement", accepted_item: item }] }) : Response.json({ ...history, items: [privateRun] })); vi.stubGlobal("fetch", fetcher); render(<ProductSourceFiles {...props} initialRunId={run.run_id}/>); await screen.findByLabelText("核对说明"); fireEvent.change(screen.getByLabelText("核对说明"), { target: { value: "核对原私有片段并登记需求草稿" } }); click("确认并登记需求草稿"); await waitFor(() => expect(screen.getByRole("link", { name: "查看需求池" })).toHaveAttribute("href", "/requirements")); expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith("rfq-ai-confirm"))).toHaveLength(1); expect(fetcher.mock.calls.find(([url]) => String(url).endsWith("product-ai-run-read"))?.[1]?.body).toBe(JSON.stringify({ run_id: run.run_id })); expect(fetcher.mock.calls.some(([url, options]) => String(url).includes("source-files") && options?.method === "POST")).toBe(false);
});
it("does not expose a linked RFQ candidate when the server receipt belongs to another product line", async () => {
  const fetcher = vi.fn<typeof fetch>(async url => String(url).includes("source-files") ? Response.json({ items: [], truncated: false }) : Response.json({ ...history, items: [{ ...run, selection: { ...selection, product_line_id: "other-line" } }] })); vi.stubGlobal("fetch", fetcher); render(<ProductSourceFiles {...props} initialRunId={run.run_id}/>); await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2)); expect(fetcher.mock.calls.some(([url]) => String(url).endsWith("rfq-ai-finding"))).toBe(false); expect(screen.queryByLabelText("核对说明")).not.toBeInTheDocument();
});
