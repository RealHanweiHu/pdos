import { UserPlusIcon } from "@phosphor-icons/react/ssr";
import { type FormEvent } from "react";

import { Button } from "@/components/ui/button";

import { ROLE_LABELS } from "./user-management-types";
import type { UserCreate, UserRole } from "./user-management-types";

export function UserCreateForm({
  creating,
  onCreate,
  roles,
}: {
  creating: boolean;
  onCreate: (payload: UserCreate) => Promise<boolean>;
  roles: readonly UserRole[];
}) {
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const email = String(form.get("email") ?? "").trim();
    const created = await onCreate({
      username: String(form.get("username") ?? "").trim(),
      display_name: String(form.get("display_name") ?? "").trim(),
      email: email || null,
      role: String(form.get("role")) as UserRole,
      password: String(form.get("password") ?? ""),
    });
    if (created) formElement.reset();
  }

  return (
    <form className="rounded-lg border bg-card p-5" onSubmit={(event) => void submit(event)}>
      <div className="flex items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
          <UserPlusIcon aria-hidden="true" className="size-5" />
        </span>
        <div>
          <h2 className="font-medium">创建账户</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            用户名创建后不可修改；临时密码仅用于本次提交。
          </p>
        </div>
      </div>

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <label className="grid gap-1.5 text-xs font-medium">
          用户名
          <input
            autoComplete="off"
            className="h-11 rounded-lg border bg-background px-3 font-mono text-sm"
            maxLength={64}
            minLength={3}
            name="username"
            pattern="[a-z0-9_.\-]+"
            required
          />
        </label>
        <label className="grid gap-1.5 text-xs font-medium">
          显示名称
          <input
            autoComplete="name"
            className="h-11 rounded-lg border bg-background px-3 text-sm"
            maxLength={256}
            name="display_name"
            required
          />
        </label>
        <label className="grid gap-1.5 text-xs font-medium">
          邮箱（可选）
          <input
            autoComplete="email"
            className="h-11 rounded-lg border bg-background px-3 text-sm"
            maxLength={320}
            name="email"
            type="email"
          />
        </label>
        <label className="grid gap-1.5 text-xs font-medium">
          角色
          <select
            className="h-11 rounded-lg border bg-background px-3 text-sm"
            defaultValue="engineer"
            name="role"
          >
            {roles.map((role) => <option key={role} value={role}>{ROLE_LABELS[role]}</option>)}
          </select>
        </label>
        <label className="grid gap-1.5 text-xs font-medium sm:col-span-2">
          临时密码
          <input
            autoComplete="new-password"
            className="h-11 rounded-lg border bg-background px-3 text-sm"
            maxLength={128}
            minLength={12}
            name="password"
            required
            type="password"
          />
        </label>
      </div>
      <div className="mt-5 flex justify-end">
        <Button className="h-11" disabled={creating} type="submit">
          {creating ? "正在创建…" : "创建账户"}
        </Button>
      </div>
    </form>
  );
}
