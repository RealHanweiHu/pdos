import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { routerReplace } = vi.hoisted(() => ({ routerReplace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: routerReplace }),
}));

import { ModelGovernance } from "./model-governance";

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

const governance = {
  eligible_models: [
    {
      provider: "minimax",
      model: "MiniMax-M2.7",
      protocol: "openai-compatible",
    },
  ],
  selection: {
    provider: "minimax",
    model: "MiniMax-M2.7",
    available: true,
  },
  budget: {
    daily_token_budget: 2000000,
    used_tokens_today: 250000,
    remaining_tokens_today: 1750000,
    exhausted: false,
  },
};

function response(body: object, status = 200) {
  return Promise.resolve(Response.json(body, { status }));
}

describe("ModelGovernance", () => {
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

  it("shows only qualified models and persists the tenant budget", async () => {
    const user = userEvent.setup();
    fetchMock
      .mockImplementationOnce(() => response(identity))
      .mockImplementationOnce(() => response(governance))
      .mockImplementationOnce(() =>
        response({
          ...governance,
          budget: { ...governance.budget, daily_token_budget: 3000000 },
        }),
      );

    render(<ModelGovernance />);

    expect(await screen.findByRole("heading", { name: "模型与预算" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "MiniMax · MiniMax-M2.7" })).toBeInTheDocument();
    expect(screen.getByText("1,750,000")).toBeInTheDocument();
    expect(screen.queryByText(/api[_ -]?key/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/base[_ -]?url/i)).not.toBeInTheDocument();

    await user.clear(screen.getByLabelText("每日 Token 预算"));
    await user.type(screen.getByLabelText("每日 Token 预算"), "3000000");
    await user.click(screen.getByRole("button", { name: "保存模型设置" }));

    await screen.findByText("模型与预算已保存");
    expect(fetchMock.mock.calls[2]?.[1]).toEqual(
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({
          provider: "minimax",
          model: "MiniMax-M2.7",
          daily_token_budget: 3000000,
        }),
      }),
    );
  });

  it("shows a forbidden state without requesting governance data for non-admin roles", async () => {
    fetchMock.mockImplementationOnce(() =>
      response({ ...identity, user: { ...identity.user, role: "project_manager" } }),
    );

    render(<ModelGovernance />);

    expect(await screen.findByRole("heading", { name: "仅管理员可访问" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("link", { name: "模型治理" })).not.toBeInTheDocument();
  });

  it("keeps an empty qualified pool explicit and disables saving", async () => {
    fetchMock
      .mockImplementationOnce(() => response(identity))
      .mockImplementationOnce(() =>
        response({ ...governance, eligible_models: [], selection: null }),
      );

    render(<ModelGovernance />);

    expect(await screen.findByText("当前没有可发布模型")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存模型设置" })).toBeDisabled();
  });

  it("redirects expired sessions and offers retry for service errors", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 401 }));
    render(<ModelGovernance />);
    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith("/login"));

    cleanup();
    fetchMock.mockReset();
    routerReplace.mockReset();
    fetchMock
      .mockImplementationOnce(() => response(identity))
      .mockRejectedValueOnce(new Error("offline"));
    render(<ModelGovernance />);
    expect(await screen.findByRole("heading", { name: "无法读取模型治理设置" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
  });
});
