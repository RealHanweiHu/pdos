import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceHome } from "./workspace-home";
import type { WorkspaceIdentity } from "./workspace-types";

const { replace, requestIdentity } = vi.hoisted(() => ({ replace: vi.fn(), requestIdentity: vi.fn<() => Promise<WorkspaceIdentity | null>>() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }), usePathname: () => "/" }));
vi.mock("./workspace-api", () => ({ requestIdentity }));

let identitySequence = 0;
function identity(role: string, tenantId = "home-tenant", userId = `home-user-${++identitySequence}`): WorkspaceIdentity {
  return {
    tenant: { id: tenantId, slug: tenantId, name: "测试组织" },
    user: { id: userId, tenant_id: tenantId, username: userId, display_name: "测试成员", role, email: null, is_active: true },
  };
}
function remember(person: WorkspaceIdentity, perspective: string) {
  window.localStorage.setItem(`pdos.work-perspective:${encodeURIComponent(person.tenant.id)}:${encodeURIComponent(person.user.id)}`, perspective);
}

describe("WorkspaceHome personal login entry", () => {
  beforeEach(() => {
    replace.mockReset(); requestIdentity.mockReset();
    const values = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
      key: (index: number) => [...values.keys()][index] ?? null,
      get length() { return values.size; },
      clear: () => values.clear(),
    });
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it.each(["product_manager", "project_manager", "engineer", "quality", "owner", "admin"])("opens %s's own work without a manual view selection", async role => {
    const person = identity(role);
    requestIdentity.mockResolvedValue(person);
    render(<WorkspaceHome />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/my-work"));
    expect(screen.getByText("正在打开测试成员的工作台…")).toBeInTheDocument();
    expect(replace).toHaveBeenCalledTimes(1);
  });

  it.each(["product", "project", "quality", "portfolio", "administration", "unknown-perspective"])("ignores the old %s preference when opening an engineer's own work", async perspective => {
    const person = identity("engineer");
    remember(person, perspective);
    requestIdentity.mockResolvedValue(person);
    render(<WorkspaceHome />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/my-work"));
    expect(replace).toHaveBeenCalledTimes(1);
  });

  it.each(["supplier", "customer", "unknown"])("opens only authorized projects for %s despite a saved internal view", async role => {
    const person = identity(role);
    remember(person, "administration");
    requestIdentity.mockResolvedValue(person);
    render(<WorkspaceHome />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/projects"));
    expect(screen.getByText("正在打开测试成员的已授权项目…")).toBeInTheDocument();
    expect(replace).toHaveBeenCalledTimes(1);
  });

  it("returns an unauthenticated visitor to login", async () => {
    requestIdentity.mockResolvedValue(null);
    render(<WorkspaceHome />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    expect(replace).not.toHaveBeenCalledWith("/projects");
    expect(replace).not.toHaveBeenCalledWith("/my-work");
  });

  it("can retry identity failure before choosing an authorized home", async () => {
    const person = identity("project_manager");
    remember(person, "product");
    requestIdentity.mockRejectedValueOnce(new Error("unavailable")).mockResolvedValueOnce(person);
    render(<WorkspaceHome />);
    expect(await screen.findByRole("heading", { name: "工作首页暂不可用" })).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/my-work"));
    expect(requestIdentity).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("heading", { name: "工作首页暂不可用" })).not.toBeInTheDocument();
  });

  it("does not navigate using an identity response after the page has unmounted", async () => {
    let finish!: (value: WorkspaceIdentity) => void;
    requestIdentity.mockReturnValue(new Promise(resolve => { finish = resolve; }));
    const view = render(<WorkspaceHome />);
    view.unmount();
    await act(async () => { finish(identity("owner")); });
    expect(replace).not.toHaveBeenCalled();
  });
});
