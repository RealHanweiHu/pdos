import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { StrategyWorkspace } from "./strategies";
import { DefinitionWorkspace, type Definition } from "./definitions";
import type { Workspace, ProductCatalog } from "./product-work-api";

vi.mock("./work-responsibility", () => ({ WorkResponsibility: () => null }));
vi.mock("./definition-cost-feedback", () => ({ DefinitionCostFeedback: () => null }));
vi.mock("./definition-result-feedback", () => ({ DefinitionResultFeedback: () => null }));
vi.mock("./definition-exports", () => ({ DefinitionExports: () => null }));
vi.mock("./definition-intake", () => ({ DefinitionIntake: () => null }));
vi.mock("./experiment-feedback", () => ({ ExperimentFeedbackInbox: () => null }));
vi.mock("./product-result-followups", () => ({ ProductResultFollowupInbox: () => null }));
vi.mock("@/components/cases/initial-plans", () => ({ InitialPlans: () => null }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); window.location.hash = ""; });

type Kind = "strategy" | "definition";
const recordId = "55555555-5555-4555-8555-555555555555";
const ref = { tenant_id: "tenant", kind: "evidence", ref_id: "source", as_of: "2026-09-30T00:00:00Z", digest: "a".repeat(64) };
const fact = { text: "合成私有事实", fact_kind: "hypothesis" as const, sources: [], approval: null, derivation_version: null };
const workspace = { space: { id: "s" }, current_user_id: "owner", can_contribute: true, members: [{ id: "owner", display_name: "合成人", access: "manager" }], work_items: [] } as unknown as Workspace;
const catalog = { nodes: [{ id: "line", product_line_id: "line", level: "line", name: "合成线" }, { id: "product", product_line_id: "line", level: "model", code: "P", name: "合成产品", lifecycle: "developing" }], line_access: { line: { can_contribute: true } }, members: [{ product_line_id: "line", user_id: "owner", access: "manager" }] } as unknown as ProductCatalog;
const evidence = [{ id: "source", name: "合成来源", reference: ref }] as unknown as Parameters<typeof StrategyWorkspace>[0]["evidence"];
const definitionContent: Definition["content"] = { title: "私有定义名称", owner_user_id: "owner", target_users: ["合成用户"], scenarios: ["合成场景"], included_features: [], excluded_features: [], region_constraints: [], target_cost: { ...fact, sources: [ref] }, price_position: fact, launch_window: fact, service_requirements: [], success_criteria: [fact], items: [], reviewers: {}, change_reason: "私有定义依据" };
const names = { strategy: { refresh: "刷新策略与方案", title: "私有策略名称 · 修订 1", editor: "编辑草稿", formTitle: "策略名称", history: "查看办理历史", read: "查看九区 Canvas" }, definition: { refresh: "刷新定义与策略", title: "私有定义名称 · 修订 1", editor: "编辑定义草稿", formTitle: "定义名称", history: "查看办理与发布历史", read: "阅读结构化规格书（0 条）" } };
function record(kind: Kind): Record<string, unknown> {
  const common = { id: recordId, owner_user_id: "owner", created_by_user_id: "owner", revision_number: 1, version: 1, payload_digest: "d".repeat(64), state: "draft", can_publish: true, has_successor: false, source_warnings: [], publication_blockers: [], approval: null, product_line_id: "line" };
  return kind === "strategy" ? { ...common, title: "私有策略名称", opportunity_id: "opp", opportunity_title: "合成机会", opportunity_series_id: "opp", opportunity_version: 1, decision_reason: "私有策略依据", canvas: Object.fromEntries(["vision", "segment_jtbd", "relative_cost", "value_proposition", "trade_offs", "success_metrics", "growth_path", "capabilities_partners", "defensibility"].map(key => [key, { ...fact, sources: key === "vision" ? [ref] : [] }])), solutions: [], route_comparisons: [], professional_constraints: [], unknowns: [], selected_solution_id: null, cost_summary: [] }
    : { ...common, product_id: "product", product_name: "合成产品", product_code: "P", strategy_id: "strategy", strategy_title: "合成发布策略", strategy_revision: 1, content: definitionContent, review_round: 0, review_digest: null, reviews: [], review_blockers: [], current_release: null, is_current: false, stable_item_keys: [], diff: { strategy_changed: false, sections: [], items: [] } };
}
function setup(kind: Kind, initialState: "draft" | "review" | "professional_review" = "draft", onResponsibilityLock?: (locked: boolean) => void) {
  const state = { deniedPath: "", deniedStatus: 403, record: record(kind), failList: false, actions: [] as Record<string, unknown>[] };
  if (initialState !== "draft") state.record = { ...state.record, state: "in_review", review_digest: "c".repeat(64), review_round: 1 };
  if (initialState === "professional_review") state.record.content = { ...definitionContent, reviewers: { id: "owner" } };
  const fetcher = vi.fn<typeof fetch>(async (url, init) => {
    const path = String(url);
    if (state.deniedPath && path.endsWith(state.deniedPath)) return Response.json({ detail: { message: "当前办理范围已撤权" } }, { status: state.deniedStatus });
    if (path.endsWith("/actions") || path.endsWith("/changes") || path.endsWith("/reviews")) { state.actions.push(JSON.parse(String(init?.body))); return Response.json({ id: recordId }); }
    if (state.failList && path.endsWith(kind === "strategy" ? "/strategies" : "/definitions")) throw new TypeError("list unreachable");
    if (path.endsWith("/strategies")) return Response.json({ items: kind === "strategy" ? [state.record] : [{ id: "strategy", title: "私有发布策略选项", revision_number: 1, state: "published", product_line_id: "line" }] });
    if (path.endsWith("/opportunities")) return Response.json({ items: [{ id: "opp", title: "私有机会选项", version: 1, state: "exploring", is_latest: true, solutions: [], product_line_id: "line", series_id: "opp" }] });
    if (path.endsWith("/definitions")) return Response.json({ items: [state.record] });
    if (path.endsWith("/history")) return Response.json(kind === "strategy" ? { items: [{ action: "product_strategy.edited", actor_user_id: "owner", timestamp: "2026-09-30T00:00:00Z", context: { reason: "私有办理历史" }, after_snapshot: null }] } : { items: [{ action: "product_definition.edited", actor_user_id: "owner", timestamp: "2026-09-30T00:00:00Z", context: { reason: "私有办理历史" }, after_snapshot: null }], releases: [] });
    if (path.endsWith("/content")) return Response.json({ snapshot_id: "source", content: "私有证据原文", content_digest: "a".repeat(64), byte_size: 100, stored_at: "2026-09-30T00:00:00Z", taint: "untrusted", content_language: "zh" });
    return Response.json({});
  });
  vi.stubGlobal("fetch", fetcher);
  const props = { base: "spaces/s", workspace, catalog, evidence, onResponsibilityLock };
  const view = render(kind === "strategy" ? <StrategyWorkspace {...props}/> : <DefinitionWorkspace {...props}/>);
  return { state, fetcher, view, props };
}

