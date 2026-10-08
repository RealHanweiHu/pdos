import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ProductWorkspace } from "./product-workspace";

vi.mock("next/navigation", async () => {
  const { useSyncExternalStore } = await import("react");
  const replace = vi.fn();
  const subscribe = (listener: () => void) => { window.addEventListener("popstate", listener); return () => window.removeEventListener("popstate", listener); };
  return { usePathname: () => useSyncExternalStore(subscribe, () => window.location.pathname), useRouter: () => ({ replace }), useSearchParams: () => new URLSearchParams(useSyncExternalStore(subscribe, () => window.location.search)) };
});
const { currentRole, paiPending } = vi.hoisted(() => ({ currentRole: { value: "product_manager" }, paiPending: { value: false } }));
vi.mock("@/components/ai/xiaopai-provider", () => ({ useXiaopaiPending: () => paiPending.value }));
vi.mock("@/components/workspace-api", async importOriginal => ({ ...await importOriginal<typeof import("@/components/workspace-api")>(), requestIdentity: async () => ({ user: { role: currentRole.value }, tenant: {} }) }));
vi.mock("@/components/workspace-shell", () => ({ WorkspaceShell: ({ children }: { children: React.ReactNode }) => <main>{children}</main> }));
vi.mock("./work-responsibility", () => ({ WorkResponsibility: () => null, WorkResponsibilityLanding: () => null }));
vi.mock("./product-catalog", () => ({ ProductTree: () => null, SpaceSettings: () => null }));
vi.mock("./product-source-files", () => ({ ProductSourceFiles: ({ disabled, onPendingChange }: { disabled: boolean; onPendingChange: (pending: boolean) => void }) => <div><button onClick={() => onPendingChange(true)}>模拟原件未决</button><button disabled={disabled} onClick={() => onPendingChange(false)}>模拟原确认恢复</button></div> }));
vi.mock("./research-collection", () => ({ ResearchCollection: () => null }));
vi.mock("./competitors", () => ({ CompetitorWorkspace: () => <p>竞品业务区</p> }));
vi.mock("./product-ai-runs", () => ({ ProductAiRuns: () => null }));
vi.mock("./product-shadow-evaluation", () => ({ ProductShadowEvaluation: () => <p>管理员影子评测入口</p> }));
const spaces = [{ id: "one", code: "ONE", title: "空间一", user_groups: [], regions: [], use_scenarios: [] }, { id: "two", code: "TWO", title: "空间二", user_groups: [], regions: [], use_scenarios: [] }].map(space => ({ ...space, category_line_id:"line-one", lifecycle: "draft", research_questions: [] }));
const memoryStorage = new Map<string, string>();
const catalog = { nodes: [{ id: "line-one", name: "品类一", level: "line" }], members: [], line_access: {}, can_create_line: false };
let fetcher: ReturnType<typeof vi.fn<typeof fetch>>;
beforeEach(() => {
  memoryStorage.clear();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => memoryStorage.get(key) ?? null,
    setItem: (key: string, value: string) => void memoryStorage.set(key, value),
  });
  currentRole.value = "product_manager";
  paiPending.value = false;
  window.history.replaceState(null, "", "/product-work?space=one&tab=research&line=line-one");
  const push = window.history.pushState.bind(window.history);
  vi.spyOn(window.history, "pushState").mockImplementation((...args) => { push(...args); window.dispatchEvent(new PopStateEvent("popstate")); });
  fetcher = vi.fn<typeof fetch>().mockImplementation(async input => {
    const path = String(input);
    if (path.endsWith("/categories")) return Response.json({ items: spaces, can_create: false });
    if (path.endsWith("/products")) return Response.json(catalog);
    if (path.endsWith("/shared")) return Response.json({parameters:[],knowledge:[],competitors:[],segments:[],test_template:{items:[]}});
    if (path.endsWith("/evidence")) return Response.json({ items: [] });
    if (path.endsWith("/product-ai-options")) return Response.json({ items: [], next_offset: null });
    return Response.json({ space: spaces[path.endsWith("/two") ? 1 : 0], research: [], work_items: [], members: [], available_members: [], can_manage: false, can_contribute: false });
  });
  vi.stubGlobal("fetch", fetcher);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("keeps tab, back/forward and remount aligned with the URL and carries the line into AI source requests", async () => {
  const view = render(<ProductWorkspace/>);
  await screen.findByRole("heading", {name:"空间一"});
  expect(screen.queryByLabelText("工作归属")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "竞品" }));
  expect(await screen.findByText("竞品业务区")).toBeInTheDocument();
  expect(new URLSearchParams(location.search).get("tab")).toBe("competitors");
  fireEvent.click(screen.getByRole("button", { name: "资料核对与分析记录" }));
  expect(screen.getByLabelText("本次品类")).toHaveValue("line-one");
  fireEvent.click(screen.getByText("小Pai · 核对本次产品工作资料"));
  fireEvent.click(screen.getByRole("button", { name: "读取可用来源" }));
  await screen.findByText("此范围没有匹配资料，可调整查询或先登记来源。");
  const call = fetcher.mock.calls.find(([url]) => String(url).endsWith("/product-ai-options"))!;
  expect(JSON.parse(String(call[1]?.body)).product_line_id).toBe("line-one");
  await act(async () => window.history.back());
  await waitFor(() => expect(screen.getByRole("tab", { name: "研究" })).toHaveAttribute("aria-selected", "true"));
  await act(async () => window.history.forward());
  await waitFor(() => expect(screen.getByRole("tab", { name: "竞品" })).toHaveAttribute("aria-selected", "true"));
  view.unmount(); render(<ProductWorkspace/>);
  expect(await screen.findByText("竞品业务区")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "资料核对与分析记录" }));
  expect(screen.getByLabelText("本次品类")).toHaveValue("line-one");
});

