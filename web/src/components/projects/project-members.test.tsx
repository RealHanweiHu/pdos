import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProjectMembers } from "./project-members";

const manager = {
  user_id: "u-manager",
  username: "manager",
  display_name: "项目经理甲",
  role: "project_manager",
  is_active: true,
  added_by_display_name: "Initial Owner",
  created_at: "2026-09-20T08:00:00Z",
  is_owner: true,
  removal_blocker: "项目负责人不能移出项目",
};
const engineer = {
  ...manager,
  user_id: "u-engineer",
  username: "engineer",
  display_name: "工程师甲",
  role: "engineer",
  is_owner: false,
  removal_blocker: null,
};
const newcomer = { user_id: "u-new", username: "engineer2", display_name: "工程师乙", role: "engineer" };

function roster(overrides: Record<string, unknown> = {}) {
  return { can_manage: true, items: [manager, engineer], available_users: [newcomer], ...overrides };
}

function open() {
  const details = screen.getByText(/^项目成员/).closest("details");
  if (!details) throw new Error("members panel missing");
  details.open = true;
  fireEvent(details, new Event("toggle"));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ProjectMembers", () => {
  it("loads only when opened, names members and adds with a request id", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") {
        return Response.json(
          roster({ items: [manager, engineer, { ...engineer, ...newcomer, added_by_display_name: "项目经理甲" }], available_users: [] }),
          { status: 201 },
        );
      }
      return Response.json(roster());
    });
    vi.stubGlobal("fetch", fetcher);
    render(<ProjectMembers projectId="p-1" userId="u-manager" />);
    expect(fetcher).not.toHaveBeenCalled();

    open();
    const list = await screen.findByRole("list", { name: "项目成员名单" });
    expect(within(list).getByText("工程师甲")).toBeVisible();
    expect(within(list).getByText("项目负责人不能移出项目")).toBeVisible();
    expect(within(list).getAllByRole("button", { name: "移出项目" })).toHaveLength(1);

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "u-new" } });
    fireEvent.click(screen.getByRole("button", { name: "加入项目" }));
    expect(await screen.findByRole("status")).toHaveTextContent("已将 工程师乙 加入项目。");
    expect(within(list).getByText("工程师乙")).toBeVisible();
    expect(screen.getByText("没有可添加的在岗内部成员。")).toBeVisible();

    const [url, init] = fetcher.mock.calls[1];
    expect(url).toBe("/api/projects/p-1/members");
    const body = JSON.parse(String(init?.body));
    expect(body.user_id).toBe("u-new");
    expect(body.request_id).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("replays a lost removal with the same request id and asks before removing", async () => {
    let attempt = 0;
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method !== "POST") return Response.json(roster());
      attempt += 1;
      if (attempt === 1) throw new TypeError("network down");
      return Response.json(roster({ items: [manager] }));
    });
    vi.stubGlobal("fetch", fetcher);
    render(<ProjectMembers projectId="p-1" userId="u-manager" />);
    open();

    fireEvent.click(await screen.findByRole("button", { name: "移出项目" }));
    const confirm = screen.getByRole("group", { name: "确认移出成员" });
    expect(confirm).toHaveTextContent("已分派给其的工作不会自动转交");
    fireEvent.click(within(confirm).getByRole("button", { name: "确认移出" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("重试将沿用同一请求");

    fireEvent.click(screen.getByRole("button", { name: "移出项目" }));
    fireEvent.click(screen.getByRole("button", { name: "确认移出" }));
    expect(await screen.findByRole("status")).toHaveTextContent("已将 工程师甲 移出项目。");

    const removals = fetcher.mock.calls.filter(([, init]) => init?.method === "POST");
    expect(removals.map(([url]) => url)).toEqual([
      "/api/projects/p-1/members/u-engineer/remove",
      "/api/projects/p-1/members/u-engineer/remove",
    ]);
    const ids = removals.map(([, init]) => JSON.parse(String(init?.body)).request_id);
    expect(ids[0]).toBe(ids[1]);
  });

  it("shows the server conflict and refreshes the roster it came from", async () => {
    let reads = 0;
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") {
        return Response.json(
          { detail: { code: "PROJECT_LAST_MANAGER", message: "项目须至少保留一名在岗的项目经理成员" } },
          { status: 409 },
        );
      }
      reads += 1;
      return Response.json(reads === 1 ? roster() : roster({ items: [manager, { ...engineer, removal_blocker: "项目须至少保留一名在岗的项目经理成员" }] }));
    });
    vi.stubGlobal("fetch", fetcher);
    render(<ProjectMembers projectId="p-1" userId="u-manager" />);
    open();

    fireEvent.click(await screen.findByRole("button", { name: "移出项目" }));
    fireEvent.click(screen.getByRole("button", { name: "确认移出" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("项目须至少保留一名在岗的项目经理成员");
    await waitFor(() => expect(screen.queryByRole("button", { name: "移出项目" })).not.toBeInTheDocument());
    expect(reads).toBe(2);
  });

  it("offers no staffing controls to members who cannot manage", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json(roster({ can_manage: false, available_users: [] }))));
    render(<ProjectMembers projectId="p-1" userId="u-engineer" />);
    open();

    expect(await screen.findByText("成员调整由本项目的项目经理或租户管理员办理。")).toBeVisible();
    expect(screen.queryByRole("button", { name: "移出项目" })).not.toBeInTheDocument();
    expect(screen.queryByText("项目负责人不能移出项目")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("does not show a backend English denial", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ detail: { code: "OBJECT_PERMISSION_DENIED", message: "The requested project action is not permitted" } }, { status: 403 })));
    render(<ProjectMembers projectId="p-1" userId="u-supplier" />);
    open();

    expect(await screen.findByRole("alert")).toHaveTextContent("当前没有办理本项目成员的权限");
    expect(screen.getByRole("button", { name: "重新读取成员" })).toBeVisible();
  });
});

