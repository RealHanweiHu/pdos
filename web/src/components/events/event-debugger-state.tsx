import { LockKeyIcon, WarningCircleIcon } from "@phosphor-icons/react/ssr";

import { Button } from "@/components/ui/button";
import { WorkspaceShell } from "@/components/workspace-shell";
import type { WorkspaceIdentity } from "@/components/workspace-types";

export function EventDebuggerLoading() {
  return (
    <main className="mx-auto max-w-6xl px-4 py-10 text-sm text-muted-foreground">
      正在读取事件流…
    </main>
  );
}

export function EventDebuggerError({ onRetry }: { onRetry: () => void }) {
  return (
    <main className="mx-auto flex min-h-svh max-w-md flex-col items-center justify-center px-6 text-center">
      <WarningCircleIcon aria-hidden="true" className="size-9 text-destructive" />
      <h1 className="mt-3 text-lg font-semibold">事件流暂不可用</h1>
      <p className="mt-1 text-sm text-muted-foreground">无法读取 catalog 或事件数据，请检查连接后重试。</p>
      <Button className="mt-4 h-11" onClick={onRetry}>重新加载</Button>
    </main>
  );
}

export function EventDebuggerForbidden({
  identity,
  loggingOut,
  onLogout,
}: {
  identity: WorkspaceIdentity;
  loggingOut: boolean;
  onLogout: () => void;
}) {
  return (
    <WorkspaceShell active="events" identity={identity} loggingOut={loggingOut} onLogout={onLogout}>
      <section className="mx-auto max-w-lg rounded-lg border bg-card p-6 text-center">
        <LockKeyIcon aria-hidden="true" className="mx-auto size-9 text-muted-foreground" />
        <h1 className="mt-3 text-lg font-semibold">仅管理员可访问</h1>
        <p className="mt-1 text-sm text-muted-foreground">事件流包含租户级调试信息，仅 Owner 与 Admin 开放。</p>
      </section>
    </WorkspaceShell>
  );
}
