import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ProductWorkspace } from "./product-workspace";

vi.mock("next/navigation", async () => {
  const { useSyncExternalStore } = await import("react");
  const subscribe = (fn: () => void) => { window.addEventListener("popstate", fn); return () => window.removeEventListener("popstate", fn); };
  return { useRouter: () => ({ replace: vi.fn() }), useSearchParams: () => new URLSearchParams(useSyncExternalStore(subscribe, () => window.location.search)) };
});
vi.mock("@/components/workspace-api", () => ({ requestIdentity: async () => ({ user: { role: "product_manager" }, tenant: {} }) }));
vi.mock("@/components/workspace-shell", () => ({ WorkspaceShell: ({ children }: { children: ReactNode }) => <main>{children}</main> }));
vi.mock("./work-responsibility", () => ({ WorkResponsibility: () => null, WorkResponsibilityLanding: () => null }));
vi.mock("./retirement-feedback", () => ({ RetirementFeedback: () => null }));
vi.mock("./product-matrix", () => ({ ProductMatrix: () => null }));
vi.mock("./product-roadmap", () => ({ ProductRoadmap: () => null }));
vi.mock("./product-source-files", () => ({ ProductSourceFiles: () => null }));
vi.mock("./product-ai-preparation", () => ({ ProductAiPreparation: () => null }));
const ref = { tenant_id: "tenant", kind: "evidence_snapshot", ref_id: "snapshot", as_of: "2026-09-29T00:00:00Z", digest: "a".repeat(64) };
const source = { id: "snapshot", name: "合成外部版本原件", url: null, captured_at: ref.as_of, taint: "untrusted", is_stale: false, superseded: false, has_conflict: false, reference: ref };
const space = { id: "one", code: "ONE", title: "产品矩阵空间", lifecycle: "active", version: 1, payload_digest: "b".repeat(64), owner_user_id: "owner", user_groups: [], regions: [], use_scenarios: [], research_questions: [] };
const levels = ["line", "family", "platform", "series", "model"];
const nodes = levels.map((level, index) => ({ id: level, product_line_id: "line", parent_id: index ? levels[index - 1] : null, code: level.toUpperCase(), name: level === "model" ? "合成私有型号" : `${level}产品`, level, lifecycle: "developing", version: 1, payload_digest: "c".repeat(64), owner_user_id: "owner", regions: [], channels: [] }));
const catalog = { nodes, members: [{ product_line_id: "line", user_id: "owner", access: "manager", display_name: "成员" }], line_access: { line: { can_manage: true, can_contribute: true } }, can_create_line: true };
const workspace = { space, current_user_id: "owner", members: [{ id: "owner", display_name: "成员", access: "manager" }], available_members: [], can_manage: true, can_contribute: true, can_collect: false, research: [], work_items: [] };
const projection = { product: { id: "model", version: 1, code: "MODEL", name: "合成私有型号", level: "model", lifecycle: "developing" }, current_definition: { id: "definition", version: 3, revision: 1, digest: "d".repeat(64), release_id: "release" }, context_digest: "e".repeat(64), items: [] };
let fetcher: ReturnType<typeof vi.fn<typeof fetch>>;
let writeStatus: number;
beforeEach(() => {
  writeStatus = 503;
  window.history.replaceState(null, "", "/product-work?space=one&tab=matrix");
  fetcher = vi.fn<typeof fetch>().mockImplementation(async (input, init) => {
    const path = String(input);
    if (path.endsWith("/spaces")) return Response.json({ items: [space], can_create: false });
    if (path.endsWith("/evidence")) return Response.json({ items: [source] });
    if (path.endsWith("/products")) return Response.json(catalog);
    if (path.endsWith("/spaces/one")) return Response.json(workspace);
    if (path.endsWith("/products/model/master-references")) return init?.method === "POST" && writeStatus !== 200 ? Response.json({ detail: { message: writeStatus === 503 ? "登记回执暂未取得" : "产品引用权限已撤回" } }, { status: writeStatus }) : Response.json(projection);
    throw new Error(`Unexpected request ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it.each([200, 403])("holds actual product-tree, workspace and directory navigation until original master-reference retry returns %s", async status => {
  render(<ProductWorkspace/>);
  fireEvent.click(await screen.findByRole("button", { name: "新登记交接引用" }));
  fireEvent.change(screen.getByLabelText("系统标识"), { target: { value: "SYNTHETIC_ERP" } });
  fireEvent.change(screen.getByLabelText("外部对象标识"), { target: { value: "MATERIAL-1" } });
  fireEvent.change(screen.getByLabelText("外部修订"), { target: { value: "R1" } });
  fireEvent.change(screen.getByLabelText("外部来源时点"), { target: { value: "2026-09-29T01:00" } });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.change(screen.getByLabelText("登记原因"), { target: { value: "合成授权原件对应关系" } });
  fireEvent.submit(screen.getByRole("button", { name: "保存交接引用" }).closest("form")!);
  const retry = await screen.findByRole("button", { name: "按原请求重试交接登记" });
  expect(retry).not.toBeDisabled();
  for (const tab of screen.getAllByRole("tab")) expect(tab).toBeDisabled();
  expect(screen.getByRole("button", { name: "市场空间" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "刷新工作与来源" })).toBeDisabled();
  for (const button of screen.getAllByRole("button", { name: "编辑" })) expect(button).toBeDisabled();
  expect(screen.getByRole("button", { name: "新建产品线" })).toBeDisabled();
  const writes = () => fetcher.mock.calls.filter(([input, init]) => String(input).endsWith("/master-references") && init?.method === "POST");
  expect(writes()).toHaveLength(1);
  writeStatus = status;
  fireEvent.click(retry);
  await waitFor(() => expect(writes()).toHaveLength(2));
  expect(JSON.parse(String(writes()[1][1]?.body))).toEqual(JSON.parse(String(writes()[0][1]?.body)));
  if (status === 200) {
    await waitFor(() => expect(screen.getByRole("button", { name: "市场空间" })).not.toBeDisabled());
    expect(screen.getByRole("button", { name: "刷新工作与来源" })).not.toBeDisabled();
    expect(screen.queryByLabelText("登记原因")).not.toBeInTheDocument();
  } else {
    await screen.findByRole("button", { name: "重试" });
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.queryByText("合成私有型号", { exact: false })).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("MATERIAL-1")).not.toBeInTheDocument();
    expect(screen.queryByText("合成外部版本原件", { exact: false })).not.toBeInTheDocument();
  }
});
