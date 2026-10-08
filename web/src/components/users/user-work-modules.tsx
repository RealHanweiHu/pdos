import { useState } from "react";

import { Button } from "@/components/ui/button";
import { WORK_MODULES, type WorkModule } from "@/components/work-modules";
import { getDefaultPerspective, getPerspective } from "@/components/workspace-experience";

import type { ManagedUser, UserUpdate } from "./user-management-types";

export function UserWorkModules({ user, busy, editable, onUpdate }: {
  user: ManagedUser;
  busy: boolean;
  editable: boolean;
  onUpdate: (user: ManagedUser, changes: UserUpdate) => Promise<void>;
}) {
  const [draft, setDraft] = useState<WorkModule[]>(user.work_modules ?? []);
  const primary = getDefaultPerspective(user.role);
  const internal = !["supplier", "customer"].includes(user.role);
  const assigned = user.work_modules ?? [];
  const changed = WORK_MODULES.some(module => draft.includes(module) !== assigned.includes(module));
  if (!internal) return <p className="mt-2 text-xs text-muted-foreground">外部协作账户</p>;
  return <div className="mt-2">
    <p className="text-xs text-muted-foreground">主模块：{getPerspective(primary).label}</p>
    {assigned.filter(module => module !== primary).length > 0 && <p className="mt-1 text-xs text-muted-foreground">兼任：{assigned.filter(module => module !== primary).map(module => getPerspective(module).label).join("、")}</p>}
    {editable && <details className="mt-2">
      <summary className="inline-flex min-h-11 cursor-pointer items-center rounded-md text-xs font-medium text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">配置兼任模块 · {user.username}</summary>
      <form className="mt-1 min-w-52 rounded-lg border bg-background p-3" onSubmit={event => {
        event.preventDefault();
        void onUpdate(user, { work_modules: WORK_MODULES.filter(module => draft.includes(module) && module !== primary) });
      }}>
        <fieldset disabled={busy}>
          <legend className="text-xs font-medium">{user.username} 的工作模块</legend>
          {WORK_MODULES.map(module => <label key={module} className="flex min-h-11 cursor-pointer items-center gap-2 text-xs">
            <input type="checkbox" className="size-4 accent-primary" checked={module === primary || draft.includes(module)} disabled={module === primary} onChange={event => setDraft(current => event.target.checked ? [...current, module] : current.filter(item => item !== module))} />
            {getPerspective(module).label}{module === primary ? "（主角色自动启用）" : ""}
          </label>)}
        </fieldset>
        <p className="mt-1 max-w-64 text-xs leading-5 text-muted-foreground">保存后自动加入该成员的工作台；具体办理权限按原职责执行。</p>
        <Button className="mt-3 min-h-11" size="sm" disabled={busy || !changed} type="submit">保存 {user.username} 的模块</Button>
      </form>
    </details>}
  </div>;
}
