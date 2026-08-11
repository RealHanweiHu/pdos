import {
  CheckCircleIcon,
  CirclesFourIcon,
  DatabaseIcon,
  ShieldCheckIcon,
} from "@phosphor-icons/react/ssr";
import Link from "next/link";

import { ThemeToggle } from "@/components/theme-toggle";

const foundations = [
  {
    label: "界面基座",
    detail: "Next.js App Router · Tailwind v4 · shadcn/ui",
    icon: CirclesFourIcon,
  },
  {
    label: "数据边界",
    detail: "PostgreSQL 10 schema · Alembic 单一迁移入口",
    icon: DatabaseIcon,
  },
  {
    label: "AI 治理",
    detail: "Finding 人审 · 服务端真值复核 · 最小权限",
    icon: ShieldCheckIcon,
  },
];

export default function Home() {
  return (
    <div className="min-h-svh bg-background lg:grid lg:grid-cols-[224px_1fr]">
      <a
        className="fixed left-4 top-4 z-50 -translate-y-20 rounded-lg bg-primary px-3 py-2 font-medium text-primary-foreground transition-transform focus:translate-y-0"
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
        <div className="px-3 py-4">
          <p className="px-2 text-[11px] font-semibold text-muted-foreground">
            当前阶段
          </p>
          <div className="mt-2 rounded-lg border border-sidebar-border bg-card px-3 py-3">
            <p className="font-medium">Sprint 0</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Tenant · Auth · RBAC · Database
            </p>
          </div>
        </div>
        <p className="mt-auto px-5 py-4 text-[11px] text-muted-foreground">
          Preview execution baseline
        </p>
      </aside>

      <div className="min-w-0">
        <header className="flex h-14 items-center border-b bg-card px-4 sm:px-6">
          <div className="flex items-center gap-2 lg:hidden">
            <span
              aria-hidden="true"
              className="flex size-6 items-center justify-center rounded-lg bg-primary font-mono text-xs font-bold text-primary-foreground"
            >
              P
            </span>
            <span className="font-semibold">PDOS</span>
          </div>
          <p className="hidden text-xs text-muted-foreground sm:block lg:ml-0">
            AI-native 产品开发操作系统
          </p>
          <div className="ml-auto">
            <div className="flex items-center gap-1">
              <Link
                className="flex h-8 items-center rounded-lg px-2.5 font-medium text-primary hover:bg-accent focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/30"
                href="/login"
              >
                登录
              </Link>
              <ThemeToggle />
            </div>
          </div>
        </header>

        <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6" id="main-content">
          <div className="flex items-center gap-2 text-xs font-medium text-success">
            <CheckCircleIcon aria-hidden="true" weight="fill" />
            工程基线已建立
          </div>
          <h1 className="mt-3 text-xl font-semibold tracking-tight">
            PDOS 基础环境
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            当前页面只验证应用壳、设计 token 与主题能力。业务模块将严格按执行计划逐项接入。
          </p>

          <section aria-labelledby="foundation-title" className="mt-8">
            <div className="border-b pb-2">
              <h2 className="font-semibold" id="foundation-title">
                已冻结的工程约束
              </h2>
            </div>
            <ul className="divide-y" role="list">
              {foundations.map(({ detail, icon: Icon, label }) => (
                <li
                  className="grid gap-2 py-4 sm:grid-cols-[160px_1fr] sm:items-center"
                  key={label}
                >
                  <span className="flex items-center gap-2 font-medium">
                    <Icon
                      aria-hidden="true"
                      className="text-primary"
                      weight="regular"
                    />
                    {label}
                  </span>
                  <span className="text-muted-foreground">{detail}</span>
                </li>
              ))}
            </ul>
          </section>
        </main>
      </div>
    </div>
  );
}
