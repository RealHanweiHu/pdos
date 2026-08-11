import { WarningCircleIcon } from "@phosphor-icons/react";

import { Button } from "@/components/ui/button";

export function RequirementPoolLoading() {
  return (
    <main
      aria-busy="true"
      aria-label="正在加载需求池"
      className="mx-auto min-h-svh max-w-5xl space-y-4 px-4 py-8 sm:px-6"
    >
      <div className="h-5 w-28 animate-pulse rounded-lg bg-muted" />
      <div className="h-10 w-full animate-pulse rounded-lg bg-muted" />
      <div className="h-48 w-full animate-pulse rounded-lg bg-muted" />
    </main>
  );
}

export function RequirementPoolError({ onRetry }: { onRetry: () => void }) {
  return (
    <main className="mx-auto flex min-h-svh max-w-lg items-center px-4 py-12">
      <section className="w-full rounded-lg border bg-card p-6 text-center">
        <WarningCircleIcon
          aria-hidden="true"
          className="mx-auto size-8 text-destructive"
          weight="regular"
        />
        <h1 className="mt-3 text-lg font-semibold">需求池暂不可用</h1>
        <p className="mt-2 text-sm text-muted-foreground" role="alert">
          未能读取需求数据。请检查服务状态后重试。
        </p>
        <Button className="mt-5 h-11 sm:h-8" onClick={onRetry}>
          重新加载
        </Button>
      </section>
    </main>
  );
}
