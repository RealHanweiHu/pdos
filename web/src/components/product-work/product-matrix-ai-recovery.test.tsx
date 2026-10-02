import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ProductMatrixPreparation } from "./product-matrix-preparation";
import { ProductMatrixRuns } from "./product-matrix-runs";

vi.mock("@/components/ai/agent-run-progress", () => ({ AgentRunProgressPanel: ({ runId, requestProgress }: { runId: string; requestProgress: (id: string) => Promise<unknown> }) => <button onClick={() => void requestProgress(runId).catch(() => {})}>合成查询运行进度</button> }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

const preparation = {
  selection: { record_id: "record", roadmap_ids: ["roadmap"] }, digest: "a".repeat(64),
  projection_version: "synthetic.v1", prompt_version: "synthetic.v1", product_ids: ["product"], criterion_keys: ["criterion"],
  generation_message: "合成资料已核对", model_context: { coverage_limits: [], omitted_references: [], references: [
    { reference_id: "record:product:product", label: "私有准备依据", fields: { secret: "私有准备原字段" }, digest: "source", href: null, omitted_fields: [] },
  ] },
};
const options = { record_id: "record", title: "私有对照名称", products: [{ product_id: "product", code: "P", name: "私有选项产品", roadmap: { id: "roadmap", version: 1, state: "published", created_at: "2026-09-30T00:00:00Z", reason: "合成计划" } }] };
function receipt(requestId = "saved-request", status = "succeeded") {
  return { run_id: "run", request_id: requestId, status, created_at: "2026-09-30T00:00:00Z", sources_current: true,
    user_instruction: "原私有要求", source_digest: preparation.digest, selection: preparation.selection,
    frozen_sources: [{ reference_id: "private", label: "私有运行依据", fields: { secret: "私有运行原字段" } }],
  };
}
function setup(withPreparation = false) {
  const state = { deniedPath: "", denialStatus: 403, failPost: false, failHistory: false, posted: false, postStatus: "succeeded", rejectPost: false,
    items: [receipt()] as ReturnType<typeof receipt>[], bodies: [] as Record<string, unknown>[] };
  const fetcher = vi.fn<typeof fetch>(async (url, init) => {
    const path = String(url);
    const body = JSON.parse(String(init?.body ?? "{}"));
    if (state.deniedPath && path.endsWith(state.deniedPath)) return Response.json({ detail: { message: "当前范围已撤权" } }, { status: state.denialStatus });
    if (path.endsWith("/matrix-ai-options")) return Response.json(options);
    if (path.endsWith("/matrix-ai-context")) return Response.json(preparation);
    if (path.endsWith("/matrix-ai-runs")) {
      state.bodies.push(body);
      if (state.failPost) { state.failPost = false; throw new TypeError("response lost"); }
      if (state.rejectPost) return Response.json({ detail: { message: "资料已变化，请重新核对" } }, { status: 409 });
      state.posted = true; const saved = receipt(body.request_id, state.postStatus); state.items = [saved]; return Response.json(saved);
    }
    if (path.endsWith("/matrix-ai-history")) {
      if (state.posted && state.failHistory) throw new TypeError("history unreachable");
      return Response.json({ can_request: true, rollout: "live", items: state.items });
    }
    return Response.json({});
  });
  vi.stubGlobal("fetch", fetcher);
  const view = render(withPreparation ? <ProductMatrixPreparation base="spaces/s" recordId="record"/> : <ProductMatrixRuns base="spaces/s" recordId="record" prepared={preparation}/>);
  return { state, fetcher, view };
}
async function readPreparation() {
  fireEvent.click(screen.getByRole("button", { name: "选择 / 刷新路线图资料" }));
  fireEvent.click(await screen.findByRole("checkbox", { name: /^P · 私有选项产品/ }));
  fireEvent.click(screen.getByRole("button", { name: "核对本次分析资料" }));
  await screen.findByText("私有准备依据");
}
async function readRun() {
  fireEvent.click(screen.getByText("矩阵分析与本人运行历史"));
  fireEvent.click(await screen.findByRole("button", { name: "查看分析与原请求" }));
  await screen.findByText("私有运行依据");
}

it.each([401, 403])("clears preparation and mounted private history after %i context denial", async status => {
  const { state } = setup(true); await readPreparation(); await readRun();
  state.deniedPath = "/matrix-ai-context"; state.denialStatus = status;
  fireEvent.click(screen.getByRole("button", { name: "核对本次分析资料" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("当前范围已撤权");
  expect(screen.queryByText("私有准备依据")).not.toBeInTheDocument();
  expect(screen.queryByRole("checkbox", { name: /^P · 私有选项产品/ })).not.toBeInTheDocument();
  expect(screen.queryByText("私有运行依据")).not.toBeInTheDocument();
});

it("clears parent source fields when private history access is denied", async () => {
  const { state } = setup(true); await readPreparation(); await readRun();
  state.deniedPath = "/matrix-ai-history";
  fireEvent.click(screen.getByRole("button", { name: "刷新本人原运行与回执" }));
  await screen.findByRole("alert");
  expect(screen.queryByText("私有准备依据")).not.toBeInTheDocument();
  expect(screen.queryByText("私有运行依据")).not.toBeInTheDocument();
});

it("retries only the original matrix request after response loss and source changes", async () => {
  const { state, view } = setup(); await readRun(); state.failPost = true;
  fireEvent.change(screen.getByLabelText("本次重点要求"), { target: { value: "原本重点" } });
  fireEvent.click(screen.getByRole("button", { name: "生成矩阵分析" }));
  fireEvent.click(screen.getByRole("button", { name: "生成矩阵分析" }));
  const retry = await screen.findByRole("button", { name: "重试原矩阵请求" });
  expect(state.bodies).toHaveLength(1);
  expect(screen.getByLabelText("本次重点要求")).toBeDisabled();
  view.rerender(<ProductMatrixRuns base="spaces/s" recordId="record" prepared={{ digest: "b".repeat(64), selection: { record_id: "record", roadmap_ids: [] } }}/>);
  expect(screen.getByRole("button", { name: "生成矩阵分析" })).toBeDisabled();
  fireEvent.click(retry);
  await waitFor(() => expect(screen.queryByRole("button", { name: "重试原矩阵请求" })).not.toBeInTheDocument());
  expect(state.bodies).toHaveLength(2);
  expect(state.bodies[1]).toEqual(state.bodies[0]);
  expect(state.bodies[1]).toMatchObject({ expected_digest: preparation.digest, user_instruction: "原本重点", selection: preparation.selection });
});

it("keeps a confirmed matrix receipt when only its history refresh fails", async () => {
  const { state } = setup(); await readRun(); state.failHistory = true;
  fireEvent.click(screen.getByRole("button", { name: "生成矩阵分析" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("矩阵分析已保存，历史暂未刷新");
  expect(screen.queryByRole("button", { name: "重试原矩阵请求" })).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("run");
  expect(state.bodies).toHaveLength(1);
});

it("clears both source panels on roadmap options denial and allows a fresh authorized reload", async () => {
  const { state } = setup(true); await readPreparation(); await readRun();
  state.deniedPath = "/matrix-ai-options";
  fireEvent.click(screen.getByRole("button", { name: "选择 / 刷新路线图资料" }));
  await screen.findByRole("alert");
  expect(screen.queryByText("私有运行依据")).not.toBeInTheDocument();
  expect(screen.queryByText("私有准备依据")).not.toBeInTheDocument();
  state.deniedPath = "";
  fireEvent.click(screen.getByRole("button", { name: "选择 / 刷新路线图资料" }));
  expect(await screen.findByRole("checkbox", { name: /^P · 私有选项产品/ })).not.toBeChecked();
  expect(screen.queryByText("私有运行依据")).not.toBeInTheDocument();
  expect(screen.queryByText("私有准备依据")).not.toBeInTheDocument();
});

it.each(["/matrix-ai-cancel", "/matrix-ai-progress"])("clears both source panels when %s denies access", async path => {
  const { state } = setup(true); state.items = [receipt("running-request", "running")];
  await readPreparation(); await readRun(); state.deniedPath = path;
  fireEvent.click(screen.getByRole("button", { name: path.endsWith("cancel") ? "停止原运行" : "合成查询运行进度" }));
  await screen.findByRole("alert");
  expect(screen.queryByText("私有运行依据")).not.toBeInTheDocument();
  expect(screen.queryByText("私有准备依据")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "生成矩阵分析" })).not.toBeInTheDocument();
});

it("clears a standalone pending request and instruction after explicit run access denial", async () => {
  const { state } = setup(); await readRun(); state.failPost = true;
  fireEvent.change(screen.getByLabelText("本次重点要求"), { target: { value: "私有草稿" } });
  fireEvent.click(screen.getByRole("button", { name: "生成矩阵分析" }));
  await screen.findByRole("button", { name: "重试原矩阵请求" });
  state.deniedPath = "/matrix-ai-history";
  fireEvent.click(screen.getByRole("button", { name: "刷新本人原运行与回执" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("当前范围已撤权");
  expect(screen.queryByRole("button", { name: "重试原矩阵请求" })).not.toBeInTheDocument();
  expect(screen.queryByText("私有运行依据")).not.toBeInTheDocument();
  state.deniedPath = "";
  fireEvent.click(screen.getByRole("button", { name: "刷新本人原运行与回执" }));
  expect(await screen.findByLabelText("本次重点要求")).toHaveValue("");
});

it("recovers a terminal original receipt by refreshing without another generation POST", async () => {
  const { state } = setup(); await readRun(); state.failPost = true;
  fireEvent.click(screen.getByRole("button", { name: "生成矩阵分析" }));
  await screen.findByRole("button", { name: "重试原矩阵请求" });
  state.items = [receipt(String(state.bodies[0].request_id))];
  fireEvent.click(screen.getByRole("button", { name: "刷新本人原运行与回执" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "重试原矩阵请求" })).not.toBeInTheDocument());
  await screen.findByText("私有运行依据");
  expect(screen.getByRole("button", { name: "生成矩阵分析" })).toBeEnabled();
  expect(state.bodies).toHaveLength(1);
});

it("keeps a confirmed running request pending until its terminal receipt is read", async () => {
  const { state } = setup(); await readRun(); state.postStatus = "running";
  fireEvent.click(screen.getByRole("button", { name: "生成矩阵分析" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "重试原矩阵请求" })).toBeEnabled());
  expect(screen.getByRole("button", { name: "生成矩阵分析" })).toBeDisabled();
  state.items = [receipt(String(state.bodies[0].request_id))];
  fireEvent.click(screen.getByRole("button", { name: "刷新本人原运行与回执" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "重试原矩阵请求" })).not.toBeInTheDocument());
  expect(state.bodies).toHaveLength(1);
});

it("releases a rejected request only after the server explicitly rejects its source version", async () => {
  const { state } = setup(); await readRun(); state.rejectPost = true;
  fireEvent.click(screen.getByRole("button", { name: "生成矩阵分析" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("资料已变化，请重新核对");
  expect(screen.queryByRole("button", { name: "重试原矩阵请求" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "生成矩阵分析" })).toBeEnabled();
  expect(state.bodies).toHaveLength(1);
});

it.each(["preparation", "runs"])("clears old %s fields immediately on scope changes", async kind => {
  const { view } = setup(kind === "preparation");
  if (kind === "preparation") await readPreparation(); else await readRun();
  view.rerender(kind === "preparation" ? <ProductMatrixPreparation base="spaces/other" recordId="other"/> : <ProductMatrixRuns base="spaces/other" recordId="other" prepared={null}/>);
  expect(screen.queryByText("私有准备依据")).not.toBeInTheDocument();
  expect(screen.queryByText("私有运行依据")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "生成矩阵分析" })).not.toBeInTheDocument();
});

it("ignores a late context response after the market space changes", async () => {
  const { fetcher, view } = setup(true);
  fireEvent.click(screen.getByRole("button", { name: "选择 / 刷新路线图资料" }));
  await screen.findByRole("checkbox", { name: /^P · 私有选项产品/ });
  let resolve!: (value: Response) => void;
  fetcher.mockImplementationOnce(() => new Promise<Response>(done => { resolve = done; }));
  fireEvent.click(screen.getByRole("button", { name: "核对本次分析资料" }));
  view.rerender(<ProductMatrixPreparation base="spaces/other" recordId="other"/>);
  resolve(Response.json(preparation));
  await waitFor(() => expect(screen.getByRole("button", { name: "选择 / 刷新路线图资料" })).toBeEnabled());
  expect(screen.queryByText("私有准备依据")).not.toBeInTheDocument();
});

it("does not follow an old generation receipt with reads after changing scopes", async () => {
  const { fetcher, view } = setup(); await readRun();
  let resolve!: (value: Response) => void;
  fetcher.mockImplementationOnce(() => new Promise<Response>(done => { resolve = done; }));
  fireEvent.click(screen.getByRole("button", { name: "生成矩阵分析" }));
  const count = fetcher.mock.calls.length;
  view.rerender(<ProductMatrixRuns base="spaces/other" recordId="other" prepared={null}/>);
  resolve(Response.json(receipt()));
  await new Promise(done => setTimeout(done, 20));
  expect(fetcher).toHaveBeenCalledTimes(count);
  expect(screen.queryByText("私有运行依据")).not.toBeInTheDocument();
});

it("does not repopulate private fields from a late history response after progress denial", async () => {
  const { fetcher, state } = setup(); await readRun();
  let resolve!: (value: Response) => void;
  fetcher.mockImplementationOnce(() => new Promise<Response>(done => { resolve = done; }));
  fireEvent.click(screen.getByRole("button", { name: "刷新本人原运行与回执" }));
  state.deniedPath = "/matrix-ai-progress";
  fireEvent.click(screen.getByRole("button", { name: "合成查询运行进度" }));
  await screen.findByRole("alert");
  resolve(Response.json({ can_request: true, rollout: "live", items: [receipt()] }));
  await waitFor(() => expect(screen.getByRole("button", { name: "刷新本人原运行与回执" })).toBeEnabled());
  expect(screen.queryByText("私有运行依据")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "生成矩阵分析" })).not.toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([, init]) => JSON.parse(String(init?.body ?? "{}")).run_id === "run" && String(init?.body).includes("before_id") === false)).toHaveLength(2);
});
