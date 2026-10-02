import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SettingsNav } from "./settings-nav";
import type { WorkspaceIdentity } from "@/components/workspace-types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/settings/security",
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

function renderNav(role: string, current: Parameters<typeof SettingsNav>[0]["current"] = "account-security") {
  render(
    <SettingsNav current={current} identity={identity(role)}>
      <p>settings content</p>
    </SettingsNav>,
  );
  return within(screen.getByRole("navigation", { name: "设置导航" }));
}

describe("SettingsNav classified secondary navigation", () => {
  afterEach(cleanup);

  it("classifies all eight settings surfaces for an admin", () => {
    const nav = renderNav("owner");
    for (const section of ["账户", "集成", "治理"]) {
      expect(nav.getByText(section)).toBeInTheDocument();
    }
    for (const [label, href] of [
      ["账户安全", "/settings/security"],
      ["钉钉", "/settings/integrations/dingtalk"],
      ["腾讯会议", "/settings/integrations/tencent-meeting"],
      ["成员与角色", "/governance/users"],
      ["组织与代理", "/governance/organization"],
      ["AI 治理", "/governance/ai"],
      ["模型治理", "/governance/models"],
      ["事件流", "/events"],
    ] as const) {
      expect(nav.getByRole("link", { name: label })).toHaveAttribute("href", href);
    }
    expect(screen.getByText("settings content")).toBeInTheDocument();
  });

  it("hides the governance section from an engineer", () => {
    const nav = renderNav("engineer");
    expect(nav.queryByText("治理")).not.toBeInTheDocument();
    expect(nav.getByText("账户")).toBeInTheDocument();
    expect(nav.getByText("集成")).toBeInTheDocument();
    expect(nav.queryByRole("link", { name: "事件流" })).not.toBeInTheDocument();
  });

  it("leaves only the account section for an external member", () => {
    const nav = renderNav("supplier");
    expect(nav.getAllByRole("link")).toHaveLength(1);
    expect(nav.getByRole("link", { name: "账户安全" })).toBeInTheDocument();
  });

  it("marks the current section entry as the page", () => {
    const nav = renderNav("owner", "model-governance");
    expect(nav.getByRole("link", { name: "模型治理" })).toHaveAttribute("aria-current", "page");
    expect(nav.getByRole("link", { name: "账户安全" })).not.toHaveAttribute("aria-current");
  });
});
