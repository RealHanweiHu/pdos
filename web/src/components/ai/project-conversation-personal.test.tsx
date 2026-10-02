import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProjectConversation } from "./project-conversation";

vi.mock("@/components/workspace-api", async importOriginal => ({ ...await importOriginal<object>(), requestIdentity: async () => ({ user: { id: "user", role: "engineer" } }) }));
vi.mock("./conversation-files", async importOriginal => ({ ...await importOriginal<object>(), ConversationFiles: () => <p>附件</p> }));
const projectId = "10000000-0000-4000-8000-000000000001";
const calls: string[] = [];
function mockConversations(privateHistory = true) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    calls.push(url);
    const entries = [
      { id: "shared", visibility: "project", updated_at: "2026-09-30T00:00:00Z", archived_at: null },
      ...(privateHistory ? [{ id: "private", visibility: "private", updated_at: "2026-09-29T00:00:00Z", archived_at: null }] : []),
    ];
    if (url.includes("?project_id=")) return Response.json({ items: entries });
    const id = url.split("/").at(-1);
    return Response.json({ conversation: { id, project_id: projectId, meeting_id: null, created_by_user_id: "user", visibility: id === "shared" ? "project" : "private", context_version: 1, archived_at: null }, items: [] });
  }));
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); calls.length = 0; });
describe("个人 Agent 会话可见范围", () => {
  it("does not silently load a newer shared conversation into the personal agent", async () => {
    mockConversations();
    const ready = vi.fn();
    render(<ProjectConversation projectId={projectId} presentation="assistant" defaultOpen onConversationReady={ready}/>);
    await waitFor(() => expect(ready).toHaveBeenCalledWith("private"));
    expect(calls).not.toContain("/api/conversations/shared");
    expect(screen.getByText("个人对话 · 仅你可见")).toBeVisible();
  });
  it("leaves personal history empty if only shared sessions exist", async () => {
    mockConversations(false);
    render(<ProjectConversation projectId={projectId} presentation="assistant" defaultOpen/>);
    await waitFor(() => expect(screen.getByLabelText("会话消息")).toBeEnabled());
    expect(calls).not.toContain("/api/conversations/shared");
    expect(screen.queryByRole("combobox", { name: "选择本人会话" })).not.toBeInTheDocument();
  });
  it("clearly labels an explicitly opened shared conversation instead of relabeling it as private", async () => {
    mockConversations();
    render(<ProjectConversation projectId={projectId} presentation="assistant" defaultOpen initialConversationId="shared"/>);
    await waitFor(() => expect(calls).toContain("/api/conversations/shared"));
    expect(await screen.findByText(/项目成员可见：本会话/)).toBeVisible();
    expect(screen.queryByText("个人对话 · 仅你可见")).not.toBeInTheDocument();
  });
});
