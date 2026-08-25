import { CheckCircleIcon, WarningCircleIcon } from "@phosphor-icons/react/ssr";

import { WorkspaceShell } from "@/components/workspace-shell";
import type { WorkspaceIdentity } from "@/components/workspace-types";

import { UserCreateForm } from "./user-create-form";
import { UserTable } from "./user-table";
import { USER_ROLES } from "./user-management-types";
import type { ManagedUser, UserCreate, UserRole, UserUpdate } from "./user-management-types";

const ADMIN_ASSIGNABLE_ROLES: readonly UserRole[] = [
  "project_manager",
  "engineer",
  "quality",
  "supplier",
  "customer",
];

export function UserManagementView({
  actionError,
  busyUserId,
  creating,
  identity,
  loggingOut,
  notice,
  onCreate,
  onLogout,
  onResetPassword,
  onUpdate,
  users,
}: {
  actionError: string | null;
  busyUserId: string | null;
  creating: boolean;
  identity: WorkspaceIdentity;
  loggingOut: boolean;
  notice: string | null;
  onCreate: (payload: UserCreate) => Promise<boolean>;
  onLogout: () => void;
  onResetPassword: (user: ManagedUser, password: string) => Promise<boolean>;
  onUpdate: (user: ManagedUser, changes: UserUpdate) => Promise<void>;
  users: ManagedUser[];
}) {
  return (
    <WorkspaceShell
      active="user-management"
      identity={identity}
      loggingOut={loggingOut}
      onLogout={onLogout}
    >
      <div className="border-b pb-4">
        <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-primary">
          Governance
        </p>
        <h1 className="mt-1 text-lg font-semibold">成员与角色</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          创建租户账户、分配角色并管理登录状态。密码不会回显或保留在页面中。
        </p>
      </div>

      {notice ? (
        <p className="mt-4 flex items-center gap-2 rounded-lg border border-emerald-600/25 bg-emerald-600/10 px-3 py-2 text-sm text-emerald-800 dark:text-emerald-300" role="status">
          <CheckCircleIcon aria-hidden="true" />{notice}
        </p>
      ) : null}
      {actionError ? (
        <p className="mt-4 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
          <WarningCircleIcon aria-hidden="true" />{actionError}
        </p>
      ) : null}

      <div className="mt-5 grid items-start gap-5 xl:grid-cols-[minmax(300px,0.72fr)_minmax(0,1.5fr)]">
        <UserCreateForm
          creating={creating}
          onCreate={onCreate}
          roles={identity.user.role === "owner" ? USER_ROLES : ADMIN_ASSIGNABLE_ROLES}
        />
        <UserTable
          busyUserId={busyUserId}
          identity={identity}
          onResetPassword={onResetPassword}
          onUpdate={onUpdate}
          users={users}
        />
      </div>
    </WorkspaceShell>
  );
}
