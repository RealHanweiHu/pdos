import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ConversationFindingGroup } from "./conversation-finding-group";
import type { AiFinding } from "./ai-types";

const finding = (id: string, status: AiFinding["status"] = "accepted"): AiFinding => ({ id, title: `候选 ${id}`, status, project_id: "project", run_id: "run", model_invocation_id: "model", agent_key: "project_intelligence", finding_type: "risk_suggestion", origin_key: id, summary: "共同材料的独立候选", proposed_payload: { title: id }, accepted_payload: status === "accepted" || status === "applied" ? { title: id } : null, evidence_event_ids: [], evidence: [], confidence_basis_points: 8000, preflight_version: "v1", reviewed_by_user_id: "reviewer", reviewed_at: "2026-09-28T00:00:00Z", review_comment: null, applied_by_user_id: status === "applied" ? "reviewer" : null, applied_at: status === "applied" ? "2026-09-28T01:00:00Z" : null, applied_entity_type: status === "applied" ? "risk" : null, applied_entity_id: status === "applied" ? `actual-${id}` : null, created_at: "2026-09-28T00:00:00Z", updated_at: "2026-09-28T01:00:00Z" });
const open = () => fireEvent.click(screen.getByText(/本条消息的 .* 项候选与办理回执/));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("retains partial success, deduplicates and retries only failed reads, then independently applies remaining work", async () => {
  let attempts = 0;
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url, init) => {
    if (String(url).endsWith("/a")) return Response.json(finding("a", "applied"));
    if (String(url).endsWith("/b") && ++attempts === 1) return Response.json({ detail: { message: "来源暂不可用" } }, { status: 503 });
    if (String(url).endsWith("/b")) return Response.json(finding("b"));
    if (String(url).endsWith("/b/apply") && init?.method === "POST") return Response.json({ finding: finding("b", "applied") });
    throw new Error(`Unexpected ${url}`);
  }); vi.stubGlobal("fetch", fetcher);
  render(<ConversationFindingGroup findingIds={["a", "b", "a"]}/>); expect(fetcher).not.toHaveBeenCalled(); open();
  await screen.findByText("待办理 0 · 已应用 1 · 已拒绝／归档／被替代 0 · 状态未确认 1"); expect(fetcher.mock.calls).toHaveLength(2);
  fireEvent.click(screen.getByRole("button", { name: "重试未读到的回执" }));
  await screen.findByText("待办理 1 · 已应用 1 · 已拒绝／归档／被替代 0 · 状态未确认 0");
  expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith("/a"))).toHaveLength(1);
  const summary = screen.getByText("候选 b", { selector: "summary" }); fireEvent.click(summary); const card = within(summary.closest("details")!);
  fireEvent.click(card.getByRole("button", { name: "核对应用内容" })); fireEvent.click(card.getByRole("button", { name: "确认独立应用" }));
  await screen.findByText("待办理 0 · 已应用 2 · 已拒绝／归档／被替代 0 · 状态未确认 0");
  expect(card.getByRole("link", { name: "查看实际业务记录与后续办理" })).toHaveAttribute("href", "/projects?project=project&tab=work-items&entity_id=actual-b");
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST").map(([url]) => url)).toEqual(["/api/ai/findings/b/apply"]);
});
it("keeps replaced and terminal history out of the pending count", async () => {
  vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockImplementation(async url => Response.json(String(url).endsWith("/old") ? { ...finding("old"), superseded_by: "new" } : finding("rejected", "rejected"))));
  render(<ConversationFindingGroup findingIds={["old", "rejected"]}/>); open();
  await screen.findByText("待办理 0 · 已应用 0 · 已拒绝／归档／被替代 2 · 状态未确认 0");
  const old = screen.getByText("候选 old", { selector: "summary" }).closest("details")!;
  expect(within(old).queryByRole("button", { name: "核对应用内容", hidden: true })).not.toBeInTheDocument();
  expect(within(old).getByRole("link", { name: "查看最新建议", hidden: true })).toHaveAttribute("href", "/ai-review?finding=new");
});
it("ignores late responses from a previous message", async () => {
  let resolve!: (value: Response) => void;
  vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockImplementationOnce(() => new Promise(done => { resolve = done; })).mockResolvedValueOnce(Response.json(finding("new"))));
  const view = render(<ConversationFindingGroup findingIds={["old"]}/>); open(); await waitFor(() => expect(resolve).toBeDefined());
  view.rerender(<ConversationFindingGroup findingIds={["new"]}/>); open(); await screen.findByText("待办理 1 · 已应用 0 · 已拒绝／归档／被替代 0 · 状态未确认 0");
  await act(async () => resolve(Response.json(finding("old")))); expect(screen.queryByText("候选 old", { selector: "summary" })).not.toBeInTheDocument();
});
it("recovers a lost apply response without resubmitting", async () => {
  let reads = 0;
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (_url, init) => {
    if (init?.method === "POST") throw new Error("写入响应丢失");
    return Response.json(finding("a", ++reads === 1 ? "accepted" : "applied"));
  }); vi.stubGlobal("fetch", fetcher);
  render(<ConversationFindingGroup findingIds={["a"]}/>); open();
  await screen.findByText("待办理 1 · 已应用 0 · 已拒绝／归档／被替代 0 · 状态未确认 0");
  fireEvent.click(screen.getByText("候选 a", { selector: "summary" }));
  fireEvent.click(screen.getByRole("button", { name: "核对应用内容" })); fireEvent.click(screen.getByRole("button", { name: "确认独立应用" }));
  await screen.findByText("待办理 0 · 已应用 0 · 已拒绝／归档／被替代 0 · 状态未确认 1");
  expect(screen.getByRole("button", { name: "核对应用内容" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "刷新当前裁决" }));
  await screen.findByText("待办理 0 · 已应用 1 · 已拒绝／归档／被替代 0 · 状态未确认 0");
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
});
