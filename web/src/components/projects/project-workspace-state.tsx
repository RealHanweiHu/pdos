import { WarningCircleIcon } from "@phosphor-icons/react/ssr";

import { Button } from "@/components/ui/button";

export function ProjectWorkspaceLoading() {
  return <main className="mx-auto max-w-6xl px-4 py-10 text-sm text-muted-foreground">正在加载项目…</main>;
}

export function ProjectWorkspaceError({ onRetry }: { onRetry: () => void }) {
  return (
    <main className="mx-auto flex min-h-svh max-w-md flex-col items-center justify-center px-6 text-center">
      <WarningCircleIcon aria-hidden="true" className="size-9 text-destructive" />
      <h1 className="mt-3 text-lg font-semibold">项目暂不可用</h1>
      <p className="mt-1 text-sm text-muted-foreground">无法读取项目或身份信息，请检查连接后重试。</p>
      <Button className="mt-4 h-11" onClick={onRetry}>重新加载</Button>
    </main>
  );
}
