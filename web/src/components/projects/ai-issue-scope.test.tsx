import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AiIssueScope } from "./ai-issue-scope";
const base = "/api/projects/project/ai-issue-applications/scope";
function data(revision = 0, enabled = false, canManage = true) { return { scope: { revision, enabled, principal_id: enabled ? "PRIVATE_PRINCIPAL" : null }, can_manage_scope: canManage, notice: "此授权用于具名确认应用，不授予自动建单资格。" }; }
function open() { fireEvent.click(screen.getByText("项目问题 AI 范围授权")); }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
describe("project Issue AI scope", () => {
  it("loads lazily and exposes a view-only state without implying automatic execution", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json(data(3, true, false)));
    vi.stubGlobal("fetch", fetcher); render(<AiIssueScope projectId="project" />); expect(fetcher).not.toHaveBeenCalled(); open();
    expect(await screen.findByText("已登记项目范围授权 · 第 3 版")).toBeVisible(); expect(screen.getByText("当前账号仅可查看项目授权，不能更改。")).toBeVisible();
    expect(screen.queryByRole("button", { name: "停止本项目范围授权" })).not.toBeInTheDocument(); expect(screen.queryByText("PRIVATE_PRINCIPAL")).not.toBeInTheDocument();
    expect(fetcher.mock.calls[0][0]).toBe(base);
  });
  it("requires a reason, retries the same unknown command and reads the latest state after acknowledgement", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(data())).mockRejectedValueOnce(new Error("连接中断")).mockResolvedValueOnce(Response.json({ revision: 1, reused: true })).mockResolvedValueOnce(Response.json(data(2, false)));
    vi.stubGlobal("fetch", fetcher); render(<AiIssueScope projectId="project" />); open();
    const button = await screen.findByRole("button", { name: "登记本项目范围授权" }); expect(button).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { name: /项目授权原因/ }), { target: { value: "限定本项目具名核对问题建议" } }); fireEvent.click(button);
    const retry = await screen.findByRole("button", { name: "沿原请求核对项目授权" }); expect(screen.getByRole("textbox")).toBeDisabled(); expect(screen.getByRole("button", { name: "刷新项目授权" })).toBeDisabled(); fireEvent.click(retry);
    expect(await screen.findByText("项目范围尚未授权 · 第 2 版")).toBeVisible();
    expect(fetcher.mock.calls[1][1]?.body).toBe(fetcher.mock.calls[2][1]?.body);
    expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body))).toEqual({ request_id: expect.any(String), expected_revision: 0, enabled: true, reason: "限定本项目具名核对问题建议" });
    expect(fetcher.mock.calls[3][1]?.method).toBe("GET"); expect(screen.getByRole("textbox")).toHaveValue("");
  });
  it("stops the current grant with its actual revision and requires refreshing a known conflict", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(data(3, true))).mockResolvedValueOnce(Response.json({ detail: { code: "AI_ISSUE_SCOPE_CHANGED", message: "项目授权已有变化，请刷新核对" } }, { status: 409 })).mockResolvedValueOnce(Response.json(data(4, false)));
    vi.stubGlobal("fetch", fetcher); render(<AiIssueScope projectId="project" />); open();
    await screen.findByRole("button", { name: "停止本项目范围授权" }); fireEvent.change(screen.getByRole("textbox"), { target: { value: "停止后续本项目应用" } }); fireEvent.click(screen.getByRole("button", { name: "停止本项目范围授权" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("项目授权已有变化"); expect(screen.queryByRole("button", { name: "停止本项目范围授权" })).not.toBeInTheDocument();
    expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body))).toEqual({ request_id: expect.any(String), expected_revision: 3, enabled: false, reason: "停止后续本项目应用" });
    fireEvent.click(screen.getByRole("button", { name: "刷新项目授权" })); expect(await screen.findByText("项目范围尚未授权 · 第 4 版")).toBeVisible();
  });
});