it.each([200, 412])("locks definition writes while a parent merge is uncertain, then releases them after its %s receipt", async status => {
  const lock = vi.fn();
  const { state, fetcher } = setup("definition", "draft", lock);
  state.record.base_definition_id = "parent";
  await screen.findByText(names.definition.title);
  fireEvent.click(screen.getByRole("button", { name: names.definition.refresh }));
  await screen.findByRole("button", { name: "比较父产品最新发布版" });
  fetcher.mockResolvedValueOnce(Response.json({ target_definition_id: "parent-2", target_release_id: "release", target_revision: 2, comparison_digest: "b".repeat(64), changes: [{ path: "field/scenarios", base: [], local: [], incoming: ["父版合成场景"], conflict: false }] }));
  fireEvent.click(screen.getByRole("button", { name: "比较父产品最新发布版" }));
  await screen.findByText("父版合成场景");
  fireEvent.click(screen.getByRole("checkbox", { name: "使用场景" }));
  fireEvent.change(screen.getByLabelText("接受变更的原因"), { target: { value: "合成显式选择" } });
  fetcher.mockRejectedValueOnce(new TypeError("response lost"));
  fireEvent.click(screen.getByRole("button", { name: "接受所选父版变更" }));
  await screen.findByRole("button", { name: "按原请求重试核对父版变更" });
  expect(screen.getByRole("button", { name: names.definition.editor })).toBeDisabled();
  expect(screen.getByRole("button", { name: "新建产品定义" })).toBeDisabled();
  expect(screen.getByRole("button", { name: names.definition.refresh })).toBeDisabled();
  expect(screen.getByLabelText("办理意见 / 原因")).toBeDisabled();
  expect(screen.getByRole("combobox", { name: "产品线" })).toBeDisabled();
  expect(lock).toHaveBeenLastCalledWith(true);
  fetcher.mockResolvedValueOnce(Response.json(status === 200 ? state.record : { detail: { message: "版本已有变化" } }, { status }));
  fireEvent.click(screen.getByRole("button", { name: "按原请求重试核对父版变更" }));
  await waitFor(() => expect(screen.getByRole("button", { name: names.definition.editor })).toBeEnabled());
  expect(lock).toHaveBeenLastCalledWith(false);
  expect(screen.queryByRole("button", { name: "按原请求重试核对父版变更" })).not.toBeInTheDocument();
  const calls = fetcher.mock.calls.filter(([path]) => String(path).endsWith("parent-merge"));
  expect(calls).toHaveLength(2); expect(calls[1][1]?.body).toEqual(calls[0][1]?.body);
});
async function readOriginal(kind: Kind) {
  await screen.findByText(names[kind].title);
  fireEvent.click(screen.getByText(names[kind].read));
  fireEvent.click(screen.getAllByRole("button", { name: "查看正文" })[0]);
  await screen.findByText("私有证据原文");
  fireEvent.click(screen.getByRole("button", { name: names[kind].history }));
  await screen.findByText("私有办理历史");
}