it("updates shared line navigation and clears obsolete targets when selecting a space", async () => {
  window.history.replaceState(null, "", `${location.pathname}${location.search}&roadmap_product=old&record_id=old&run=old&responsibility_id=old&responsibility_kind=space#research-old`);
  render(<ProductWorkspace/>);
  await screen.findByRole("heading", {name:"空间一"});
  fireEvent.click(screen.getByRole("button", { name: "品类" }));
  const spaceLink = await screen.findByRole("link", { name: /空间二/ });
  expect(spaceLink).toHaveAttribute("href", "/product-work?category=two");
  act(() => window.history.pushState(null, "", spaceLink.getAttribute("href")));
  await screen.findByRole("heading", { name: "空间二" });
  expect(location.search).toBe("?category=two");
  expect(screen.getByRole("heading", { name: "品类资料" })).toBeInTheDocument();
});

it("does not silently broaden an inaccessible line or space", async () => {
  window.history.replaceState(null, "", "/product-work?space=one&line=missing");
  render(<ProductWorkspace/>);
  expect(await screen.findByRole("alert")).toHaveTextContent("品类不存在或当前无权访问");
  expect(screen.queryByText("小Pai · 核对本次产品工作资料")).not.toBeInTheDocument();
  act(() => window.history.pushState(null, "", "/product-work?space=missing"));
  expect(await screen.findByRole("alert")).toHaveTextContent("品类不存在或当前无权访问");
  expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
});

it("keeps the explicit all-work scope when opening and switching professional views", async () => {
  window.history.replaceState(null, "", "/product-work?space=one&tab=research&line=all");
  render(<ProductWorkspace/>);
  await screen.findByRole("heading", {name:"空间一"});
  expect(screen.queryByLabelText("工作归属")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "竞品" }));
  expect(await screen.findByText("竞品业务区")).toBeInTheDocument();
  expect(new URLSearchParams(location.search).get("line")).toBe("all");
});

