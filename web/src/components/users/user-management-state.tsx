import { LockKeyIcon, WarningCircleIcon } from "@phosphor-icons/react/ssr";

import { Button } from "@/components/ui/button";
import { WorkspaceShell } from "@/components/workspace-shell";
import type { WorkspaceIdentity } from "@/components/workspace-types";

export function UserManagementLoading() {
  return (
    <main className="mx-auto max-w-6xl px-4 py-10 text-sm text-muted-foreground">
      正在读取成员账户…
    </main>
  );
}

export function UserManagementError({ onRetry }: { onRetry: () => void }) {
  return (
    <main className="mx-auto flex min-h-svh max-w-md flex-col items-center justify-center px-6 text-center">
      <WarningCircleIcon aria-hidden="true" className="size-9 text-destructive" />
      <h1 className="mt-3 text-lg font-semibold">无法读取成员账户</h1>
      <p className="mt-1 text-sm text-muted-foreground">账户服务暂不可用，请检查连接后重试。</p>
      <Button className="mt-4 h-11" onClick={onRetry}>重试</Button>
    </main>
  );
}

export function UserManagementForbidden({
  identity,
  loggingOut,
  onLogout,
}: {
  identity: WorkspaceIdentity;
  loggingOut: boolean;
  onLogout: () => void;
}) {
  return (
    <WorkspaceShell
      active="user-management"
      identity={identity}
      loggingOut={loggingOut}
      onLogout={onLogout}
    >
      <section className="mx-auto max-w-lg rounded-lg border bg-card p-6 text-center">
        <LockKeyIcon aria-hidden="true" className="mx-auto size-9 text-muted-foreground" />
        <h1 className="mt-3 text-lg font-semibold">仅管理员可访问</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          租户成员和角色仅向 Owner 与 Admin 开放。
        </p>
      </section>
    </WorkspaceShell>
  );
}
