"use client";

import {
  BookOpenTextIcon,
  CaretRightIcon,
  CameraIcon,
  MagnifyingGlassIcon,
  ChatCircleTextIcon,
  ClipboardTextIcon,
  FolderOpenIcon,
  GaugeIcon,
  HouseIcon,
  GearSixIcon,
  KanbanIcon,
  ListIcon,
  ListChecksIcon,
  PackageIcon,
  SidebarSimpleIcon,
  SignOutIcon,
  SquaresFourIcon,
  TrayIcon,
} from "@phosphor-icons/react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useRef, useState, type ReactNode } from "react";

import { XiaopaiIdentity } from "@/components/ai/xiaopai-provider";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import type { WorkspaceIdentity } from "@/components/workspace-types";
import { useCollapsedNavigation } from "@/components/workspace-preferences";
import { useWorkPerspective } from "@/components/workspace-experience";
import { cn } from "@/lib/utils";

/**
 * Scenario navigation: the verified account role orders daily routes;
 * account permissions still determine the available destinations. The sidebar carries only daily destinations;
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
      { href: "/dashboard", label: "项目快照", icon: GaugeIcon, key: "dashboard", internalOnly: true },
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
      { href: "/requirements", label: "需求池", icon: ClipboardTextIcon, key: "requirements", internalOnly: true },
      { href: "/cases", label: "开发案例", icon: FolderOpenIcon, key: "cases", internalOnly: true },
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

const governanceNavigation = [
  { href: "/governance/users", label: "成员与角色", icon: GearSixIcon, key: "settings" },
  { href: "/governance/organization", label: "组织与流程", icon: GearSixIcon, key: "settings" },
  { href: "/governance/models", label: "模型可用性", icon: GearSixIcon, key: "settings" },
  { href: "/governance/ai", label: "AI 治理", icon: GearSixIcon, key: "settings" },
  { href: "/events", label: "运行与事件", icon: GearSixIcon, key: "settings" },
] as const;
type NavigationItem = (typeof domains)[number]["items"][number] | (typeof governanceNavigation)[number];
type NavigationGroup = { domain: string; label: string; items: readonly NavigationItem[] };

// Settings-area pages highlight the single settings entry; field capture and
// global search keep the shell without a sidebar entry to light up.
type WorkspaceView = NavigationItem["key"] | typeof settingsEntry.key | "capture" | "search";

function DomainSection({ active, collapsed, group, pathname }: { active: WorkspaceView; collapsed: boolean; group: NavigationGroup; pathname: string }) {
  return (
    <div className="pb-4">
      <p className={cn("px-2 pb-1 text-[11px] font-medium text-muted-foreground", collapsed && "sr-only")}>{group.label}</p>
      <ul className="space-y-0.5" role="list">
        {group.items.map(({ href, icon: Icon, key, label }) => (
          <li key={href}>
            <Link
              aria-current={(key === "settings" ? pathname === href : active === key) ? "page" : undefined}
              className={cn(
                "flex min-h-11 items-center gap-2 rounded-md px-2 text-[13px] text-sidebar-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-sidebar-ring/30 lg:min-h-8",
                (key === "settings" ? pathname === href : active === key) && "bg-sidebar-accent text-sidebar-accent-foreground",
                collapsed && "justify-center px-0",
              )}
              href={href}
              title={collapsed ? label : undefined}
            >
              <Icon aria-hidden="true" className="size-4 shrink-0" weight="regular" />
              <span className={collapsed ? "sr-only" : "truncate"}>{label}</span>
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
  const [collapsed, toggleCollapsed] = useCollapsedNavigation();
  const pathname = usePathname();
  const { available } = useWorkPerspective(identity);
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
  const permittedItems: NavigationItem[] = [...visibleDomains.flatMap(group => group.items), ...(isAdmin ? governanceNavigation : [])];
  const priorityRoutes = [...new Set(available.flatMap(module => [...module.priorityRoutes]))];
  const priorityItems = priorityRoutes.flatMap(href => permittedItems.filter(item => item.href === href));
  const secondaryDomains = visibleDomains.map(group => ({ ...group, items: group.items.filter(item => !priorityItems.some(primary => primary.href === item.href)) })).filter(group => group.items.length);
  const visibleNavigation = [...priorityItems, ...secondaryDomains.flatMap(group => group.items), settingsEntry];
  const currentNavigation = [...(domains as readonly NavigationGroup[]).flatMap((group) => group.items), settingsEntry].find((item) => item.key === active);
  const currentLabel = currentNavigation?.label ?? (active === "search" ? "搜索" : active === "capture" ? "现场采集" : "工作区");
  const currentGroup = domains.find((group) => group.items.some((item) => item.key === active));
  return (
    <div className={cn("workspace-shell min-h-svh bg-background lg:grid", collapsed ? "lg:grid-cols-[56px_minmax(0,1fr)]" : "lg:grid-cols-[224px_minmax(0,1fr)]")} data-navigation-collapsed={collapsed}>
      <XiaopaiIdentity identity={identity} />
      <a
        className="fixed left-4 top-4 z-50 inline-flex min-h-11 -translate-y-20 items-center rounded-lg bg-primary px-3 py-2 font-medium text-primary-foreground transition-transform focus:translate-y-0"
        href="#main-content"
      >
        跳到主要内容
      </a>
      <aside className="hidden border-r border-sidebar-border bg-sidebar lg:sticky lg:top-0 lg:flex lg:h-svh lg:flex-col">
        <div className={cn("flex h-12 shrink-0 items-center gap-2 border-b border-sidebar-border", collapsed ? "justify-center px-2" : "px-4")}>
          <Link aria-label="PDOS 工作区" href={isExternal ? "/projects" : "/"} className="flex min-h-8 min-w-8 items-center gap-2 rounded-lg focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-sidebar-ring/30">
          <span
            aria-hidden="true"
            className="flex size-6 items-center justify-center rounded-lg bg-primary font-mono text-xs font-bold text-primary-foreground"
          >
            P
          </span>
          <span className={cn("font-semibold tracking-tight", collapsed && "sr-only")}>PDOS</span>
          </Link>
        </div>
        <nav aria-label="主导航" className="min-h-0 flex-1 overflow-y-auto px-2.5 py-3">
          {!isExternal && <Link aria-label="工作首页" className={cn("mb-3 flex min-h-11 items-center gap-2 rounded-lg px-2 text-[13px] font-medium hover:bg-sidebar-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring lg:min-h-8", collapsed && "justify-center px-0")} href="/" title="工作首页"><HouseIcon aria-hidden className="size-4"/><span className={collapsed ? "sr-only" : undefined}>工作首页</span></Link>}
          {priorityItems.length > 0 && <DomainSection active={active} collapsed={collapsed} group={{ domain: "current-work", label: "常用工作", items: priorityItems }} pathname={pathname}/>}
          <details className="group/navigation" open={collapsed || secondaryDomains.some(group => group.items.some(item => item.key === active))}>
            <summary className={cn("mb-2 flex min-h-8 cursor-pointer items-center gap-2 rounded-lg px-2 text-[11px] font-medium text-muted-foreground hover:bg-sidebar-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring", collapsed && "sr-only")}><CaretRightIcon aria-hidden className="size-3 transition-transform group-open/navigation:rotate-90"/>其他工作入口</summary>
            {secondaryDomains.map(group => <DomainSection active={active} collapsed={collapsed} group={group} key={group.domain} pathname={pathname}/>)}
          </details>
        </nav>
        <div className="border-t border-sidebar-border px-2.5 py-2">
          <Link
            aria-current={active === settingsEntry.key ? "page" : undefined}
            className={cn(
              "flex min-h-11 items-center gap-2 rounded-md px-2 text-[13px] text-sidebar-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-sidebar-ring/30 lg:min-h-8",
              active === settingsEntry.key && "bg-sidebar-accent text-sidebar-accent-foreground",
              collapsed && "justify-center px-0",
            )}
            href={settingsEntry.href}
            title={collapsed ? "设置" : undefined}
          >
            <GearSixIcon aria-hidden="true" className="size-4" weight="regular" />
            <span className={collapsed ? "sr-only" : undefined}>{settingsEntry.label}</span>
          </Link>
        </div>
        <div className={cn("border-t border-sidebar-border", collapsed ? "px-2 py-3" : "px-4 py-3")}>
          <Link aria-label={`${identity.user.display_name} · 账户安全`} href="/settings/security" title={`${identity.user.display_name} · ${identity.tenant.name}`} className="flex min-w-0 items-center gap-2 rounded-lg focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-sidebar-ring/30">
          <span aria-hidden="true" className="flex size-7 shrink-0 items-center justify-center rounded-lg border bg-sidebar-accent text-xs font-medium">{identity.user.display_name.trim().slice(0, 1) || "P"}</span>
          <div className={collapsed ? "sr-only" : "min-w-0"}>
          <p className="truncate text-xs font-medium text-sidebar-accent-foreground">
            {identity.user.display_name}
          </p>
          <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
            {identity.tenant.name}
          </p>
          </div>
          </Link>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-30 flex h-12 items-center gap-2 border-b bg-background px-3 sm:gap-3 sm:px-6">
          <Button aria-label={collapsed ? "展开侧栏" : "收起侧栏"} aria-expanded={!collapsed} className="hidden lg:inline-flex" onClick={toggleCollapsed} size="icon" title={collapsed ? "展开侧栏" : "收起侧栏"} variant="ghost"><SidebarSimpleIcon aria-hidden="true" className="size-4" /></Button>
          <div className="flex items-center gap-2 lg:hidden">
            <span
              aria-hidden="true"
              className="flex size-6 items-center justify-center rounded-lg bg-primary font-mono text-xs font-bold text-primary-foreground"
            >
              P
            </span>
            <span className="font-semibold">PDOS</span>
          </div>
          <nav aria-label="当前位置" className="hidden min-w-0 items-center gap-2 text-xs lg:flex">
            <span className="max-w-40 truncate text-muted-foreground" title={identity.tenant.name}>{identity.tenant.name}</span>
            <CaretRightIcon aria-hidden="true" className="size-3 shrink-0 text-muted-foreground" />
            {currentGroup && <><span className="shrink-0 text-muted-foreground">{currentGroup.label}</span><CaretRightIcon aria-hidden="true" className="size-3 shrink-0 text-muted-foreground" /></>}
            <span className="truncate font-medium" aria-current="page">{currentLabel}</span>
          </nav>
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
              {currentLabel}
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
          {available.length > 0 && <div className={cn("border-t py-2", !mobileNavigationExpanded && "hidden")}><Link className="inline-flex min-h-11 items-center gap-2 text-sm text-primary" href="/" onClick={() => setMobileNavigationExpanded(false)}><HouseIcon aria-hidden className="size-4"/>工作首页</Link></div>}
          <ul
            className={cn("max-h-[60svh] grid-cols-2 overflow-y-auto border-t py-2 sm:grid-cols-4", mobileNavigationExpanded ? "grid" : "hidden")}
            hidden={!mobileNavigationExpanded}
            id="mobile-navigation-links"
            role="list"
          >
            {visibleNavigation.map(({ href, icon: Icon, key, label }) => (
              <li key={href}>
                <Link
                  aria-current={(key === "settings" ? pathname === href : active === key) ? "page" : undefined}
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
        <main className={cn("workspace-content mx-auto w-full min-w-0 px-4 py-6 sm:px-6 xl:px-8", active === "settings" ? "max-w-6xl" : "max-w-[1920px]")} id="main-content" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  );
}
