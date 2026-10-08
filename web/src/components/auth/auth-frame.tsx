import {
  FlowArrowIcon,
  ListChecksIcon,
  PackageIcon,
} from "@phosphor-icons/react";
import type { ReactNode } from "react";

import { ThemeToggle } from "@/components/theme-toggle";

const workAreas = [
  {
    icon: PackageIcon,
    title: "研究与产品定义",
    detail: "从品类进入提案，复用研究、竞品和产品规格。",
  },
  {
    icon: ListChecksIcon,
    title: "项目与日常工作",
    detail: "查看自己的待办，在项目中推进阶段、计划和专业事项。",
  },
  {
    icon: FlowArrowIcon,
    title: "评审与交付",
    detail: "汇集资料和验证依据，办理评审、签核与交付。",
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
        className="mx-auto grid min-h-[calc(100svh-3.5rem)] max-w-6xl items-center gap-12 px-4 py-10 sm:px-8 lg:grid-cols-[minmax(0,1fr)_400px] lg:gap-20 lg:py-16"
        id="auth-content"
      >
        <section className="rounded-lg border bg-card px-5 py-8 sm:px-8 lg:order-2">
          <div className="mx-auto w-full max-w-sm">{children}</div>
        </section>

        <section
          aria-labelledby="auth-context-title"
          className="hidden lg:order-1 lg:block"
        >
          <div className="mx-auto max-w-xl lg:mx-0">
            <h2
              className="text-2xl font-semibold tracking-tight"
              id="auth-context-title"
            >
              让产品开发的下一步更清楚
            </h2>
            <p className="mt-2 max-w-lg text-sm leading-6 text-muted-foreground">
              从研究到项目交付，在同一个工作区查看当前事项、办理动作和结果依据。
            </p>
            <ul className="mt-8 divide-y border-y" role="list">
              {workAreas.map(({ detail, icon: Icon, title }) => (
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
