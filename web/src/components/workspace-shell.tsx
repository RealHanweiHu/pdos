"use client";

import {
  BookOpenTextIcon,
  CameraIcon,
  ClipboardTextIcon,
  FolderOpenIcon,
  GaugeIcon,
  GearSixIcon,
  KanbanIcon,
  ListIcon,
  MagnifyingGlassIcon,
  ListChecksIcon,
  LockKeyIcon,
  PulseIcon,
  PlugsConnectedIcon,
  SignOutIcon,
  TrayIcon,
  UsersThreeIcon,
} from "@phosphor-icons/react";
import Link from "next/link";
import { useRef, useState, type ReactNode } from "react";

import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import type { WorkspaceIdentity } from "@/components/workspace-types";
import { cn } from "@/lib/utils";

/**
 * D31 two-layer information architecture: ten global domains on top, the
 * project workspace's nine business tabs inside a project. A domain groups the
 * surfaces that already exist; domains whose own data plane arrives in a later
 * phase point at the surface that carries that work today.
 */
const domains = [
  {
    domain: "Home",
    label: "工作台",
    items: [
      { href: "/", label: "驾驶舱", icon: GaugeIcon, key: "dashboard" },
      { href: "/capture", label: "现场采集", icon: CameraIcon, key: "capture", internalOnly: true },
      { href: "/search", label: "搜索", icon: MagnifyingGlassIcon, key: "search", internalOnly: true },
      {
        href: "/my-work",
        label: "我的工作",
        icon: ListChecksIcon,
        key: "my-work",
        internalOnly: true,
      },
    ],
  },
  {
    domain: "Portfolio",
    label: "项目组合",
    items: [
      {
        href: "/portfolio",
        label: "组合与阻塞",
        icon: GaugeIcon,
        key: "portfolio",
        internalOnly: true,
      },
    ],
  },
  {
    domain: "Products",
    label: "产品",
    items: [
      { href: "/product-work", label: "产品管理工作台", icon: ClipboardTextIcon, key: "product-work", internalOnly: true },
      { href: "/requirements", label: "需求池", icon: ClipboardTextIcon, key: "requirements" },
      { href: "/cases", label: "开发案例", icon: FolderOpenIcon, key: "cases" },
    ],
  },
  {
    domain: "Projects",
    label: "项目",
    items: [{ href: "/projects", label: "项目工作区", icon: KanbanIcon, key: "projects" }],
  },
  {
    domain: "Engineering",
    label: "工程",
    items: [
      {
        href: "/projects?tab=engineering",
        label: "工程·变更",
        icon: ClipboardTextIcon,
        key: "engineering",
        internalOnly: true,
      },
    ],
  },
  {
    domain: "Quality",
    label: "质量",
    items: [
      {
        href: "/projects?tab=quality",
        label: "试制·测试·质量",
        icon: ListChecksIcon,
        key: "quality",
        internalOnly: true,
      },
    ],
  },
  {
    domain: "Delivery",
    label: "交付",
    items: [
      {
        href: "/projects?tab=gates",
        label: "Gate·交付物",
        icon: FolderOpenIcon,
        key: "delivery",
        internalOnly: true,
      },
      {
        href: "/settings/integrations/dingtalk",
        label: "钉钉集成",
        icon: PlugsConnectedIcon,
        key: "dingtalk-integration",
        internalOnly: true,
      },
      {
        href: "/settings/integrations/tencent-meeting",
        label: "腾讯会议集成",
        icon: PlugsConnectedIcon,
        key: "tencent-meeting-integration",
        internalOnly: true,
      },
    ],
  },
  {
    domain: "Knowledge",
    label: "知识",
    items: [
      {
        href: "/knowledge",
        label: "知识库",
        icon: BookOpenTextIcon,
        key: "knowledge",
        internalOnly: true,
      },
    ],
  },
  {
    domain: "AI Workbench",
    label: "AI 工作台",
    items: [
      { href: "/ask", label: "Ask PDOS", icon: TrayIcon, key: "ask", internalOnly: true },
      { href: "/ai-review", label: "Review 收件箱", icon: TrayIcon, key: "ai-review", internalOnly: true },
      {
        href: "/governance/ai",
        label: "AI 治理",
        icon: PulseIcon,
        key: "ai-governance",
        adminOnly: true,
      },
    ],
  },
  {
    domain: "Admin",
    label: "管理",
    items: [
      { href: "/events", label: "事件流", icon: PulseIcon, key: "events", adminOnly: true },
      {
        href: "/governance/models",
        label: "模型治理",
        icon: GearSixIcon,
        key: "model-governance",
        adminOnly: true,
      },
      {
        href: "/governance/users",
        label: "成员与角色",
        icon: UsersThreeIcon,
        key: "user-management",
        adminOnly: true,
      },
      {
        href: "/governance/organization",
        label: "组织与代理",
        icon: UsersThreeIcon,
        key: "organization",
        adminOnly: true,
      },
      { href: "/settings/security", label: "账户安全", icon: LockKeyIcon, key: "account-security" },
    ],
  },
] as const;

