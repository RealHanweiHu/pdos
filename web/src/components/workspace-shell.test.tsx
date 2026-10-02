import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

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

function renderShell(role: string) {
  render(
    <WorkspaceShell active="dashboard" identity={identity(role)} loggingOut={false} onLogout={vi.fn()}>
      <p>content</p>
    </WorkspaceShell>,
  );
  return within(screen.getByRole("navigation", { name: "主导航" }));
}

describe("WorkspaceShell global domain navigation (D31 regrouped)", () => {
  afterEach(cleanup);

  it("keeps search and first-time field capture reachable from the top bar for internal members", () => {
    renderShell("engineer");
    expect(screen.getByRole("link", { name: "搜索" })).toHaveAttribute("href", "/search");
    expect(screen.getByRole("link", { name: "现场采集" })).toHaveAttribute("href", "/capture");
    cleanup(); renderShell("supplier");
    expect(screen.queryByRole("link", { name: "搜索" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "现场采集" })).not.toBeInTheDocument();
  });

  it("keeps the sidebar to daily destinations with a single pinned settings entry", () => {
    const nav = renderShell("owner");
    for (const domain of ["工作", "项目", "产品", "AI 与知识"]) {
      expect(nav.getByText(domain)).toBeInTheDocument();
    }
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

  it("has no entries for contextual surfaces or project workspace tabs", () => {
    renderShell("engineer");
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

  it("drops internal-only domains that an external member may not enter", () => {
    const nav = renderShell("supplier");
    expect(nav.queryByRole("link", { name: "组合与阻塞" })).not.toBeInTheDocument();
    expect(nav.queryByText("AI 与知识")).not.toBeInTheDocument();
    expect(nav.queryByRole("link", { name: "我的工作" })).not.toBeInTheDocument();
    // Projects, product surfaces and the settings area stay reachable for external collaborators.
    expect(nav.getByRole("link", { name: "项目工作区" })).toBeInTheDocument();
    expect(nav.getByRole("link", { name: "需求池" })).toBeInTheDocument();
    const aside = within(screen.getByRole("complementary"));
    expect(aside.getByRole("link", { name: "设置" })).toHaveAttribute("href", "/settings/security");
  });

  it("starts with a compact mobile current entry and preserves every permitted destination when expanded", async () => {
    renderShell("owner");
    const aside = within(screen.getByRole("complementary"));
    const mobile = within(screen.getByRole("navigation", { name: "移动端主导航" }));
    expect(mobile.getByText("驾驶舱", { selector: "span" })).toHaveAttribute("aria-current", "page");
    const toggle = mobile.getByRole("button", { name: "展开导航" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(mobile.queryAllByRole("link")).toHaveLength(0);
    expect(document.getElementById(toggle.getAttribute("aria-controls")!)).toHaveAttribute("hidden");

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(mobile.getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual(
      aside.getAllByRole("link").map((link) => link.getAttribute("href")),
    );
    await userEvent.click(mobile.getByRole("button", { name: "收起导航" }));
    expect(mobile.queryAllByRole("link")).toHaveLength(0);
  });

  it("supports keyboard disclosure, navigation and Escape with focus restored to the toggle", async () => {
    const user = userEvent.setup();
    renderShell("engineer");
    const mobile = within(screen.getByRole("navigation", { name: "移动端主导航" }));
    const toggle = mobile.getByRole("button", { name: "展开导航" });
    toggle.focus();
    await user.keyboard("{Enter}");
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

  it.each(["engineer", "supplier"])("keeps mobile permission filtering for %s", async (role) => {
    renderShell(role);
    const mobile = within(screen.getByRole("navigation", { name: "移动端主导航" }));
    await userEvent.click(mobile.getByRole("button", { name: "展开导航" }));
    expect(mobile.queryByRole("link", { name: "AI 治理" })).not.toBeInTheDocument();
    expect(mobile.queryByRole("link", { name: "组织与代理" })).not.toBeInTheDocument();
    expect(mobile.getByRole("link", { name: "项目工作区" })).toHaveAttribute("href", "/projects");
    if (role === "supplier") {
      expect(mobile.queryByRole("link", { name: "我的工作" })).not.toBeInTheDocument();
      expect(mobile.queryByRole("link", { name: "Review 收件箱" })).not.toBeInTheDocument();
    } else {
      expect(mobile.getByRole("link", { name: "我的工作" })).toHaveAttribute("href", "/my-work");
    }
  });
});
