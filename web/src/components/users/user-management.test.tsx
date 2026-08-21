import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { routerReplace } = vi.hoisted(() => ({ routerReplace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: routerReplace }),
}));

import { UserManagement } from "./user-management";

const ownerIdentity = {
  tenant: { id: "tenant-1", slug: "beepump", name: "Beehive Technology" },
  user: {
    id: "user-owner",
    tenant_id: "tenant-1",
    username: "owner",
    display_name: "Initial Owner",
    role: "owner",
    email: null,
    is_active: true,
  },
};

const users = {
  items: [
    {
      id: "user-owner",
      tenant_id: "tenant-1",
      username: "owner",
      display_name: "Initial Owner",
      email: null,
      role: "owner",
      is_active: true,
      last_signed_in_at: "2026-08-20T10:00:00Z",
      created_at: "2026-08-11T10:00:00Z",
      updated_at: "2026-08-20T10:00:00Z",
    },
  ],
};

function response(body: object, status = 200) {
  return Promise.resolve(Response.json(body, { status }));
}

describe("UserManagement", () => {
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

  it("lets an Owner create a tenant account without retaining the temporary password", async () => {
    const user = userEvent.setup();
    const created = {
      ...users.items[0],
      id: "user-quality",
      username: "quality-lead",
      display_name: "Quality Lead",
      email: "quality@example.com",
      role: "quality",
      last_signed_in_at: null,
    };
    fetchMock
      .mockImplementationOnce(() => response(ownerIdentity))
      .mockImplementationOnce(() => response(users))
      .mockImplementationOnce(() => response(created, 201));

    render(<UserManagement />);

    expect(await screen.findByRole("heading", { name: "成员与角色" })).toBeInTheDocument();
    expect(screen.getByText("1 个账户")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Owner" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Admin" })).toBeInTheDocument();

    await user.type(screen.getByLabelText("用户名"), "quality-lead");
    await user.type(screen.getByLabelText("显示名称"), "Quality Lead");
    await user.type(screen.getByLabelText("邮箱（可选）"), "quality@example.com");
    await user.selectOptions(screen.getByLabelText("角色"), "quality");
    await user.type(screen.getByLabelText("临时密码"), "temporary passphrase 2026");
    await user.click(screen.getByRole("button", { name: "创建账户" }));

    expect(await screen.findByText("账户 quality-lead 已创建")).toBeInTheDocument();
    expect(screen.getByLabelText("临时密码")).toHaveValue("");
    expect(screen.getByText("2 个账户")).toBeInTheDocument();
    expect(fetchMock.mock.calls[2]?.[1]).toEqual(
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          username: "quality-lead",
          display_name: "Quality Lead",
          email: "quality@example.com",
          role: "quality",
          password: "temporary passphrase 2026",
        }),
      }),
    );
  });

  it("supports role, status, and password reset actions with explicit confirmation", async () => {
    const user = userEvent.setup();
    const engineer = {
      ...users.items[0],
      id: "user-engineer",
      username: "engineer-one",
      display_name: "Engineer One",
      role: "engineer",
      last_signed_in_at: null,
    };
    fetchMock
      .mockImplementationOnce(() => response(ownerIdentity))
      .mockImplementationOnce(() => response({ items: [...users.items, engineer] }))
      .mockImplementationOnce(() => response({ ...engineer, role: "project_manager" }))
      .mockImplementationOnce(() => response({ ...engineer, role: "project_manager", is_active: false }))
      .mockImplementationOnce(() => response({ ...engineer, role: "project_manager" }));

    render(<UserManagement />);
    const row = await screen.findByRole("row", { name: /engineer-one/i });
    await user.selectOptions(within(row).getByLabelText("engineer-one 的角色"), "project_manager");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));

    await user.click(within(row).getByRole("button", { name: "停用 engineer-one" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));

    await user.click(within(row).getByRole("button", { name: "重置 engineer-one 密码" }));
    const password = await screen.findByLabelText("engineer-one 的新密码");
    await user.type(password, "rotated production passphrase");
    await user.click(screen.getByRole("button", { name: "确认重置密码" }));

    expect(await screen.findByText("engineer-one 的密码已重置，旧会话已失效")).toBeInTheDocument();
    expect(password).toHaveValue("");
    expect(fetchMock.mock.calls[4]?.[1]).toEqual(
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ password: "rotated production passphrase" }),
      }),
    );
  });

  it("hides privileged role choices from Admins", async () => {
    fetchMock
      .mockImplementationOnce(() =>
        response({ ...ownerIdentity, user: { ...ownerIdentity.user, id: "user-admin", role: "admin" } }),
      )
      .mockImplementationOnce(() => response(users));

    render(<UserManagement />);

    expect(await screen.findByRole("heading", { name: "成员与角色" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Owner" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Admin" })).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Engineer" })).toBeInTheDocument();
  });

  it("shows a forbidden state without requesting accounts for non-admin roles", async () => {
    fetchMock.mockImplementationOnce(() =>
      response({ ...ownerIdentity, user: { ...ownerIdentity.user, role: "engineer" } }),
    );

    render(<UserManagement />);

    expect(await screen.findByRole("heading", { name: "仅管理员可访问" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("link", { name: "成员与角色" })).not.toBeInTheDocument();
  });

  it("redirects expired sessions and offers retry for service errors", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 401 }));
    render(<UserManagement />);
    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith("/login"));

    cleanup();
    fetchMock.mockReset();
    routerReplace.mockReset();
    fetchMock
      .mockImplementationOnce(() => response(ownerIdentity))
      .mockRejectedValueOnce(new Error("offline"));
    render(<UserManagement />);
    expect(await screen.findByRole("heading", { name: "无法读取成员账户" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
  });
});
