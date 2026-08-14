import { WarningCircleIcon } from "@phosphor-icons/react/ssr";

import { Button } from "@/components/ui/button";

export function ProductEngineeringLoading() {
  return (
    <div aria-busy="true" aria-label="正在加载产品工程数据" className="space-y-3">
      <div className="h-20 animate-pulse rounded-lg border bg-muted/50" />
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="h-56 animate-pulse rounded-lg border bg-muted/50" />
        <div className="h-56 animate-pulse rounded-lg border bg-muted/50" />
      </div>
    </div>
  );
}

export function ProductEngineeringError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-10 text-center">
      <WarningCircleIcon aria-hidden="true" className="mx-auto size-8 text-destructive" />
      <h3 className="mt-3 font-semibold">产品工程数据暂不可用</h3>
      <p className="mt-1 text-sm text-muted-foreground">读取失败不会被展示为零规格或零 BOM。</p>
      <Button className="mt-4 h-11" onClick={onRetry} variant="outline">
        重新加载产品工程数据
      </Button>
    </div>
  );
}