export function WorkspaceShell({
  active,
  children,
  identity,
  loggingOut,
  onLogout,
}: {
  active:
    | "dashboard"
    | "search"
    | "capture"
    | "my-work"
    | "portfolio"
    | "requirements"
    | "cases"
    | "product-work"
    | "projects"
    | "engineering"
    | "quality"
    | "delivery"
    | "knowledge"
    | "ai-review"
    | "ask"
    | "events"
    | "model-governance"
    | "ai-governance"
    | "user-management"
    | "organization"
    | "account-security"
    | "dingtalk-integration"
    | "tencent-meeting-integration";
  children: ReactNode;
  identity: WorkspaceIdentity;
  loggingOut: boolean;
  onLogout: () => void;
}) {
  const [mobileNavigationExpanded, setMobileNavigationExpanded] = useState(false);
  const mobileNavigationToggle = useRef<HTMLButtonElement>(null);
  const isAdmin = ["owner", "admin"].includes(identity.user.role);
  const isExternal = ["supplier", "customer"].includes(identity.user.role);
  const visibleDomains = domains
    .map((group) => ({
      ...group,
      items: group.items.filter(
        (item) =>
          (!("adminOnly" in item) || isAdmin) && (!("internalOnly" in item) || !isExternal),
      ),
    }))
    .filter((group) => group.items.length > 0);
  const visibleNavigation = visibleDomains.flatMap((group) => group.items);
  const currentNavigation = visibleNavigation.find((item) => item.key === active);
  return (
    <div className="min-h-svh bg-background lg:grid lg:grid-cols-[224px_1fr]">
      <a
        className="fixed left-4 top-4 z-50 inline-flex min-h-11 -translate-y-20 items-center rounded-lg bg-primary px-3 py-2 font-medium text-primary-foreground transition-transform focus:translate-y-0"
        href="#main-content"
      >
        跳到主要内容
      </a>
      <aside className="hidden border-r border-sidebar-border bg-sidebar lg:flex lg:flex-col">
        <div className="flex h-14 items-center gap-2 border-b border-sidebar-border px-4">
          <span
            aria-hidden="true"
            className="flex size-6 items-center justify-center rounded-lg bg-primary font-mono text-xs font-bold text-primary-foreground"
          >
            P
          </span>
          <span className="font-semibold tracking-tight">PDOS</span>
        </div>
        <nav aria-label="主导航" className="px-3 py-4">
          {visibleDomains.map((group) => (
          <div className="pb-3" key={group.domain}>
          <p className="px-2 pb-1.5 text-[11px] font-semibold text-muted-foreground">
            {group.label}
          </p>
          <ul className="space-y-1" role="list">
            {group.items.map(({ href, icon: Icon, key, label }) => (
              <li key={key}>
                <Link
                  aria-current={active === key ? "page" : undefined}
                  className={cn(
                    "flex min-h-11 items-center gap-2 rounded-lg px-2.5 text-sm text-sidebar-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-sidebar-ring/30",
                    active === key &&
                      "bg-sidebar-accent font-medium text-sidebar-accent-foreground shadow-[inset_2px_0_0_var(--sidebar-primary)]",
                  )}
                  href={href}
                >
                  <Icon aria-hidden="true" weight="regular" />
                  {label}
                </Link>
              </li>
            ))}
          </ul>
          </div>
          ))}
        </nav>
        <div className="mt-auto border-t border-sidebar-border px-4 py-4">
          <p className="truncate text-xs font-medium text-sidebar-accent-foreground">
            {identity.user.display_name}
          </p>
          <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
            {identity.tenant.name}
          </p>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="flex h-14 items-center gap-4 border-b bg-card px-4 sm:px-6">
          <div className="flex items-center gap-2 lg:hidden">
            <span
              aria-hidden="true"
              className="flex size-6 items-center justify-center rounded-lg bg-primary font-mono text-xs font-bold text-primary-foreground"
            >
              P
            </span>
            <span className="font-semibold">PDOS</span>
          </div>
          <p className="hidden truncate text-xs text-muted-foreground sm:block lg:ml-0">
            {identity.tenant.name} · {identity.user.display_name}
          </p>
          <div className="ml-auto flex items-center gap-1">
            <ThemeToggle />
            <Button
              aria-label="退出登录"
              className="size-11 sm:size-8"
              disabled={loggingOut}
              onClick={onLogout}
              size="icon"
              title="退出登录"
              variant="ghost"
            >
              <SignOutIcon aria-hidden="true" weight="regular" />
            </Button>
          </div>
        </header>
        <nav
          aria-label="移动端主导航"
          className="border-b bg-card px-4 lg:hidden"
          onKeyDown={(event) => {
            if (event.key === "Escape" && mobileNavigationExpanded) {
              event.preventDefault();
              setMobileNavigationExpanded(false);
              mobileNavigationToggle.current?.focus();
            }
          }}
        >
          <div className="flex min-h-11 min-w-0 items-center justify-between gap-2">
            <span aria-current="page" className="min-w-0 truncate text-sm font-medium text-primary">
              {currentNavigation?.label ?? "工作区"}
            </span>
            <button
              aria-controls="mobile-navigation-links"
              aria-expanded={mobileNavigationExpanded}
              className="inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-lg px-2 text-xs font-medium focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/30"
              onClick={() => setMobileNavigationExpanded((expanded) => !expanded)}
              ref={mobileNavigationToggle}
              type="button"
            >
              <ListIcon aria-hidden="true" />
              {mobileNavigationExpanded ? "收起导航" : "展开导航"}
            </button>
          </div>
          <ul
            className={cn("max-h-[60svh] grid-cols-2 overflow-y-auto border-t py-2 sm:grid-cols-4", mobileNavigationExpanded ? "grid" : "hidden")}
            hidden={!mobileNavigationExpanded}
            id="mobile-navigation-links"
            role="list"
          >
            {visibleNavigation.map(({ href, icon: Icon, key, label }) => (
              <li key={key}>
                <Link
                  aria-current={active === key ? "page" : undefined}
                  className={cn(
                    "flex min-h-11 items-center justify-center gap-1.5 rounded-lg px-1 text-xs text-muted-foreground focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/30",
                    active === key && "font-medium text-primary",
                  )}
                  href={href}
                  onClick={() => {
                    setMobileNavigationExpanded(false);
                    mobileNavigationToggle.current?.focus();
                  }}
                >
                  <Icon aria-hidden="true" />
                  {label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6" id="main-content">
          {children}
        </main>
      </div>
    </div>
  );
}