it("restores the URL matrix record through the original read and clears it on tab navigation", async () => {
  const record = "f11423e8-84f0-4d9f-9654-10dd68bc2e33";
  window.history.replaceState(null, "", `/product-work?space=one&tab=matrix&line=line-one&record_id=${record}`);
  const previous = fetcher.getMockImplementation()!;
  fetcher.mockImplementation(async (...args) => {
    const path = String(args[0]);
    if (path.endsWith("/matrix-record-read")) return Response.json({ detail: { message: "当前原记录需要核对授权" } }, { status: 403 });
    if (path.endsWith("/product-matrix")) return Response.json({ items: [], total: 0, scope_counts: {}, facets: { regions: [], channels: [], scenarios: [] }, revision: "fixed", next_offset: null });
    return previous(...args);
  });
  render(<ProductWorkspace/>);
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => String(url).endsWith("/matrix-record-read"))).toBe(true));
  const call = fetcher.mock.calls.find(([url]) => String(url).endsWith("/matrix-record-read"))!;
  expect(JSON.parse(String(call[1]?.body))).toEqual({ record_id: record });
  expect(fetcher.mock.calls.some(([url]) => String(url).endsWith("/matrix-record-refresh"))).toBe(false);
  fireEvent.click(screen.getByRole("tab", { name: "研究" }));
  await waitFor(() => expect(new URLSearchParams(location.search).has("record_id")).toBe(false));
});

it("passes the research result URL to the authorized original lookup and clears it on navigation", async () => {
  window.history.replaceState(null, "", "/product-work?space=one&tab=research&line=line-one&run=original-run");
  const previous = fetcher.getMockImplementation()!;
  fetcher.mockImplementation(async (...args) => String(args[0]).endsWith("product-ai-run-read") ? Response.json({ items: [{ run_id: "original-run", selection: { capability: "research_planning", product_line_id: "line-one" } }] }) : previous(...args));
  render(<ProductWorkspace/>);
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => String(url).endsWith("product-ai-run-read"))).toBe(true));
  const lookup = fetcher.mock.calls.find(([url]) => String(url).endsWith("product-ai-run-read"))!;
  expect(JSON.parse(String(lookup[1]?.body))).toEqual({ run_id: "original-run" });
  expect(screen.getByText("小Pai · 核对本次产品工作资料").closest("details")).toHaveAttribute("open");
  expect(fetcher.mock.calls.some(([url]) => String(url).endsWith("product-ai-runs"))).toBe(false);
  fireEvent.click(screen.getByRole("tab", { name: "竞品" }));
  await screen.findByText("竞品业务区");
  expect(new URLSearchParams(location.search).has("run")).toBe(false);
});

it("opens the requested matrix run from the workspace URL against its original saved record", async () => {
  const record = "f11423e8-84f0-4d9f-9654-10dd68bc2e33";
  window.history.replaceState(null, "", `/product-work?space=one&tab=matrix&line=line-one&record_id=${record}&run=matrix-original`);
  const previous = fetcher.getMockImplementation()!;
  const result = { snapshot: { products: [], facts: [], segment: { title: "原市场" } }, product_summary: [], criteria: [], overlap: [], scope: "原范围", formula: "原规则", formula_version: "coverage.v1", input_digest: "input", result_digest: "result" };
  const run = { run_id: "matrix-original", request_id: "request", status: "succeeded", selection: { record_id: record, roadmap_ids: [] }, sources_current: true, created_at: "2026-09-30T00:00:00Z", assessment: { summary: [{ text: "父入口指定的原矩阵分析", nature: "observed", citations: [] }], products: [], criteria: [], positioning_hypotheses: [], platform_reuse_hypotheses: [], missing: [], coverage_limits: "原范围" }, frozen_sources: [] };
  fetcher.mockImplementation(async (...args) => {
    const path = String(args[0]);
    if (path.endsWith("matrix-record-read")) return Response.json({ id: record, product_line_id: "line-one", title: "原记录", version: 1, actor_name: "负责人", created_at: run.created_at, source_changes: [], current_source_warnings: [], result });
    if (path.endsWith("matrix-ai-history")) return Response.json({ items: [run], can_request: false, rollout: "shadow", next_before_id: null });
    if (path.endsWith("product-matrix")) return Response.json({ items: [], total: 0, scope_counts: {}, facets: { regions: [], channels: [], scenarios: [] }, revision: "fixed", next_offset: null });
    return previous(...args);
  });
  render(<ProductWorkspace/>);
  await screen.findByText(/父入口指定的原矩阵分析/);
  const lookup = fetcher.mock.calls.find(([url]) => String(url).endsWith("matrix-ai-history"))!;
  expect(JSON.parse(String(lookup[1]?.body))).toEqual({ record_id: record, run_id: "matrix-original" });
  expect(fetcher.mock.calls.some(([url]) => String(url).endsWith("matrix-ai-runs") || String(url).endsWith("matrix-record-refresh"))).toBe(false);
});

