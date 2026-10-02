"use client";

import {
  BookOpenTextIcon,
  CameraIcon,
  MagnifyingGlassIcon,
  ChatCircleTextIcon,
  ClipboardTextIcon,
  FolderOpenIcon,
  GaugeIcon,
  GearSixIcon,
  KanbanIcon,
  ListIcon,
  ListChecksIcon,
  PackageIcon,
  SignOutIcon,
  SquaresFourIcon,
  TrayIcon,
} from "@phosphor-icons/react";
import Link from "next/link";
import { useRef, useState, type ReactNode } from "react";

import { XiaopaiIdentity } from "@/components/ai/xiaopai-provider";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import type { WorkspaceIdentity } from "@/components/workspace-types";
import { cn } from "@/lib/utils";

/**
 * Global navigation (D31, regrouped 2026-09-28): five groups instead of ten
 * mostly single-entry domains. The sidebar carries only daily destinations;
 * search and field capture are reached from the top bar or source records, and rarely opened governance/integration/account
 * pages sit in the pinned 设置 group above the user card. Project-scoped work
 * (engineering, quality, gates) is reached through the project workspace's own
 * tab bar, not through duplicate sidebar deep-links.
 */
const domains = [
  {
    domain: "Work",
    label: "工作",
    items: [
      {
        href: "/my-work",
        label: "我的工作",
        icon: ListChecksIcon,
        key: "my-work",
        internalOnly: true,
      },
      { href: "/", label: "驾驶舱", icon: GaugeIcon, key: "dashboard" },
    ],
  },
  {
    domain: "Projects",
    label: "项目",
    items: [
      { href: "/projects", label: "项目工作区", icon: KanbanIcon, key: "projects" },
      {
        href: "/portfolio",
        label: "组合与阻塞",
        icon: SquaresFourIcon,
        key: "portfolio",
        internalOnly: true,
      },
    ],
  },
  {
    domain: "Products",
    label: "产品",
    items: [
      {
        href: "/product-work",
        label: "产品管理工作台",
        icon: PackageIcon,
        key: "product-work",
        internalOnly: true,
      },
      { href: "/requirements", label: "需求池", icon: ClipboardTextIcon, key: "requirements" },
      { href: "/cases", label: "开发案例", icon: FolderOpenIcon, key: "cases" },
    ],
  },
  {
    domain: "AI & Knowledge",
    label: "AI 与知识",
    items: [
      { href: "/ask", label: "小Pai", icon: ChatCircleTextIcon, key: "ask", internalOnly: true },
      { href: "/ai-review", label: "Review 收件箱", icon: TrayIcon, key: "ai-review", internalOnly: true },
      {
        href: "/knowledge",
        label: "知识库",
        icon: BookOpenTextIcon,
        key: "knowledge",
        internalOnly: true,
      },
    ],
  },
] as const;

/**
 * One pinned settings entry, Linear-style. The account, integration and
 * governance pages behind it are classified by SettingsNav inside the
 * settings area instead of occupying flat sidebar entries.
 */
const settingsEntry = {
  href: "/settings/security",
  label: "设置",
  icon: GearSixIcon,
  key: "settings",
} as const;

type NavigationItem = (typeof domains)[number]["items"][number];
type NavigationGroup = { domain: string; label: string; items: readonly NavigationItem[] };

// Settings-area pages highlight the single settings entry; field capture and
// global search keep the shell without a sidebar entry to light up.
type WorkspaceView = NavigationItem["key"] | typeof settingsEntry.key | "capture" | "search";

