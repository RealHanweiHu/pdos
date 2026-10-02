"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import type { WorkspaceIdentity } from "@/components/workspace-types";
import { cn } from "@/lib/utils";

/**
 * Settings-area secondary navigation (D31 follow-up, 2026-09-29): the global
 * sidebar carries one pinned 设置 entry; the rarely opened account,
 * integration and governance pages are classified here into 账户 / 集成 /
 * 治理 sections instead of eight flat sidebar entries. Routes stay unchanged,
 * so existing bookmarks and receipts keep working.
 */
const sections = [
  {
    label: "账户",
    items: [{ href: "/settings/security", label: "账户安全", key: "account-security" }],
  },
  {
    label: "集成",
    internalOnly: true,
    items: [
      { href: "/settings/integrations/dingtalk", label: "钉钉", key: "dingtalk-integration" },
      {
        href: "/settings/integrations/tencent-meeting",
        label: "腾讯会议",
        key: "tencent-meeting-integration",
      },
    ],
  },
  {
    label: "治理",
    adminOnly: true,
    items: [
      { href: "/governance/users", label: "成员与角色", key: "user-management" },
      { href: "/governance/organization", label: "组织与代理", key: "organization" },
      { href: "/governance/ai", label: "AI 治理", key: "ai-governance" },
      { href: "/governance/models", label: "模型治理", key: "model-governance" },
      { href: "/events", label: "事件流", key: "events" },
    ],
  },
] as const;

export type SettingsSectionKey = (typeof sections)[number]["items"][number]["key"];

export function SettingsNav({
  current,
  identity,
  children,
}: {
  current: SettingsSectionKey;
  identity: WorkspaceIdentity;
  children: ReactNode;
}) {
  const isAdmin = ["owner", "admin"].includes(identity.user.role);
  const isExternal = ["supplier", "customer"].includes(identity.user.role);
  const visibleSections = sections.filter(
    (section) =>
      (!("adminOnly" in section) || isAdmin) && (!("internalOnly" in section) || !isExternal),
  );
  return (
    <div className="lg:grid lg:grid-cols-[180px_minmax(0,1fr)] lg:gap-8">
      <nav aria-label="设置导航" className="mb-6 lg:mb-0">
        {visibleSections.map((section) => (
          <div className="mb-4 last:mb-0 lg:mb-5" key={section.label}>
            <p className="hidden px-2 pb-1 text-[11px] font-medium text-muted-foreground lg:block">
              {section.label}
            </p>
            <ul className="flex flex-wrap gap-1 lg:block lg:space-y-0.5" role="list">
              {section.items.map(({ href, key, label }) => (
                <li key={key}>
                  <Link
                    aria-current={current === key ? "page" : undefined}
                    className={cn(
                      "flex min-h-11 items-center rounded-md px-2 text-[13px] text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/30 lg:min-h-8",
                      current === key && "bg-muted font-medium text-foreground",
                    )}
                    href={href}
                  >
                    {label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
      <div className="min-w-0">{children}</div>
    </div>
  );
}
