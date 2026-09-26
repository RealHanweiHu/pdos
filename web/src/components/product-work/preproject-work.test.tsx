import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { PreProjectWork } from "./preproject-work";
const empty = { research: [], work_items: [], experiments: [], strategies: [], definitions: [] };
const row = (id: string) => ({ id, market_space_id: "space-1", product_line_id: "line-1", space_title: "充气场景", product_line_name: "便携泵", state: "draft", question: `研究 ${id}` });
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("exposes remaining work, reads the chosen collection and preserves typed source links", async () => {
  const fetcher = vi.fn(async (input: RequestInfo | URL) => response(String(input).includes("collection=research")
    ? { ...empty, research: [row("3")], pages: { research: { total: 3, next_offset: null } } }
    : { ...empty, research: [row("1"), row("2")], definitions: [{ ...row("definition-1"), question: undefined, title: "边界定义", state: "in_review" }], pages: Object.fromEntries(Object.keys(empty).map(key => [key, { total: key === "research" ? 3 : key === "definitions" ? 1 : 0, next_offset: key === "research" ? 2 : null }])) }));
  vi.stubGlobal("fetch", fetcher);
  render(<PreProjectWork />);
  expect(await screen.findByText(/共 4 项，已读取 3 项/)).toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText("立项前工作类型"), "research");
  await userEvent.click(screen.getByRole("button", { name: "继续读取研究任务" }));
  expect(await screen.findByRole("link", { name: /研究 3/ })).toHaveAttribute("href", "/product-work?space=space-1&line=line-1#research-3");
  expect(fetcher).toHaveBeenLastCalledWith("/api/product-work/my-work?collection=research&offset=2&limit=100", expect.any(Object));
  expect(screen.queryByRole("button", { name: "继续读取研究任务" })).not.toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText("立项前工作类型"), "definitions");
  expect(screen.getByRole("link", { name: /边界定义/ })).toHaveAttribute("href", "/product-work?space=space-1&line=line-1&tab=definitions#definition-definition-1");
  expect(screen.getByRole("link", { name: /边界定义/ })).toHaveTextContent("待协审 / 发布");
});
it("keeps failed reads distinct from an empty queue and retries independently", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(response({ detail: { message: "权限已变化" } }, 403)).mockResolvedValueOnce(response(empty));
  vi.stubGlobal("fetch", fetcher);
  render(<><button>办理项目任务</button><PreProjectWork /></>);
  expect(await screen.findByRole("alert")).toHaveTextContent("权限已变化");
  expect(screen.queryByText(/当前没有分派给你/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "办理项目任务" })).toBeEnabled();
  await userEvent.click(screen.getByRole("button", { name: "刷新立项前工作" }));
  expect(await screen.findByText(/当前没有分派给你或等待你接收/)).toBeInTheDocument();
});