it.each(["strategy", "definition"] as const)("clears all private %s text, history, source content and draft on list denial", async kind => {
  const { state } = setup(kind); await readOriginal(kind);
  fireEvent.click(screen.getByRole("button", { name: names[kind].editor }));
  fireEvent.change(screen.getByLabelText(names[kind].formTitle), { target: { value: "未保存私有草稿" } });
  state.deniedPath = kind === "strategy" ? "/strategies" : "/definitions";
  fireEvent.click(screen.getByRole("button", { name: names[kind].refresh }));
  expect(await screen.findByRole("alert")).toHaveTextContent("当前办理范围已撤权");
  expect(screen.queryByText(names[kind].title)).not.toBeInTheDocument();
  expect(screen.queryByText("私有办理历史")).not.toBeInTheDocument();
  expect(screen.queryByText("私有证据原文")).not.toBeInTheDocument();
  expect(screen.queryByDisplayValue("未保存私有草稿")).not.toBeInTheDocument();
});

it.each(["strategy", "definition"] as const)("clears %s data on an explicit evidence-content denial", async kind => {
  const { state } = setup(kind); await readOriginal(kind);
  state.deniedPath = "/content"; state.deniedStatus = 401;
  fireEvent.click(screen.getAllByRole("button", { name: "查看正文" })[0]);
  await screen.findByRole("alert");
  expect(screen.queryByText(names[kind].title)).not.toBeInTheDocument();
  expect(screen.queryByText("私有办理历史")).not.toBeInTheDocument();
  expect(screen.queryByText("私有证据原文")).not.toBeInTheDocument();
});

it.each(["strategy", "definition"] as const)("clears %s data when reading its private handling history is denied", async kind => {
  const { state } = setup(kind); await screen.findByText(names[kind].title);
  state.deniedPath = "/history";
  fireEvent.click(screen.getByRole("button", { name: names[kind].history }));
  await screen.findByRole("alert");
  expect(screen.queryByText(names[kind].title)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: names[kind].editor })).not.toBeInTheDocument();
});

it.each(["strategy", "definition"] as const)("clears %s data when saving its draft is denied", async kind => {
  const { state } = setup(kind); await readOriginal(kind);
  fireEvent.click(screen.getByRole("button", { name: names[kind].editor }));
  fireEvent.change(screen.getByLabelText(names[kind].formTitle), { target: { value: "私有编辑内容" } });
  state.deniedPath = "/changes";
  fireEvent.submit(screen.getByLabelText(names[kind].formTitle).closest("form")!);
  await screen.findByRole("alert");
  expect(screen.queryByText(names[kind].title)).not.toBeInTheDocument();
  expect(screen.queryByText("私有证据原文")).not.toBeInTheDocument();
  expect(screen.queryByDisplayValue("私有编辑内容")).not.toBeInTheDocument();
});

