import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { routerReplace } = vi.hoisted(() => ({ routerReplace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: routerReplace }),
}));

import { EventDebugger } from "./event-debugger";

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

const catalog = {
  items: [
    {
      event_type: "PROJECT_CREATED",
      version: 1,
      entity: "project",
      producer: "project_service",
      consumers: ["timeline_projection", "agent_dispatcher"],
      payload_schema: { type: "object", properties: {}, required: [] },
      idempotency: "unique(source,event_id); reuse event_id on retry",
      implemented_in_sprint_1: true,
    },
    {
      event_type: "GATE_APPROVED",
      version: 1,
      entity: "gate",
      producer: "gate_service",
      consumers: ["timeline_projection"],
      payload_schema: { type: "object", properties: {}, required: [] },
      idempotency: "unique(source,event_id); reuse event_id on retry",
      implemented_in_sprint_1: false,
    },
  ],
};

const firstPage = {
  items: [
    {
      id: 41,
      project_id: "project-1",
      event_id: "project:project-1:created",
      event_type: "PROJECT_CREATED",
      schema_version: 1,
      source: "project_service",
      entity: "project",
      entity_id: "project-1",
      payload: { project_code: "PDOS-001", project_name: "PDOS" },
      timestamp: "2026-08-11T16:00:00Z",
      consumers: ["timeline_projection", "agent_dispatcher"],
    },
  ],
  next_after_id: 41,
  has_more: true,
};

function response(body: object, status = 200) {
  return Promise.resolve(Response.json(body, { status }));
}

describe("EventDebugger", () => {
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

  it("renders the read-only envelope, consumers, and payload", async () => {
    fetchMock
      .mockImplementationOnce(() => response(identity))
      .mockImplementationOnce(() => response(catalog))
      .mockImplementationOnce(() => response(firstPage));

    render(<EventDebugger />);

    expect(await screen.findByRole("heading", { name: "事件流调试" })).toBeInTheDocument();
    expect(screen.getAllByText("PROJECT_CREATED")).toHaveLength(2);
    expect(screen.getByText("project_service")).toBeInTheDocument();
    expect(screen.getByText("timeline_projection")).toBeInTheDocument();
    expect(screen.getByText(/PDOS-001/)).toBeInTheDocument();
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /重放|执行/ })).not.toBeInTheDocument();
  });

  it("applies filters and extends the stream from its stable cursor", async () => {
    const user = userEvent.setup();
    fetchMock
      .mockImplementationOnce(() => response(identity))
      .mockImplementationOnce(() => response(catalog))
      .mockImplementationOnce(() => response(firstPage))
      .mockImplementationOnce(() =>
        response({
          items: [
            {
              ...firstPage.items[0],
              id: 42,
              event_id: "project:project-1:status:active",
              event_type: "PROJECT_STATUS_CHANGED",
            },
          ],
          next_after_id: 42,
          has_more: false,
        }),
      )
      .mockImplementationOnce(() =>
        response({ ...firstPage, items: [], next_after_id: null, has_more: false }),
      )
      .mockImplementationOnce(() => response(firstPage));
    render(<EventDebugger />);
    await screen.findAllByText("PROJECT_CREATED");

    await user.click(screen.getByRole("button", { name: "加载更多" }));
    await screen.findByText("PROJECT_STATUS_CHANGED");
    expect(String(fetchMock.mock.calls[3]?.[0])).toBe(
      "/api/events?limit=50&after_id=41",
    );

    await user.selectOptions(screen.getByLabelText("事件类型"), "PROJECT_CREATED");
    await user.type(screen.getByLabelText("项目 ID"), "project-1");
    await user.click(screen.getByRole("button", { name: "应用筛选" }));
    await waitFor(() =>
      expect(String(fetchMock.mock.calls[4]?.[0])).toBe(
        "/api/events?limit=50&event_type=PROJECT_CREATED&project_id=project-1",
      ),
    );

    await user.click(screen.getByRole("button", { name: "清除筛选" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(6));
  });

  it("shows a forbidden state without requesting event data for non-admin roles", async () => {
    fetchMock.mockImplementationOnce(() =>
      response({ ...identity, user: { ...identity.user, role: "project_manager" } }),
    );

    render(<EventDebugger />);

    expect(await screen.findByRole("heading", { name: "仅管理员可访问" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("link", { name: "事件流" })).not.toBeInTheDocument();
  });

  it("redirects an expired session to login", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 401 }));
    render(<EventDebugger />);

    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith("/login"));
  });
});
