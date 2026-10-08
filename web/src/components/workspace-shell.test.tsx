import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps, ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceShell } from "./workspace-shell";
import type { WorkspaceIdentity } from "./workspace-types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/",
}));

const identity = (role: string): WorkspaceIdentity =>
  ({
    tenant: { id: "tenant-1", slug: "beepump", name: "Beehive Technology" },
    user: {
      id: "user-1",
      tenant_id: "tenant-1",
      username: "someone",
      display_name: "Someone",
      role,
      email: null,
      is_active: true,
    },
  }) as WorkspaceIdentity;

function renderShell(role: string, options: { active?: ComponentProps<typeof WorkspaceShell>["active"]; children?: ReactNode } = {}) {
  render(
    <WorkspaceShell active={options.active ?? (["supplier", "customer"].includes(role) ? "projects" : "dashboard")} identity={identity(role)} loggingOut={false} onLogout={vi.fn()}>
      {options.children ?? <p>content</p>}
    </WorkspaceShell>,
  );
  return within(screen.getByRole("navigation", { name: "主导航" }));
}

async function expandOtherEntries() {
  const nav = screen.getByRole("navigation", { name: "主导航" });
  const summary = within(nav).getByText("其他工作入口").closest("summary")!;
  if (!summary.closest("details")!.open) await userEvent.click(summary);
}