it.each(["strategy", "definition"] as const)("clears %s data on publication denial without retrying the named action", async kind => {
  const { state, fetcher } = setup(kind, "review");
  await screen.findByText(names[kind].title);
  fireEvent.change(screen.getByLabelText(kind === "strategy" ? "送审 / 发布 / 退回意见" : "办理意见 / 原因"), { target: { value: "合成具名发布意见" } });
  state.deniedPath = "/actions";
  fireEvent.click(screen.getByRole("button", { name: kind === "strategy" ? "批准并发布此版策略" : "确认协审版本并发布" }));
  await screen.findByRole("alert");
  expect(screen.queryByText(names[kind].title)).not.toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith("/actions"))).toHaveLength(1);
});

it("clears the definition and reviewer draft after named professional review access is denied", async () => {
  const { state } = setup("definition", "professional_review");
  await screen.findByText("提交 ID 工业设计 协审");
  fireEvent.change(screen.getByLabelText("意见"), { target: { value: "approved" } });
  fireEvent.change(screen.getByLabelText("审阅范围、依据与意见"), { target: { value: "私有协审内容" } });
  state.deniedPath = "/reviews";
  fireEvent.submit(screen.getByRole("button", { name: "记录本专业意见" }).closest("form")!);
  await screen.findByRole("alert");
  expect(screen.queryByText(names.definition.title)).not.toBeInTheDocument();
  expect(screen.queryByDisplayValue("私有协审内容")).not.toBeInTheDocument();
});

it.each(["strategy", "definition"] as const)("restores %s only after an authorized read, with old drafts cleared", async kind => {
  const { state } = setup(kind); await readOriginal(kind);
  fireEvent.click(screen.getByRole("button", { name: names[kind].editor }));
  fireEvent.change(screen.getByLabelText(names[kind].formTitle), { target: { value: "旧私有草稿" } });
  state.deniedPath = kind === "strategy" ? "/strategies" : "/definitions";
  fireEvent.click(screen.getByRole("button", { name: names[kind].refresh }));
  await screen.findByRole("alert");
  expect(screen.getByRole("combobox", { name: kind === "strategy" ? "工作归属" : "产品线" })).toBeDisabled();
  expect(screen.queryByRole("option", { name: "合成线" })).not.toBeInTheDocument();
  state.deniedPath = "";
  fireEvent.click(screen.getByRole("button", { name: names[kind].refresh }));
  await screen.findByText(names[kind].title);
  expect(screen.queryByText("私有证据原文")).not.toBeInTheDocument();
  expect(screen.queryByText("私有办理历史")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: names[kind].editor }));
  expect(screen.getByLabelText(names[kind].formTitle)).not.toHaveValue("旧私有草稿");
});

it.each(["strategy", "definition"] as const)("ignores a late %s list response after evidence permission is revoked", async kind => {
  const { state, fetcher } = setup(kind); await readOriginal(kind);
  let resolve!: (value: Response) => void;
  fetcher.mockImplementationOnce(() => new Promise<Response>(done => { resolve = done; }));
  fireEvent.click(screen.getByRole("button", { name: names[kind].refresh }));
  state.deniedPath = "/content";
  fireEvent.click(screen.getAllByRole("button", { name: "查看正文" })[0]);
  await screen.findByRole("alert");
  resolve(Response.json({ items: [state.record] }));
  await waitFor(() => expect(screen.getByRole("button", { name: names[kind].refresh })).toBeEnabled());
  expect(screen.queryByText(names[kind].title)).not.toBeInTheDocument();
  expect(screen.queryByText("私有证据原文")).not.toBeInTheDocument();
});

