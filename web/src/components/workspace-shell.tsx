"use client";

import {
  BookOpenTextIcon,
  ClipboardTextIcon,
  FolderOpenIcon,
  GaugeIcon,
  GearSixIcon,
  KanbanIcon,
  PulseIcon,
  PlugsConnectedIcon,
  SignOutIcon,
  TrayIcon,
} from "@phosphor-icons/react";
import Link from "next/link";
import type { ReactNode } from "react";

import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import type { WorkspaceIdentity } from "@/components/workspace-types";
import { cn } from "@/lib/utils";

const navigation = [
  { href: "/", label: "驾驶舱", icon: GaugeIcon, key: "dashboard" },
  { href: "/requirements", label: "需求池", icon: ClipboardTextIcon, key: "requirements" },
  { href: "/cases", label: "开发案例", icon: FolderOpenIcon, key: "cases" },
  { href: "/projects", label: "项目", icon: KanbanIcon, key: "projects" },
  {
    href: "/knowledge",
    label: "知识库",
    icon: BookOpenTextIcon,
    key: "knowledge",
    internalOnly: true,
  },
  {
    href: "/ai-review",
    label: "AI Review",
    icon: TrayIcon,
    key: "ai-review",
    internalOnly: true,
  },
  { href: "/events", label: "事件流", icon: PulseIcon, key: "events", adminOnly: true },
  {
    href: "/governance/models",
    label: "模型治理",
    icon: GearSixIcon,
    key: "model-governance",
    adminOnly: true,
  },
  {
    href: "/settings/integrations/dingtalk",
    label: "钉钉集成",
    icon: PlugsConnectedIcon,
    key: "dingtalk-integration",
    internalOnly: true,
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
    | "requirements"
    | "cases"
    | "projects"
    | "knowledge"
    | "ai-review"
    | "events"
    | "model-governance"
    | "dingtalk-integration";
  children: ReactNode;
  identity: WorkspaceIdentity;
  loggingOut: boolean;
  onLogout: () => void;
}) {
  const visibleNavigation = navigation.filter(
    (item) =>
      (!("adminOnly" in item) || ["owner", "admin"].includes(identity.user.role)) &&
      (!("internalOnly" in item) || !["supplier", "customer"].includes(identity.user.role)),
  );
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
          <p className="px-2 pb-2 text-[11px] font-semibold text-muted-foreground">
            工作区
          </p>
          <ul className="space-y-1" role="list">
            {visibleNavigation.map(({ href, icon: Icon, key, label }) => (
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
        <nav aria-label="移动端主导航" className="border-b bg-card px-2 lg:hidden">
          <ul
            className={cn(
              "grid",
              visibleNavigation.length >= 6 ? "grid-cols-4 sm:grid-cols-7" : "grid-cols-4",
            )}
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