describe("member receipt recovery", () => {
  it("retains the request id when a successful response body is lost", async () => {
    let writes = 0;
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method !== "POST") return Response.json(roster());
      writes += 1;
      if (writes === 1) return new Response("truncated", { status: 201 });
      return Response.json(roster({ receipt: { replayed: true } }));
    });
    vi.stubGlobal("fetch", fetcher);
    render(<ProjectMembers projectId="p-1" userId="u-manager" />);
    open();
    fireEvent.change(await screen.findByRole("combobox"), { target: { value: "u-new" } });
    fireEvent.click(screen.getByRole("button", { name: "加入项目" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("未收到完整回执");
    fireEvent.click(screen.getByRole("button", { name: "加入项目" }));
    expect(await screen.findByRole("status")).toHaveTextContent("已核对原添加回执");
    const ids = fetcher.mock.calls.filter(([, init]) => init?.method === "POST")
      .map(([, init]) => JSON.parse(String(init?.body)).request_id);
    expect(ids).toHaveLength(2);
    expect(ids[0]).toBe(ids[1]);
  });

  it("clears a previously visible roster when current permission is denied", async () => {
    let reads = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      reads += 1;
      return reads === 1 ? Response.json(roster()) : Response.json({}, { status: 403 });
    }));
    render(<ProjectMembers projectId="p-1" userId="u-manager" />);
    open();
    fireEvent.click(await screen.findByRole("button", { name: "刷新成员" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("当前没有办理本项目成员的权限");
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("stops showing management controls after removing oneself", async () => {
    vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
      Response.json(init?.method === "POST"
        ? roster({ can_manage: false, access_lost: true, items: [], available_users: [] })
        : roster({ items: [manager, { ...engineer, role: "project_manager" }] }))));
    render(<ProjectMembers projectId="p-1" userId="u-engineer" />);
    open();
    fireEvent.click(await screen.findByRole("button", { name: "移出项目" }));
    expect(screen.getByRole("group", { name: "确认移出成员" })).toHaveTextContent("你正在移出自己");
    fireEvent.click(screen.getByRole("button", { name: "确认移出" }));
    expect(await screen.findByRole("status")).toHaveTextContent("项目访问权限已收回");
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });
});
