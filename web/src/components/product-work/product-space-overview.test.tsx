import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ProductSpaceOverview } from "./product-space-overview";
import { ProductRequestError, request, type ProductCatalog, type Workspace } from "./product-work-api";
import { ProductWorkScopeContext, useProductWorkScope } from "./product-work-scope";
import { navigateProductWork } from "./product-work-navigation";

const workspace = { space: { id: "space" }, research: [], work_items: [
  { id: "mine", title: "待我接收的成果", expected_output: "研究结论", state: "submitted", acceptance_required: true, receiver_user_id: "me", product_line_id: "line", evidence: [] },
  { id: "other", title: "其他人的接收事项", expected_output: "证据", state: "submitted", acceptance_required: true, receiver_user_id: "other", product_line_id: "line", evidence: [] },
  { id: "shared", title: "共同研究工作", expected_output: "证据", state: "ready", owner_user_id: "me", product_line_id: null, evidence: [] },
], members: [], current_user_id: "me", can_contribute: true, can_manage: false } as unknown as Workspace;
const catalog = { nodes: [{ id: "line", name: "主题一", level: "line" }], line_access: { line: { can_contribute: true } } } as unknown as ProductCatalog;
const candidate = { id: "finding", run_id: "run", title: "研究计划草案", summary: "待核对的访谈计划", status: "pending_review", capability: "research_planning", product_line_id: "line", created_at: "2026-10-01T00:00:00Z" };
const props = { base: "spaces/space", workspace, catalog, evidence: [], scope: "line", onAuthorityLost: vi.fn(), onPendingChange: vi.fn() };
beforeEach(() => { Element.prototype.scrollIntoView = vi.fn(); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("loads the scoped queue, links actual receiver work, and opens a candidate without generation or application", async () => {
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async input => String(input).endsWith("product-work-attention") ? Response.json({ candidates: [candidate], runs: [], limited: false, unavailable: false }) : Response.json({ finding: null }));
  vi.stubGlobal("fetch", fetcher); render(<ProductSpaceOverview {...props}/>);
  await screen.findByText("待核对的访谈计划");
  expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual({ all_lines: false, product_line_id: "line" });
  expect(screen.getByRole("link", { name: "核对并接收成果" })).toHaveAttribute("href", "/product-work?space=space&tab=research&line=line#work-mine");
  expect(screen.queryByText("共同研究工作")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "核对 / 修订候选" }));
  await screen.findByText(/本次没有可办理的研究候选/);
  expect(screen.getByLabelText("审阅所选候选")).toHaveFocus();
  expect(fetcher.mock.calls.map(([path]) => String(path))).toEqual(["/api/product-work/spaces/space/product-work-attention", "/api/product-work/my-work", "/api/product-work/spaces/space/research-ai-finding"]);
});

it("clears private queue details on access loss", async () => {
  const denied = vi.fn(); let allowed = true;
  vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockImplementation(async () => allowed ? Response.json({ candidates: [candidate], runs: [], limited: false, unavailable: false }) : Response.json({ detail: { message: "权限已撤回" } }, { status: 403 })));
  render(<ProductSpaceOverview {...props} onAuthorityLost={denied}/>); await screen.findByText(candidate.summary);
  allowed = false; fireEvent.focus(window);
  await waitFor(() => expect(denied).toHaveBeenCalledWith("权限已撤回"));
  expect(screen.queryByText(candidate.summary)).not.toBeInTheDocument();
});

it("announces confirmed writes, never POST reads or failed writes", async () => {
  const changed = vi.fn(); window.addEventListener("pdos:product-work-changed", changed);
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => Response.json({})); vi.stubGlobal("fetch", fetcher);
  await request("spaces/space/product-work-attention", "POST", {});
  await request("spaces/space/research-ai-finding", "POST", {});
  expect(changed).not.toHaveBeenCalled();
  fetcher.mockImplementation(async () => Response.json({}, { status: 409 }));
  await expect(request("spaces/space/research-ai-apply", "POST", {})).rejects.toBeInstanceOf(ProductRequestError);
  expect(changed).not.toHaveBeenCalled();
  fetcher.mockImplementation(async () => Response.json({})); await request("spaces/space/research-ai-apply", "POST", {});
  expect(changed).toHaveBeenCalledTimes(1);
  expect(changed.mock.calls[0][0].detail).toEqual({ base: "spaces/space" });
  window.removeEventListener("pdos:product-work-changed", changed);
});

it("keeps shared scope and clears stale run targets across professional views", () => {
  window.history.replaceState(null, "", "/product-work?space=space&line=&tab=research&run=old&history=1#research-old");
  navigateProductWork({ tab: "experiments" });
  expect(window.location.search).toBe("?space=space&line=&tab=experiments"); expect(window.location.hash).toBe("");
  function ScopedView() { const { scope, setScope } = useProductWorkScope(); return <button onClick={() => setScope("line")}>{scope}</button>; }
  const setScope = vi.fn(); render(<ProductWorkScopeContext.Provider value={{ scope: "", setScope }}><ScopedView/></ProductWorkScopeContext.Provider>);
  fireEvent.click(screen.getByRole("button")); expect(setScope).toHaveBeenCalledWith("line");
});
