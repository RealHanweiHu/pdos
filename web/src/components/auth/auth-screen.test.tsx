import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthScreen } from "./auth-screen";

const { routerPush } = vi.hoisted(() => ({ routerPush: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
}));

function jsonResponse(body: object, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("AuthScreen", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("shows the one-time workspace setup form when the server is empty", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ needs_setup: true }));

    render(<AuthScreen />);

    expect(
      await screen.findByRole("heading", { name: "初始化 PDOS 工作区" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("租户标识")).toHaveAttribute(
      "autocomplete",
      "organization",
    );
    expect(screen.getByLabelText("管理员密码")).toHaveAttribute(
      "autocomplete",
      "new-password",
    );
    expect(
      screen.getByRole("button", { name: "创建工作区并登录" }),
    ).toBeEnabled();
  });

  it("creates an HttpOnly-backed session and resolves the current identity", async () => {
    const user = userEvent.setup();
    const onAuthenticated = vi.fn();
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ needs_setup: false }))
      .mockResolvedValueOnce(
        jsonResponse({ authenticated: true, expires_in: 1800 }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          tenant: { id: "tenant-1", slug: "beepump", name: "Beehive" },
          user: {
            id: "user-1",
            tenant_id: "tenant-1",
            username: "owner",
            display_name: "Owner",
            role: "owner",
            email: null,
            is_active: true,
          },
        }),
      );

    render(<AuthScreen onAuthenticated={onAuthenticated} />);

    await screen.findByRole("heading", { name: "登录 PDOS" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await user.type(screen.getByLabelText("租户标识"), "beepump");
    await user.type(screen.getByLabelText("用户名"), "owner");
    await user.type(screen.getByLabelText("密码"), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: "登录" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledOnce());
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/session/login",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          tenant_slug: "beepump",
          username: "owner",
          password: "correct horse battery staple",
        }),
      }),
    );
    expect(screen.getByLabelText("密码")).toHaveValue("");
    expect(screen.getByRole("status")).toHaveTextContent("身份验证成功");
  });

  it("submits the one-time setup fields through the same-origin session boundary", async () => {
    const user = userEvent.setup();
    const onAuthenticated = vi.fn();
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ needs_setup: true }))
      .mockResolvedValueOnce(jsonResponse({ authenticated: true }))
      .mockResolvedValueOnce(
        jsonResponse({
          tenant: { id: "tenant-1", slug: "beepump", name: "Beehive" },
          user: {
            id: "user-1",
            tenant_id: "tenant-1",
            username: "owner",
            display_name: "Owner",
            role: "owner",
            email: null,
            is_active: true,
          },
        }),
      );

    render(<AuthScreen onAuthenticated={onAuthenticated} />);

    await screen.findByRole("heading", { name: "初始化 PDOS 工作区" });
    await user.type(screen.getByLabelText("租户标识"), "beepump");
    await user.type(screen.getByLabelText("组织名称"), "Beehive Technology");
    await user.type(screen.getByLabelText("管理员用户名"), "owner");
    await user.type(screen.getByLabelText("显示名称"), "Initial Owner");
    await user.type(
      screen.getByLabelText("管理员密码"),
      "correct horse battery staple",
    );
    await user.click(
      screen.getByRole("button", { name: "创建工作区并登录" }),
    );

    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledOnce());
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/session/setup",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          tenant_slug: "beepump",
          tenant_name: "Beehive Technology",
          username: "owner",
          display_name: "Initial Owner",
          password: "correct horse battery staple",
        }),
      }),
    );
    expect(screen.getByLabelText("管理员密码")).toHaveValue("");
  });

  it("announces a stable error and clears the password after rejected credentials", async () => {
    const user = userEvent.setup();
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ needs_setup: false }))
      .mockResolvedValueOnce(
        jsonResponse(
          { detail: { code: "INVALID_CREDENTIALS", message: "Invalid" } },
          401,
        ),
      );

    render(<AuthScreen />);

    await screen.findByRole("heading", { name: "登录 PDOS" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await user.type(screen.getByLabelText("租户标识"), "beepump");
    await user.type(screen.getByLabelText("用户名"), "owner");
    await user.type(screen.getByLabelText("密码"), "wrong password");
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "租户、账号或密码不正确",
    );
    expect(screen.getByLabelText("密码")).toHaveValue("");
    await waitFor(() => expect(screen.getByLabelText("密码")).toHaveFocus());
  });

  it("starts DingTalk OAuth only after a tenant is supplied", async () => {
    const user = userEvent.setup();
    const assign = vi.fn();
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ needs_setup: false }))
      .mockResolvedValueOnce(
        jsonResponse({
          authorization_url:
            "https://login.dingtalk.com/oauth2/auth?client_id=client&state=opaque",
          expires_in: 300,
        }),
      );
    vi.stubGlobal("location", { assign });

    render(<AuthScreen />);

    await screen.findByRole("heading", { name: "登录 PDOS" });
    const dingTalk = screen.getByRole("button", { name: "使用钉钉登录" });
    expect(dingTalk).toBeDisabled();
    await user.type(screen.getByLabelText("租户标识"), "beepump");
    expect(dingTalk).toBeEnabled();
    await user.click(dingTalk);

    await waitFor(() => expect(assign).toHaveBeenCalledOnce());
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/session/dingtalk/start",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ tenant_slug: "beepump", return_path: "/" }),
      }),
    );
    expect(assign).toHaveBeenCalledWith(
      "https://login.dingtalk.com/oauth2/auth?client_id=client&state=opaque",
    );
  });
});
