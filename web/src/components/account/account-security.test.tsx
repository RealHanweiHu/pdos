import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { routerReplace } = vi.hoisted(() => ({ routerReplace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: routerReplace }),
}));

import { AccountSecurity } from "./account-security";

const identity = {
  tenant: { id: "tenant-1", slug: "beepump", name: "Beehive Technology" },
  user: {
    id: "user-1",
    tenant_id: "tenant-1",
    username: "owner",
    display_name: "Initial Owner",
    role: "owner",
    email: null,
    is_active: true,
  },
};

describe("AccountSecurity", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    fetchMock.mockReset();
    routerReplace.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("requires confirmation, changes the current user's password, and ends the session", async () => {
    const user = userEvent.setup();
    fetchMock
      .mockResolvedValueOnce(Response.json(identity))
      .mockResolvedValueOnce(Response.json({ changed: true, reauthentication_required: true }));

    render(<AccountSecurity />);
    expect(await screen.findByRole("heading", { name: "账户安全" })).toBeInTheDocument();

    await user.type(screen.getByLabelText("当前密码"), "correct horse battery staple");
    await user.type(screen.getByLabelText("新密码"), "rotated production passphrase");
    await user.type(screen.getByLabelText("确认新密码"), "different production passphrase");
    await user.click(screen.getByRole("button", { name: "修改密码" }));
    expect(await screen.findByText("两次输入的新密码不一致。" )).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await user.clear(screen.getByLabelText("确认新密码"));
    await user.type(screen.getByLabelText("确认新密码"), "rotated production passphrase");
    await user.click(screen.getByRole("button", { name: "修改密码" }));

    expect(await screen.findByRole("heading", { name: "密码已修改" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "使用新密码登录" })).toHaveAttribute("href", "/login");
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          current_password: "correct horse battery staple",
          new_password: "rotated production passphrase",
        }),
      }),
    );
  });

  it("explains an invalid current password without discarding the form", async () => {
    const user = userEvent.setup();
    fetchMock
      .mockResolvedValueOnce(Response.json(identity))
      .mockResolvedValueOnce(
        Response.json({ detail: { code: "INVALID_CURRENT_PASSWORD" } }, { status: 400 }),
      );
    render(<AccountSecurity />);
    await screen.findByRole("heading", { name: "账户安全" });
    await user.type(screen.getByLabelText("当前密码"), "wrong current password");
    await user.type(screen.getByLabelText("新密码"), "rotated production passphrase");
    await user.type(screen.getByLabelText("确认新密码"), "rotated production passphrase");
    await user.click(screen.getByRole("button", { name: "修改密码" }));

    expect(await screen.findByText("当前密码不正确，请重新输入。" )).toBeInTheDocument();
    expect(screen.getByLabelText("新密码")).toHaveValue("rotated production passphrase");
  });

  it("redirects an expired identity session", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 401 }));
    render(<AccountSecurity />);
    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith("/login"));
  });
});