it.each(["owner", "admin"])("opens the source-scoped evaluation tab for %s", async role => {
  currentRole.value = role;
  window.history.replaceState(null, "", "/product-work?space=one&tab=evaluation");
  render(<ProductWorkspace/>);
  expect(await screen.findByText("管理员影子评测入口")).toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: "能力评测" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "品类设置" }));
  expect(await screen.findByRole("button", { name: "能力评测" })).toBeInTheDocument();
});

it("keeps administrator evaluation out of an employee's navigation and rejects its deep link", async () => {
  window.history.replaceState(null, "", "/product-work?space=one&tab=evaluation");
  render(<ProductWorkspace/>);
  expect(await screen.findByRole("alert")).toHaveTextContent("能力评测仅允许当前租户模型管理员办理");
  expect(screen.queryByRole("tab", { name: "能力评测" })).not.toBeInTheDocument();
  expect(screen.queryByText("管理员影子评测入口")).not.toBeInTheDocument();
});

it("opens the directory with shareable space links and persists the list/card preference", async () => {
  window.history.replaceState(null, "", "/product-work");
  const view = render(<ProductWorkspace/>);
  expect(await screen.findByRole("link", { name: /空间一/ })).toHaveAttribute("href", "/product-work?category=one");
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "列表视图" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: "卡片视图" }));
  expect(memoryStorage.get("pdos.productWork.view")).toBe("cards");
  expect(screen.getByRole("link", { name: /空间一/ })).toBeInTheDocument();
  view.unmount(); render(<ProductWorkspace/>);
  await screen.findByRole("link", { name: /空间一/ });
  expect(screen.getByRole("button", { name: "卡片视图" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: "列表视图" }));
  expect(memoryStorage.get("pdos.productWork.view")).toBe("list");
});

it("keeps the directory usable when browser storage is unavailable", async () => {
  window.history.replaceState(null, "", "/product-work");
  vi.stubGlobal("localStorage", {
    getItem: () => { throw new DOMException("Storage disabled", "SecurityError"); },
    setItem: () => { throw new DOMException("Storage disabled", "SecurityError"); },
  });
  render(<ProductWorkspace/>);
  expect(await screen.findByRole("link", { name: /空间一/ })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "卡片视图" }));
  expect(screen.getByRole("button", { name: "卡片视图" })).toHaveAttribute("aria-pressed", "true");
});


it("keeps the RFQ recovery available while locking tabs, scope, workspace refresh and directory navigation", async () => {
  render(<ProductWorkspace/>); await screen.findByRole("heading", {name:"空间一"});
  fireEvent.click(screen.getByRole("button", { name: "资料核对与分析记录" }));
  fireEvent.click(screen.getByText("资料与采集"));
  fireEvent.click(screen.getByRole("button", { name: "模拟原件未决" }));
  expect(screen.queryByLabelText("工作归属")).not.toBeInTheDocument();
  expect(screen.getByLabelText("本次品类")).toBeDisabled();
  expect(screen.getByRole("tab", { name: "竞品" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "刷新工作与来源" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "品类" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "模拟原确认恢复" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "模拟原确认恢复" }));
  expect(screen.queryByLabelText("工作归属")).not.toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "竞品" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "品类" })).toBeEnabled();
});


it("keeps the submitted Xiaopai scope fixed until the original request resolves", async () => {
  paiPending.value = true;
  const view = render(<ProductWorkspace/>);
  await screen.findByRole("heading", {name:"空间一"});
  expect(screen.queryByLabelText("工作归属")).not.toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "竞品" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "品类" })).toBeDisabled();
  const original = location.search;
  fireEvent.click(screen.getByRole("tab", { name: "竞品" }));
  fireEvent.click(screen.getByRole("button", { name: "品类" }));
  expect(location.search).toBe(original);
  paiPending.value = false;
  view.rerender(<ProductWorkspace/>);
  expect(screen.queryByLabelText("工作归属")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "竞品" }));
  expect(await screen.findByText("竞品业务区")).toBeInTheDocument();
  expect(new URLSearchParams(location.search).get("line")).toBe("line-one");
});

