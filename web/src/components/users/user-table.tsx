import { KeyIcon } from "@phosphor-icons/react/ssr";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import type { WorkspaceIdentity } from "@/components/workspace-types";

import { ROLE_LABELS, USER_ROLES } from "./user-management-types";
import type { ManagedUser, UserRole, UserUpdate } from "./user-management-types";

const ADMIN_ROLES: readonly UserRole[] = ["owner", "admin"];
const NON_PRIVILEGED_ROLES = USER_ROLES.filter((role) => !ADMIN_ROLES.includes(role));

function canManage(identity: WorkspaceIdentity, user: ManagedUser) {
  if (identity.user.id === user.id) return false;
  return identity.user.role === "owner" || !ADMIN_ROLES.includes(user.role);
}

function formatLastSignIn(value: string | null) {
  if (value === null) return "尚未登录";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(value));
}

export function UserTable({
  busyUserId,
  identity,
  onResetPassword,
  onUpdate,
  users,
}: {
  busyUserId: string | null;
  identity: WorkspaceIdentity;
  onResetPassword: (user: ManagedUser, password: string) => Promise<boolean>;
  onUpdate: (user: ManagedUser, changes: UserUpdate) => Promise<void>;
  users: ManagedUser[];
}) {
  const [resetUserId, setResetUserId] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const assignableRoles = identity.user.role === "owner" ? USER_ROLES : NON_PRIVILEGED_ROLES;

  return (
    <section className="rounded-lg border bg-card" aria-labelledby="account-list-title">
      <div className="flex items-center justify-between gap-3 border-b px-5 py-4">
        <div>
          <h2 className="font-medium" id="account-list-title">租户账户</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">{users.length} 个账户</p>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-left text-sm">
          <thead className="bg-muted/45 text-xs text-muted-foreground">
            <tr>
              <th className="px-5 py-3 font-medium" scope="col">成员</th>
              <th className="px-3 py-3 font-medium" scope="col">角色</th>
              <th className="px-3 py-3 font-medium" scope="col">状态</th>
              <th className="px-3 py-3 font-medium" scope="col">最近登录</th>
              <th className="px-5 py-3 text-right font-medium" scope="col">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {users.map((user) => {
              const manageable = canManage(identity, user);
              const busy = busyUserId === user.id;
              const resetting = resetUserId === user.id;
              return (
                <tr key={user.id}>
                  <td className="px-5 py-4 align-top">
                    <p className="font-medium">{user.display_name}</p>
                    <p className="mt-0.5 font-mono text-xs text-muted-foreground">{user.username}</p>
                    {user.email ? <p className="mt-0.5 text-xs text-muted-foreground">{user.email}</p> : null}
                  </td>
                  <td className="px-3 py-4 align-top">
                    {manageable ? (
                      <label className="sr-only" htmlFor={`role-${user.id}`}>{user.username} 的角色</label>
                    ) : null}
                    {manageable ? (
                      <select
                        aria-label={`${user.username} 的角色`}
                        className="h-9 rounded-lg border bg-background px-2 text-xs"
                        disabled={busy}
                        id={`role-${user.id}`}
                        onChange={(event) => void onUpdate(user, { role: event.target.value as UserRole })}
                        value={user.role}
                      >
                        {assignableRoles.map((role) => <option key={role} value={role}>{ROLE_LABELS[role]}</option>)}
                      </select>
                    ) : (
                      <span className="text-xs font-medium">{ROLE_LABELS[user.role]}</span>
                    )}
                  </td>
                  <td className="px-3 py-4 align-top">
                    <span className={user.is_active ? "text-emerald-700 dark:text-emerald-400" : "text-muted-foreground"}>
                      {user.is_active ? "启用" : "停用"}
                    </span>
                  </td>
                  <td className="px-3 py-4 align-top text-xs text-muted-foreground">
                    {formatLastSignIn(user.last_signed_in_at)}
                  </td>
                  <td className="px-5 py-4 align-top">
                    {manageable ? (
                      <div className="flex justify-end gap-2">
                        <Button
                          className="h-9"
                          disabled={busy}
                          onClick={() => void onUpdate(user, { is_active: !user.is_active })}
                          size="sm"
                          variant="outline"
                        >
                          {user.is_active ? `停用 ${user.username}` : `启用 ${user.username}`}
                        </Button>
                        <Button
                          aria-label={`重置 ${user.username} 密码`}
                          className="size-9"
                          disabled={busy}
                          onClick={() => {
                            setResetUserId(user.id);
                            setPassword("");
                          }}
                          size="icon"
                          title={`重置 ${user.username} 密码`}
                          variant="ghost"
                        >
                          <KeyIcon aria-hidden="true" />
                        </Button>
                      </div>
                    ) : <span className="block text-right text-xs text-muted-foreground">不可自助变更</span>}
                    {resetting ? (
                      <form
                        className="mt-3 ml-auto grid max-w-xs gap-2 rounded-lg border bg-background p-3"
                        onSubmit={(event) => {
                          event.preventDefault();
                          void onResetPassword(user, password).then((succeeded) => {
                            if (succeeded) setPassword("");
                          });
                        }}
                      >
                        <input
                          autoComplete="username"
                          name="username"
                          type="hidden"
                          value={user.username}
                        />
                        <label className="grid gap-1 text-xs font-medium">
                          {user.username} 的新密码
                          <input
                            autoComplete="new-password"
                            className="h-10 rounded-lg border bg-background px-3 text-sm"
                            minLength={12}
                            onChange={(event) => setPassword(event.target.value)}
                            required
                            type="password"
                            value={password}
                          />
                        </label>
                        <div className="flex justify-end gap-2">
                          <Button className="h-9" onClick={() => setResetUserId(null)} size="sm" type="button" variant="ghost">取消</Button>
                          <Button className="h-9" disabled={busy} size="sm" type="submit">确认重置密码</Button>
                        </div>
                      </form>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