it.each(["strategy", "definition"] as const)("ignores a late %s source body after its list denies access", async kind => {
  const { state, fetcher } = setup(kind); await readOriginal(kind);
  let resolve!: (value: Response) => void;
  fetcher.mockImplementationOnce(() => new Promise<Response>(done => { resolve = done; }));
  fireEvent.click(screen.getAllByRole("button", { name: "查看正文" })[0]);
  state.deniedPath = kind === "strategy" ? "/strategies" : "/definitions";
  fireEvent.click(screen.getByRole("button", { name: names[kind].refresh }));
  await screen.findByRole("alert");
  resolve(Response.json({ content: "私有迟到原文" }));
  await new Promise(done => setTimeout(done, 20));
  expect(screen.queryByText("私有迟到原文")).not.toBeInTheDocument();
});

it.each(["strategy", "definition"] as const)("does not refresh %s after an old draft-save response arrives following revocation", async kind => {
  const { state, fetcher } = setup(kind); await readOriginal(kind);
  fireEvent.click(screen.getByRole("button", { name: names[kind].editor }));
  let resolve!: (value: Response) => void;
  fetcher.mockImplementationOnce(() => new Promise<Response>(done => { resolve = done; }));
  fireEvent.submit(screen.getByLabelText(names[kind].formTitle).closest("form")!);
  state.deniedPath = "/content";
  fireEvent.click(screen.getAllByRole("button", { name: "查看正文" })[0]);
  await screen.findByRole("alert");
  const count = fetcher.mock.calls.length;
  resolve(Response.json({ id: recordId }));
  await new Promise(done => setTimeout(done, 20));
  expect(fetcher).toHaveBeenCalledTimes(count);
  expect(screen.queryByText(names[kind].title)).not.toBeInTheDocument();
});

it.each(["strategy", "definition"] as const)("clears %s immediately when the acting user changes", async kind => {
  const { view, props, fetcher } = setup(kind); await readOriginal(kind);
  fetcher.mockImplementation(async () => Response.json({ items: [] }));
  const other = { ...props, workspace: { ...workspace, current_user_id: "other" } };
  view.rerender(kind === "strategy" ? <StrategyWorkspace {...other}/> : <DefinitionWorkspace {...other}/>);
  expect(screen.queryByText(names[kind].title)).not.toBeInTheDocument();
  expect(screen.queryByText("私有证据原文")).not.toBeInTheDocument();
  expect(screen.queryByText("私有办理历史")).not.toBeInTheDocument();
});

it.each(["strategy", "definition"] as const)("keeps readable %s content on a generic refresh failure", async kind => {
  const { state } = setup(kind); await readOriginal(kind); state.failList = true;
  fireEvent.click(screen.getByRole("button", { name: names[kind].refresh }));
  expect(await screen.findByRole("alert")).toHaveTextContent("list unreachable");
  expect(screen.getByText(names[kind].title)).toBeInTheDocument();
  expect(screen.getByText("私有证据原文")).toBeInTheDocument();
  expect(screen.getByText("私有办理历史")).toBeInTheDocument();
});

it("preserves named publication version and source digest when only the post-save list is unavailable", async () => {
  const { state } = setup("definition", "review");
  await screen.findByText(names.definition.title);
  fireEvent.change(screen.getByLabelText("办理意见 / 原因"), { target: { value: "具名人工发布" } });
  state.failList = true;
  fireEvent.click(screen.getByRole("button", { name: "确认协审版本并发布" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("定义已保存，列表刷新失败");
  expect(state.actions).toHaveLength(1);
  expect(state.actions[0]).toMatchObject({ action: "publish", expected_version: 1, payload_digest: "d".repeat(64), reviewed_source_digest: "c".repeat(64), reason: "具名人工发布" });
  expect(state.actions[0].idempotency_key).toEqual(expect.any(String));
});

it("clears the owning definition when its actual inheritance panel loses parent source access", async () => {
  const { state } = setup("definition"); await readOriginal("definition");
  state.record = { ...state.record, base_definition_id: "original-parent" };
  fireEvent.click(screen.getByRole("button", { name: names.definition.refresh }));
  await screen.findByRole("button", { name: "比较父产品最新发布版" });
  state.deniedPath = "/parent-comparison";
  fireEvent.click(screen.getByRole("button", { name: "比较父产品最新发布版" }));
  await screen.findByRole("alert");
  expect(screen.queryByText(names.definition.title)).not.toBeInTheDocument();
  expect(screen.queryByText("私有证据原文")).not.toBeInTheDocument();
  expect(screen.queryByText("私有办理历史")).not.toBeInTheDocument();
});