function DomainSection({ active, group }: { active: WorkspaceView; group: NavigationGroup }) {
  return (
    <div className="pb-4">
      <p className="px-2 pb-1 text-[11px] font-medium text-muted-foreground">{group.label}</p>
      <ul className="space-y-0.5" role="list">
        {group.items.map(({ href, icon: Icon, key, label }) => (
          <li key={key}>
            <Link
              aria-current={active === key ? "page" : undefined}
              className={cn(
                "flex min-h-11 items-center gap-2 rounded-md px-2 text-[13px] text-sidebar-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-sidebar-ring/30 lg:min-h-8",
                active === key && "bg-sidebar-accent text-sidebar-accent-foreground",
              )}
              href={href}
            >
              <Icon aria-hidden="true" className="size-4" weight="regular" />
              {label}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function WorkspaceShell({
  active,
  children,
  identity,
  loggingOut,
  onLogout,
}: {
  active: WorkspaceView;
  children: ReactNode;
  identity: WorkspaceIdentity;
  loggingOut: boolean;
  onLogout: () => void;
}) {
  const [mobileNavigationExpanded, setMobileNavigationExpanded] = useState(false);
  const mobileNavigationToggle = useRef<HTMLButtonElement>(null);
  const isAdmin = ["owner", "admin"].includes(identity.user.role);
  const isExternal = ["supplier", "customer"].includes(identity.user.role);
  const visibleDomains: NavigationGroup[] = domains
    .map((group) => ({
      ...group,
      items: group.items.filter(
        (item) =>
          (!("adminOnly" in item) || isAdmin) && (!("internalOnly" in item) || !isExternal),
      ),
    }))
    .filter((group) => group.items.length > 0);
  const visibleNavigation = [...visibleDomains.flatMap((group) => group.items), settingsEntry];
  const currentNavigation = visibleNavigation.find((item) => item.key === active);
  return (
    <div className="min-h-svh bg-background lg:grid lg:grid-cols-[224px_1fr]">
      <XiaopaiIdentity identity={identity} />
      <a
        className="fixed left-4 top-4 z-50 inline-flex min-h-11 -translate-y-20 items-center rounded-lg bg-primary px-3 py-2 font-medium text-primary-foreground transition-transform focus:translate-y-0"
        href="#main-content"
      >
        跳到主要内容
      </a>
      <aside className="hidden border-r border-sidebar-border bg-sidebar lg:sticky lg:top-0 lg:flex lg:h-svh lg:flex-col">
        <div className="flex h-12 items-center gap-2 border-b border-sidebar-border px-4">
          <span
            aria-hidden="true"
            className="flex size-6 items-center justify-center rounded-lg bg-primary font-mono text-xs font-bold text-primary-foreground"
          >
            P
          </span>
          <span className="font-semibold tracking-tight">PDOS</span>
        </div>
        <nav aria-label="主导航" className="min-h-0 flex-1 overflow-y-auto px-2.5 py-3">
          {visibleDomains.map((group) => (
            <DomainSection active={active} group={group} key={group.domain} />
          ))}
        </nav>
        <div className="border-t border-sidebar-border px-2.5 py-2">
          <Link
            aria-current={active === settingsEntry.key ? "page" : undefined}
            className={cn(
              "flex min-h-11 items-center gap-2 rounded-md px-2 text-[13px] text-sidebar-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-sidebar-ring/30 lg:min-h-8",
              active === settingsEntry.key && "bg-sidebar-accent text-sidebar-accent-foreground",
            )}
            href={settingsEntry.href}
          >
            <GearSixIcon aria-hidden="true" className="size-4" weight="regular" />
            {settingsEntry.label}
          </Link>
        </div>
        <div className="border-t border-sidebar-border px-4 py-3">
          <p className="truncate text-xs font-medium text-sidebar-accent-foreground">
            {identity.user.display_name}
          </p>
          <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
            {identity.tenant.name}
          </p>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="flex h-12 items-center gap-4 border-b bg-background px-4 sm:px-6">
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
            {!isExternal && <>
              <Link aria-current={active === "search" ? "page" : undefined} aria-label="搜索" title="搜索" href="/search" className="flex size-11 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/30 sm:size-8">
                <MagnifyingGlassIcon aria-hidden="true" className="size-4" />
              </Link>
              <Link aria-current={active === "capture" ? "page" : undefined} aria-label="现场采集" title="现场采集" href="/capture" className="flex size-11 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/30 sm:size-8">
                <CameraIcon aria-hidden="true" className="size-4" />
              </Link>
            </>}
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
          className="border-b bg-background px-4 lg:hidden"
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
