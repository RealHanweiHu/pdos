import {
  FlowArrowIcon,
  ShieldCheckIcon,
  StackIcon,
} from "@phosphor-icons/react";
import type { ReactNode } from "react";

import { ThemeToggle } from "@/components/theme-toggle";

const boundaries = [
  {
    icon: StackIcon,
    title: "租户边界",
    detail: "身份与项目范围由服务端解析，客户端不提交租户政策事实。",
  },
  {
    icon: ShieldCheckIcon,
    title: "最小权限",
    detail: "七角色矩阵默认拒绝，外部成员只见被授权项目。",
  },
  {
    icon: FlowArrowIcon,
    title: "事件留痕",
    detail: "业务写、事件与不可变审计在同一事务中提交。",
  },
];

export function AuthFrame({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-svh bg-background">
      <a
        className="fixed left-4 top-4 z-50 -translate-y-20 rounded-lg bg-primary px-3 py-2 font-medium text-primary-foreground transition-transform focus:translate-y-0"
        href="#auth-content"
      >
        跳到身份验证
      </a>
      <header className="flex h-14 items-center border-b bg-card px-4 sm:px-6">
        <div className="flex items-center gap-2">
          <span
            aria-hidden="true"
            className="flex size-6 items-center justify-center rounded-lg bg-primary font-mono text-xs font-bold text-primary-foreground"
          >
            P
          </span>
          <span className="font-semibold tracking-tight">PDOS</span>
          <span className="hidden text-xs text-muted-foreground sm:inline">
            产品开发操作系统
          </span>
        </div>
        <div className="ml-auto">
          <ThemeToggle />
        </div>
      </header>

      <main
        className="grid min-h-[calc(100svh-3.5rem)] lg:grid-cols-[minmax(0,1fr)_480px]"
        id="auth-content"
      >
        <section className="bg-card px-4 py-8 sm:px-8 lg:order-2 lg:border-l lg:py-16">
          <div className="mx-auto w-full max-w-sm">{children}</div>
        </section>

        <section
          aria-labelledby="auth-context-title"
          className="border-t px-4 py-8 sm:px-8 lg:order-1 lg:border-t-0 lg:px-12 lg:py-16"
        >
          <div className="mx-auto max-w-xl lg:mx-0">
            <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-primary">
              Sprint 0 · Governance boundary
            </p>
            <h2
              className="mt-3 text-lg font-semibold tracking-tight"
              id="auth-context-title"
            >
              先确认身份，再进入产品开发现场
            </h2>
            <p className="mt-2 max-w-lg text-sm leading-6 text-muted-foreground">
              PDOS 将需求、项目、质量记录与 AI finding 装配在同一审计链中。登录入口只负责建立可信的租户与用户上下文。
            </p>
            <ul className="mt-8 divide-y border-y" role="list">
              {boundaries.map(({ detail, icon: Icon, title }) => (
                <li className="grid gap-2 py-4 sm:grid-cols-[152px_1fr]" key={title}>
                  <span className="flex items-center gap-2 font-medium">
                    <Icon aria-hidden="true" className="text-primary" weight="regular" />
                    {title}
                  </span>
                  <span className="text-muted-foreground">{detail}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>
      </main>
    </div>
  );
}