it.each(["list", "cards"])("removes a confirmed category from the %s directory and restores it from archived", async mode => {
  window.history.replaceState(null, "", "/product-work");
  memoryStorage.set("pdos.productWork.view", mode);
  let rows = spaces.map(space => ({ ...space, version: 1, payload_digest: "current", can_restore: space.id === "one" }));
  const previous = fetcher.getMockImplementation()!;
  fetcher.mockImplementation(async (...args) => {
    if (String(args[0]).endsWith("/categories")) return Response.json({ items: rows, can_create: false });
    if (String(args[0]).endsWith("/one/lifecycle")) {
      const body = JSON.parse(String(args[1]?.body));
      rows = rows.map(row => row.id === "one" ? { ...row, lifecycle: body.lifecycle, version: row.version + 1 } : row);
      return Response.json(rows[0]);
    }
    return previous(...args);
  });
  render(<ProductWorkspace/>);
  expect(await screen.findByRole("link", { name: /空间一/ })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "删除品类 空间二" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "删除品类 空间一" }));
  expect(fetcher.mock.calls.some(([url]) => String(url).endsWith("/lifecycle"))).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
  await waitFor(() => expect(screen.queryByRole("link", { name: /空间一/ })).not.toBeInTheDocument());
  expect(screen.getByRole("link", { name: /空间二/ })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "已归档" }));
  expect(await screen.findByRole("link", { name: /空间一/ })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /空间二/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "恢复品类 空间一" }));
  fireEvent.click(screen.getByRole("button", { name: "确认恢复" }));
  expect(await screen.findByText("暂无已归档品类。")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "返回品类列表" }));
  expect(await screen.findByRole("link", { name: /空间一/ })).toBeInTheDocument();
});

it("returns from a deleted category's detail to the default directory", async () => {
  const previous = fetcher.getMockImplementation()!;
  const managed = { ...spaces[0], version: 1, payload_digest: "current", can_restore: true };
  fetcher.mockImplementation(async (...args) => {
    if (String(args[0]).endsWith("/one/lifecycle")) return Response.json({ ...managed, lifecycle: "archived", version: 2 });
    if (String(args[0]).endsWith("/spaces/one")) return Response.json({ space: managed, research: [], work_items: [], members: [], available_members: [], can_manage: true, can_restore: true, can_contribute: false });
    return previous(...args);
  });
  render(<ProductWorkspace/>);
  await screen.findByRole("heading", { name: "空间一" });
  fireEvent.click(screen.getByText("更多操作"));
  fireEvent.click(screen.getByRole("button", { name: "删除品类 空间一" }));
  fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
  await waitFor(() => expect(location.search).toBe(""));
  expect(await screen.findByRole("heading", { name: "品类" })).toBeInTheDocument();
});

it("ignores a delayed directory refresh that predates confirmed removal", async () => {
  window.history.replaceState(null, "", "/product-work");
  const before = { ...spaces[0], version: 1, payload_digest: "current", can_restore: true };
  let current = before, reads = 0;
  let finishOldRead!: (response: Response) => void;
  const previous = fetcher.getMockImplementation()!;
  fetcher.mockImplementation(async (...args) => {
    if (String(args[0]).endsWith("/categories")) {
      reads += 1;
      if (reads === 2) return new Promise<Response>(resolve => { finishOldRead = resolve; });
      return Response.json({ items: [current], can_create: false });
    }
    if (String(args[0]).endsWith("/one/lifecycle")) {
      current = { ...before, lifecycle: "archived", version: 2 };
      return Response.json(current);
    }
    return previous(...args);
  });
  render(<ProductWorkspace/>);
  await screen.findByRole("link", { name: /空间一/ });
  fireEvent.click(screen.getByRole("button", { name: "刷新" }));
  fireEvent.click(screen.getByRole("button", { name: "删除品类 空间一" }));
  fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
  await waitFor(() => expect(screen.queryByRole("link", { name: /空间一/ })).not.toBeInTheDocument());
  await act(async () => finishOldRead(Response.json({ items: [before], can_create: false })));
  expect(screen.queryByRole("link", { name: /空间一/ })).not.toBeInTheDocument();
});
