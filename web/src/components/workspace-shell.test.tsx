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

describe("WorkspaceShell global domain navigation (D31)", () => {
  afterEach(cleanup);

  it("groups an admin's surfaces under the ten global domains", () => {
    const nav = renderShell("owner");
    for (const domain of [
      "工作台",
      "项目组合",
      "产品",
      "项目",
      "工程",
      "质量",
      "交付",
      "知识",
      "AI 工作台",
      "管理",
    ]) {
      expect(nav.getByText(domain)).toBeInTheDocument();
    }
    expect(nav.getByRole("link", { name: "组合与阻塞" })).toHaveAttribute("href", "/portfolio");
    expect(nav.getByRole("link", { name: "组织与代理" })).toHaveAttribute(
      "href",
      "/governance/organization",
    );
  });

  it("points the project-scoped domains at the matching workspace tab", () => {
    const nav = renderShell("engineer");
    expect(nav.getByRole("link", { name: "工程·变更" })).toHaveAttribute(
      "href",
      "/projects?tab=engineering",
    );
    expect(nav.getByRole("link", { name: "试制·测试·质量" })).toHaveAttribute(
      "href",
      "/projects?tab=quality",
    );
    expect(nav.getByRole("link", { name: "Gate·交付物" })).toHaveAttribute(
      "href",
      "/projects?tab=gates",
    );
  });

  it("hides admin-only domains from an engineer but keeps their own work", () => {
    const nav = renderShell("engineer");
    expect(nav.queryByText("管理")).toBeInTheDocument(); // 账户安全 keeps Admin visible
    expect(nav.queryByRole("link", { name: "模型治理" })).not.toBeInTheDocument();
    expect(nav.queryByRole("link", { name: "AI 治理" })).not.toBeInTheDocument();
    expect(nav.getByRole("link", { name: "我的工作" })).toBeInTheDocument();
  });

  it("drops whole domains that an external member may not enter", () => {
    const nav = renderShell("supplier");
    expect(nav.queryByText("项目组合")).not.toBeInTheDocument();
    expect(nav.queryByText("知识")).not.toBeInTheDocument();
    expect(nav.queryByText("AI 工作台")).not.toBeInTheDocument();
    expect(nav.queryByRole("link", { name: "我的工作" })).not.toBeInTheDocument();
    // Products and Projects stay reachable for external collaborators.
    expect(nav.getByRole("link", { name: "项目工作区" })).toBeInTheDocument();
    expect(nav.getByRole("link", { name: "需求池" })).toBeInTheDocument();
  });

  it("starts with a compact mobile current entry and preserves every permitted destination when expanded", async () => {
    const desktop = renderShell("owner");
    const mobile = within(screen.getByRole("navigation", { name: "移动端主导航" }));
    expect(mobile.getByText("驾驶舱", { selector: "span" })).toHaveAttribute("aria-current", "page");
    const toggle = mobile.getByRole("button", { name: "展开导航" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(mobile.queryAllByRole("link")).toHaveLength(0);
    expect(document.getElementById(toggle.getAttribute("aria-controls")!)).toHaveAttribute("hidden");

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(mobile.getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual(
      desktop.getAllByRole("link").map((link) => link.getAttribute("href")),
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
    expect(mobile.getByRole("link", { name: "驾驶舱" })).toHaveFocus();
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