describe("WorkspaceShell global domain navigation (D31 regrouped)", () => {
  it("unions assigned module destinations without duplicating navigation or exposing administration", () => {
    const person = identity("engineer");
    person.user.work_modules = ["product", "supply", "portfolio", "engineering"];
    render(<WorkspaceShell active="my-work" identity={person} loggingOut={false} onLogout={vi.fn()}><p>content</p></WorkspaceShell>);
    const nav = within(screen.getByRole("navigation", { name: "主导航" }));
    expect(nav.getAllByRole("link", { name: "我的工作" })).toHaveLength(1);
    expect(nav.getByRole("link", { name: "产品管理工作台" })).toBeVisible();
    expect(nav.getByRole("link", { name: "组合与阻塞" })).toBeVisible();
    expect(nav.queryByRole("link", { name: "成员与角色" })).not.toBeInTheDocument();
  });
  beforeEach(() => {
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

  it("keeps search and first-time field capture reachable from the top bar for internal members", () => {
    renderShell("engineer");
    expect(screen.getByRole("link", { name: "搜索" })).toHaveAttribute("href", "/search");
    expect(screen.getByRole("link", { name: "现场采集" })).toHaveAttribute("href", "/capture");
    cleanup(); renderShell("supplier");
    expect(screen.queryByRole("link", { name: "搜索" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "现场采集" })).not.toBeInTheDocument();
  });

  it("keeps the sidebar to daily destinations with a single pinned settings entry", async () => {
    const nav = renderShell("owner");
    await expandOtherEntries();
    for (const domain of ["常用工作", "工作", "产品"]) {
      expect(nav.getByText(domain)).toBeInTheDocument();
    }
    for (const label of ["小Pai", "Review 收件箱", "知识库"]) expect(nav.getByRole("link", { name: label })).toBeInTheDocument();
    // Governance, integrations and account pages integrate into one settings
    // entry; the settings area navigates internally via SettingsNav.
    const aside = within(screen.getByRole("complementary"));
    expect(aside.getByRole("link", { name: "设置" })).toHaveAttribute(
      "href",
      "/settings/security",
    );
    for (const label of [
      "账户安全",
      "钉钉集成",
      "腾讯会议集成",
      "成员与角色",
      "组织与代理",
      "AI 治理",
      "模型治理",
      "事件流",
    ]) {
      expect(aside.queryByRole("link", { name: label })).not.toBeInTheDocument();
    }
    expect(nav.getByRole("link", { name: "组合与阻塞" })).toHaveAttribute("href", "/portfolio");
  });

  it("has no entries for contextual surfaces or project workspace tabs", async () => {
    renderShell("engineer");
    await expandOtherEntries();
    const aside = within(screen.getByRole("complementary"));
    // Field capture and global search are reached from the records that link
    // to them, not from the sidebar.
    expect(aside.queryByRole("link", { name: "现场采集" })).not.toBeInTheDocument();
    expect(aside.queryByRole("link", { name: "搜索" })).not.toBeInTheDocument();
    // Engineering, quality and gates live in the workspace's own tab bar.
    expect(aside.queryByRole("link", { name: "工程·变更" })).not.toBeInTheDocument();
    expect(aside.queryByRole("link", { name: "试制·测试·质量" })).not.toBeInTheDocument();
    expect(aside.queryByRole("link", { name: "Gate·交付物" })).not.toBeInTheDocument();
    expect(aside.getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual(
      expect.not.arrayContaining([
        "/capture",
        "/search",
        "/projects?tab=engineering",
        "/projects?tab=quality",
        "/projects?tab=gates",
      ]),
    );
    expect(aside.getByRole("link", { name: "项目工作区" })).toHaveAttribute("href", "/projects");
  });

  it("hides governance entries from an engineer but keeps their own work and settings", () => {
    const nav = renderShell("engineer");
    const aside = within(screen.getByRole("complementary"));
    for (const label of ["成员与角色", "组织与代理", "AI 治理", "模型治理", "事件流"]) {
      expect(aside.queryByRole("link", { name: label })).not.toBeInTheDocument();
    }
    expect(aside.getByRole("link", { name: "设置" })).toHaveAttribute("href", "/settings/security");
    expect(nav.getByRole("link", { name: "我的工作" })).toBeInTheDocument();
  });

  it.each(["supplier", "customer"])("drops every internal business destination for %s", role => {
    const nav = renderShell(role);
    expect(nav.queryByRole("link", { name: "组合与阻塞" })).not.toBeInTheDocument();
    expect(nav.queryByText("AI 与知识")).not.toBeInTheDocument();
    expect(nav.queryByRole("link", { name: "我的工作" })).not.toBeInTheDocument();
    // External collaborators have only their authorized projects and account settings.
    expect(nav.getByRole("link", { name: "项目工作区" })).toBeInTheDocument();
    expect(nav.getAllByRole("link").map(link => link.getAttribute("href"))).toEqual(["/projects"]);
    for (const label of ["工作首页", "需求池", "开发案例", "产品管理工作台", "知识库", "Review 收件箱", "小Pai", "项目快照"]) {
      expect(nav.queryByRole("link", { name: label })).not.toBeInTheDocument();
    }
    const aside = within(screen.getByRole("complementary"));
    expect(aside.getByRole("link", { name: "设置" })).toHaveAttribute("href", "/settings/security");
    expect(aside.queryByRole("combobox", { name: "选择工作视角" })).not.toBeInTheDocument();
    expect(aside.getByRole("link", { name: "PDOS 工作区" })).toHaveAttribute("href", "/projects");
  });

  it("starts with a compact mobile current entry and preserves every permitted destination when expanded", async () => {
    renderShell("owner");
    await expandOtherEntries();
    const aside = within(screen.getByRole("complementary"));
    const mobile = within(screen.getByRole("navigation", { name: "移动端主导航" }));
    expect(mobile.getByText("项目快照", { selector: "span" })).toHaveAttribute("aria-current", "page");
    const toggle = mobile.getByRole("button", { name: "展开导航" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    const links = document.getElementById(toggle.getAttribute("aria-controls")!)!;
    expect(within(links).queryAllByRole("link")).toHaveLength(0);
    expect(links).toHaveAttribute("hidden");

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(mobile.getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual(
      [...within(screen.getByRole("navigation", { name: "主导航" })).getAllByRole("link"), aside.getByRole("link", { name: "设置" })].map((link) => link.getAttribute("href")),
    );
    await userEvent.click(mobile.getByRole("button", { name: "收起导航" }));
    expect(within(links).queryAllByRole("link")).toHaveLength(0);
  });

  it("supports keyboard disclosure, navigation and Escape with focus restored to the toggle", async () => {
    const user = userEvent.setup();
    renderShell("engineer");
    const mobile = within(screen.getByRole("navigation", { name: "移动端主导航" }));
    const toggle = mobile.getByRole("button", { name: "展开导航" });
    toggle.focus();
    await user.keyboard("{Enter}");
    await user.tab();
    expect(mobile.getByRole("link", { name: "工作首页" })).toHaveFocus();
    await user.tab();
    expect(mobile.getByRole("link", { name: "我的工作" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(toggle).toHaveFocus();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.keyboard(" ");
    const projectsLink = mobile.getByRole("link", { name: "项目工作区" });
    projectsLink.addEventListener("click", (event) => event.preventDefault());
    projectsLink.focus();
    await user.keyboard("{Enter}");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveFocus();
  });

  it.each(["engineer", "supplier", "customer"])("keeps mobile permission filtering for %s", async (role) => {
    renderShell(role);
    const mobile = within(screen.getByRole("navigation", { name: "移动端主导航" }));
    await userEvent.click(mobile.getByRole("button", { name: "展开导航" }));
    expect(mobile.queryByRole("link", { name: "AI 治理" })).not.toBeInTheDocument();
    expect(mobile.queryByRole("link", { name: "组织与代理" })).not.toBeInTheDocument();
    expect(mobile.getByRole("link", { name: "项目工作区" })).toHaveAttribute("href", "/projects");
    if (["supplier", "customer"].includes(role)) {
      expect(mobile.queryByRole("link", { name: "我的工作" })).not.toBeInTheDocument();
      expect(mobile.queryByRole("link", { name: "Review 收件箱" })).not.toBeInTheDocument();
      for (const label of ["工作首页", "需求池", "开发案例", "产品管理工作台", "知识库", "小Pai", "项目快照"]) expect(mobile.queryByRole("link", { name: label })).not.toBeInTheDocument();
      expect(mobile.queryByRole("combobox", { name: "选择工作视角" })).not.toBeInTheDocument();
    } else {
      expect(mobile.getByRole("link", { name: "我的工作" })).toHaveAttribute("href", "/my-work");
    }
  });

  it("retains sidebar preference across pages while keeping every permitted link named", async () => {
    const user = userEvent.setup();
    renderShell("owner");
    await user.click(screen.getByRole("button", { name: "收起侧栏" }));
    expect(screen.getByRole("button", { name: "展开侧栏" })).toHaveAttribute("aria-expanded", "false");
    expect(window.localStorage.getItem("pdos.navigation.collapsed")).toBe("true");
    const nav = within(screen.getByRole("navigation", { name: "主导航" }));
    expect(nav.getByRole("link", { name: "我的工作" })).toHaveAttribute("title", "我的工作");
    cleanup();
    renderShell("owner");
    expect(screen.getByRole("button", { name: "展开侧栏" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "展开侧栏" }));
    expect(window.localStorage.getItem("pdos.navigation.collapsed")).toBe("false");
  });

  it.each(["engineer", "quality"])("keeps %s's home separate from the explicit read-only project snapshot", async role => {
    const nav = renderShell(role);
    await expandOtherEntries();
    expect(nav.getByRole("link", { name: "工作首页" })).toHaveAttribute("href", "/");
    expect(nav.getByRole("link", { name: "项目快照" })).toHaveAttribute("href", "/dashboard");
    expect(nav.getByRole("link", { name: "我的工作" })).toHaveAttribute("href", "/my-work");
  });

  it.each([
    ["product_manager", ["/product-work", "/requirements", "/cases", "/my-work", "/ask"]],
    ["project_manager", ["/projects", "/my-work", "/cases", "/portfolio", "/ask"]],
    ["engineer", ["/my-work", "/projects", "/ai-review", "/knowledge", "/ask"]],
    ["quality", ["/my-work", "/projects", "/ai-review", "/knowledge", "/ask"]],
    ["admin", ["/governance/users", "/governance/organization", "/governance/models", "/governance/ai", "/events"]],
  ])("automatically orders %s's work on desktop and mobile without a picker", async (role, routes) => {
    const nav = renderShell(role);
    expect(screen.queryByRole("combobox", { name: "选择工作视角" })).not.toBeInTheDocument();
    const primary = within(nav.getByText("常用工作").parentElement!);
    expect(primary.getAllByRole("link").map(link => link.getAttribute("href"))).toEqual(routes);
    await userEvent.click(screen.getByRole("button", { name: "展开导航" }));
    const mobile = within(screen.getByRole("navigation", { name: "移动端主导航" }));
    expect(mobile.queryByRole("combobox")).not.toBeInTheDocument();
    expect(mobile.getAllByRole("link").slice(1, routes.length + 1).map(link => link.getAttribute("href"))).toEqual(routes);
  });

  it("ignores a saved unrelated perspective and retains the original page and permissions", async () => {
    window.localStorage.setItem("pdos.work-perspective:tenant-1:user-1", "administration");
    const taskHref = "/projects?project=project-1&view=work-items&entity_id=task-1";
    const nav = renderShell("engineer", { active: "projects", children: <section aria-label="当前办理事项"><p>当前办理人：工程责任人</p><a href={taskHref}>继续原任务</a><button disabled>需要具名评审权限</button></section> });
    const primary = within(nav.getByText("常用工作").parentElement!);
    expect(primary.getAllByRole("link")[0]).toHaveAttribute("href", "/my-work");
    expect(screen.getByText("当前办理人：工程责任人")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "继续原任务" })).toHaveAttribute("href", taskHref);
    expect(screen.getByRole("button", { name: "需要具名评审权限" })).toBeDisabled();
    expect(nav.getByRole("link", { name: "项目工作区" })).toHaveAttribute("aria-current", "page");
    for (const label of ["成员与角色", "组织与流程", "模型可用性", "AI 治理", "运行与事件"]) expect(nav.queryByRole("link", { name: label })).not.toBeInTheDocument();
  });

  it("opens a product detail without a generic work-path banner", () => {
    renderShell("product_manager", { active: "product-work" });
    expect(screen.queryByLabelText("当前工作路径")).not.toBeInTheDocument();
    expect(screen.queryByText("工作视角")).not.toBeInTheDocument();
  });
});
