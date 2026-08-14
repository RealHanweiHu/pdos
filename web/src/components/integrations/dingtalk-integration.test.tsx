import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { routerReplace } = vi.hoisted(() => ({ routerReplace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: routerReplace }),
}));

import { DingTalkIntegration } from "./dingtalk-integration";

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

function response(body: object, status = 200) {
  return Promise.resolve(Response.json(body, { status }));
}

describe("DingTalkIntegration", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    fetchMock.mockReset();
    routerReplace.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("shows fail-closed delivery state and admin outbox evidence", async () => {
    fetchMock
      .mockImplementationOnce(() => response(identity))
      .mockImplementationOnce(() =>
        response({
          configured: true,
          binding_status: "active",
          corp_id: "ding-corp",
          linked: false,
          delivery_enabled: false,
        }),
      )
      .mockImplementationOnce(() =>
        response({
          items: [
            {
              id: "outbox-1",
              project_id: "project-1",
              operation: "gate_approval_create",
              status: "uncertain",
              attempt_count: 1,
              remote_reference: null,
              last_error_code: "DINGTALK_CREATE_OUTCOME_UNKNOWN",
            },
          ],
        }),
      );

    render(<DingTalkIntegration />);

    expect(await screen.findByRole("heading", { name: "钉钉集成" })).toBeInTheDocument();
    expect(screen.getByText("人工降级")).toBeInTheDocument();
    expect(screen.getByText("Gate 外部审批")).toBeInTheDocument();
    expect(screen.getByText("uncertain")).toBeInTheDocument();
    expect(screen.getByText("DINGTALK_CREATE_OUTCOME_UNKNOWN")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "显式绑定当前身份" })).toBeEnabled();
  });

  it("starts explicit link at the fixed DingTalk host", async () => {
    const user = userEvent.setup();
    const assign = vi.fn();
    vi.stubGlobal("location", { assign });
    fetchMock
      .mockImplementationOnce(() => response({ ...identity, user: { ...identity.user, role: "engineer" } }))
      .mockImplementationOnce(() =>
        response({
          configured: true,
          binding_status: "active",
          corp_id: "ding-corp",
          linked: false,
          delivery_enabled: true,
        }),
      )
      .mockImplementationOnce(() =>
        response({
          authorization_url: "https://login.dingtalk.com/oauth2/auth?state=opaque",
          expires_in: 300,
        }),
      );

    render(<DingTalkIntegration />);
    await user.click(await screen.findByRole("button", { name: "显式绑定当前身份" }));

    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith(
        "https://login.dingtalk.com/oauth2/auth?state=opaque",
      ),
    );
    expect(screen.queryByRole("heading", { name: "最近投递" })).not.toBeInTheDocument();
  });

  it("does not request integration APIs for external roles", async () => {
    fetchMock.mockImplementationOnce(() =>
      response({ ...identity, user: { ...identity.user, role: "supplier" } }),
    );

    render(<DingTalkIntegration />);

    expect(await screen.findByRole("heading", { name: "当前角色不可访问" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("link", { name: "钉钉集成" })).not.toBeInTheDocument();
  });
});
