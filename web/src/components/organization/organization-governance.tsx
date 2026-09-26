"use client";

import { OrganizationHandoverHistory } from "./organization-handover-history";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { requestUserManagementBootstrap } from "@/components/users/user-management-api";
import type { ManagedUser } from "@/components/users/user-management-types";
import { WorkspaceShell } from "@/components/workspace-shell";
import type { WorkspaceIdentity } from "@/components/workspace-types";
import { ProcessTemplateLibrary } from "./process-template-library";
import { cn } from "@/lib/utils";

import {
  createDepartment,
  grantDelegation,
  handOver,
  previewHandover,
  requestDelegations,
  requestDepartments,
  revokeDelegation,
  setPlacement,
} from "./organization-api";
import {
  HANDOVER_COUNT_LABELS,
  delegationState,
  type Delegation,
  type Department,
  type HandoverPreview,
} from "./organization-types";

type LoadState = "loading" | "ready" | "forbidden" | "error" | "redirecting";

const stateLabels = {
  active: "生效中",
  scheduled: "未开始",
  expired: "已过期",
  revoked: "已撤销",
} as const;

function messageFrom(error: unknown) {
  return error instanceof Error ? error.message : "操作失败，请稍后重试。";
}

function isoLocal(offsetHours: number) {
  const at = new Date(Date.now() + offsetHours * 3_600_000);
  at.setSeconds(0, 0);
  return at.toISOString().slice(0, 16);
}

export function OrganizationGovernance() {
  const { replace } = useRouter();
  const [state, setState] = useState<LoadState>("loading");
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null);
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [delegations, setDelegations] = useState<Delegation[]>([]);
  const [loggingOut, setLoggingOut] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const [departmentName, setDepartmentName] = useState("");
  const [placementUser, setPlacementUser] = useState("");
  const [placementDepartment, setPlacementDepartment] = useState("");
  const [placementManager, setPlacementManager] = useState("");
  const [principal, setPrincipal] = useState("");
  const [delegate, setDelegate] = useState("");
  const [startsAt, setStartsAt] = useState(() => isoLocal(0));
  const [endsAt, setEndsAt] = useState(() => isoLocal(24 * 7));
  const [reason, setReason] = useState("");
  const [handoverFrom, setHandoverFrom] = useState("");
  const [handoverTo, setHandoverTo] = useState("");
  const [confirmingHandover, setConfirmingHandover] = useState(false);
  const [handoverPreview, setHandoverPreview] = useState<HandoverPreview | null>(null);
  const [deactivateSource, setDeactivateSource] = useState(true);

  async function loadData() {
    const [bootstrap, nextDepartments, nextDelegations] = await Promise.all([
      requestUserManagementBootstrap(),
      requestDepartments(),
      requestDelegations(),
    ]);
    setUsers(bootstrap?.kind === "ready" ? bootstrap.users : []);
    setDepartments(nextDepartments);
    setDelegations(nextDelegations);
  }

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const bootstrap = await requestUserManagementBootstrap();
        if (!active) return;
        if (bootstrap === null) {
          setState("redirecting");
          replace("/login");
          return;
        }
        setIdentity(bootstrap.identity);
        if (bootstrap.kind === "forbidden") {
          setState("forbidden");
          return;
        }
        setUsers(bootstrap.users);
        const [nextDepartments, nextDelegations] = await Promise.all([
          requestDepartments(),
          requestDelegations(),
        ]);
        if (!active) return;
        setDepartments(nextDepartments);
        setDelegations(nextDelegations);
        setState("ready");
      } catch (loadError) {
        if (!active) return;
        setError(messageFrom(loadError));
        setState("error");
      }
    })();
    return () => {
      active = false;
    };
  }, [replace]);

  async function run(action: () => Promise<string>) {
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      const message = await action();
      await loadData();
      setStatus(message);
    } catch (actionError) {
      setError(messageFrom(actionError));
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    setLoggingOut(true);
    try {
      await fetch("/api/session/logout", { method: "POST", credentials: "same-origin" });
    } finally {
      replace("/login");
    }
  }

  const nameOf = (userId: string) =>
    users.find((user) => user.id === userId)?.display_name ?? userId.slice(0, 8);

  if (state === "redirecting") return null;
  if (state === "loading") {
    return (
      <main aria-busy="true" className="mx-auto max-w-6xl px-4 py-10 text-sm text-muted-foreground">
        正在加载组织与代理…
      </main>
    );
  }
  if (state === "forbidden") {
    return (
      <main className="mx-auto flex min-h-svh max-w-md flex-col items-center justify-center px-6 text-center">
        <h1 className="text-lg font-semibold">仅管理员可管理组织</h1>
      </main>
    );
  }
  if (state === "error" || identity === null) {
    return (
      <main className="mx-auto flex min-h-svh max-w-md flex-col items-center justify-center px-6 text-center">
        <h1 className="text-lg font-semibold">组织管理暂不可用</h1>
        <p className="mt-1 text-sm text-muted-foreground">{error ?? "无法读取组织数据。"}</p>
      </main>
    );
  }

  return (
    <WorkspaceShell
      active="organization"
      identity={identity}
      loggingOut={loggingOut}
      onLogout={() => void logout()}
    >
      <div className="border-b pb-4">
        <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-primary">
          Admin Workspace
        </p>
        <h1 className="mt-1 text-lg font-semibold">组织、代理与交接</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          汇报线支撑升级链与四眼独立性；休假代理只借出项目可见范围，不借出角色权限；离职一次性移交在办的负责人与验证人。
        </p>
      </div>

      {status ? (
        <p
          className="mt-4 rounded-lg border border-success/30 bg-success/10 px-3 py-2 text-sm text-success"
          role="status"
        >
          {status}
        </p>
      ) : null}
      {error ? (
        <p
          className="mt-4 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
          role="alert"
        >
          {error}
        </p>
      ) : null}

      <section aria-label="部门与汇报线" className="mt-5 rounded-lg border bg-card p-4">
        <h2 className="text-sm font-semibold">部门与汇报线</h2>
        <form
          className="mt-3 flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void run(async () => {
              await createDepartment(departmentName.trim());
              setDepartmentName("");
              return "部门已创建";
            });
          }}
        >
          <label className="text-xs">
            <span className="block text-muted-foreground">新部门名称</span>
            <input
              className="mt-1 h-11 min-w-52 rounded-lg border bg-background px-2 text-sm sm:h-9"
              onChange={(event) => setDepartmentName(event.target.value)}
              required
              value={departmentName}
            />
          </label>
          <button
            className="h-11 rounded-lg bg-primary px-3 text-xs font-medium text-primary-foreground disabled:opacity-50 sm:h-9"
            disabled={busy || departmentName.trim() === ""}
            type="submit"
          >
            创建部门
          </button>
        </form>

        <ul className="mt-3 flex flex-wrap gap-2" role="list">
          {departments.map((department) => (
            <li className="rounded-full border px-3 py-1 text-xs" key={department.id}>
              {department.name}
              {department.parent_department_id ? (
                <span className="ml-1 text-muted-foreground">
                  （上级：
                  {departments.find((item) => item.id === department.parent_department_id)?.name ??
                    "—"}
                  ）
                </span>
              ) : null}
            </li>
          ))}
          {departments.length === 0 ? (
            <li className="text-xs text-muted-foreground">还没有部门。</li>
          ) : null}
        </ul>

        <form
          className="mt-4 flex flex-wrap items-end gap-2 border-t pt-4"
          onSubmit={(event) => {
            event.preventDefault();
            void run(async () => {
              await setPlacement(placementUser, {
                department_id: placementDepartment || null,
                manager_user_id: placementManager || null,
              });
              return "组织归属已更新";
            });
          }}
        >
          <label className="text-xs">
            <span className="block text-muted-foreground">成员</span>
            <select
              className="mt-1 h-11 min-w-40 rounded-lg border bg-background px-2 text-sm sm:h-9"
              onChange={(event) => setPlacementUser(event.target.value)}
              required
              value={placementUser}
            >
              <option value="">请选择</option>
              {users.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.display_name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs">
            <span className="block text-muted-foreground">部门</span>
            <select
              className="mt-1 h-11 min-w-40 rounded-lg border bg-background px-2 text-sm sm:h-9"
              onChange={(event) => setPlacementDepartment(event.target.value)}
              value={placementDepartment}
            >
              <option value="">（不设置）</option>
              {departments.map((department) => (
                <option key={department.id} value={department.id}>
                  {department.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs">
            <span className="block text-muted-foreground">汇报给</span>
            <select
              className="mt-1 h-11 min-w-40 rounded-lg border bg-background px-2 text-sm sm:h-9"
              onChange={(event) => setPlacementManager(event.target.value)}
              value={placementManager}
            >
              <option value="">（不设置）</option>
              {users
                .filter((user) => user.id !== placementUser)
                .map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.display_name}
                  </option>
                ))}
            </select>
          </label>
          <button
            className="h-11 rounded-lg border px-3 text-xs font-medium disabled:opacity-50 sm:h-9"
            disabled={busy || placementUser === ""}
            type="submit"
          >
            保存归属
          </button>
        </form>
      </section>

      <section aria-label="休假代理" className="mt-5 rounded-lg border bg-card p-4">
        <h2 className="text-sm font-semibold">休假代理</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          代理人以自己的身份行事，因此四眼原则依旧需要两个不同的人。
        </p>
        <form
          className="mt-3 flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void run(async () => {
              await grantDelegation({
                principal_user_id: principal,
                delegate_user_id: delegate,
                starts_at: new Date(startsAt).toISOString(),
                ends_at: new Date(endsAt).toISOString(),
                reason: reason.trim(),
              });
              setReason("");
              return "代理已创建";
            });
          }}
        >
          <label className="text-xs">
            <span className="block text-muted-foreground">委托人</span>
            <select
              className="mt-1 h-11 min-w-36 rounded-lg border bg-background px-2 text-sm sm:h-9"
              onChange={(event) => setPrincipal(event.target.value)}
              required
              value={principal}
            >
              <option value="">请选择</option>
              {users.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.display_name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs">
            <span className="block text-muted-foreground">代理人</span>
            <select
              className="mt-1 h-11 min-w-36 rounded-lg border bg-background px-2 text-sm sm:h-9"
              onChange={(event) => setDelegate(event.target.value)}
              required
              value={delegate}
            >
              <option value="">请选择</option>
              {users
                .filter((user) => user.id !== principal)
                .map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.display_name}
                  </option>
                ))}
            </select>
          </label>
          <label className="text-xs">
            <span className="block text-muted-foreground">开始</span>
            <input
              className="mt-1 h-11 rounded-lg border bg-background px-2 text-sm sm:h-9"
              onChange={(event) => setStartsAt(event.target.value)}
              required
              type="datetime-local"
              value={startsAt}
            />
          </label>
          <label className="text-xs">
            <span className="block text-muted-foreground">结束</span>
            <input
              className="mt-1 h-11 rounded-lg border bg-background px-2 text-sm sm:h-9"
              onChange={(event) => setEndsAt(event.target.value)}
              required
              type="datetime-local"
              value={endsAt}
            />
          </label>
          <label className="text-xs">
            <span className="block text-muted-foreground">原因</span>
            <input
              className="mt-1 h-11 min-w-44 rounded-lg border bg-background px-2 text-sm sm:h-9"
              onChange={(event) => setReason(event.target.value)}
              required
              value={reason}
            />
          </label>
          <button
            className="h-11 rounded-lg bg-primary px-3 text-xs font-medium text-primary-foreground disabled:opacity-50 sm:h-9"
            disabled={busy || principal === "" || delegate === "" || reason.trim() === ""}
            type="submit"
          >
            创建代理
          </button>
        </form>

        <ul className="mt-3 space-y-2" role="list">
          {delegations.map((delegation) => {
            const current = delegationState(delegation, new Date());
            return (
              <li
                className="flex flex-wrap items-center gap-3 rounded-lg border px-3 py-2"
                key={delegation.id}
              >
                <span
                  className={cn(
                    "rounded-full border px-2 py-0.5 text-[10px] font-semibold",
                    current === "active" && "border-success/30 bg-success/10 text-success",
                    current === "scheduled" && "border-pending/30 bg-pending/10 text-pending",
                    (current === "expired" || current === "revoked") &&
                      "border-muted-foreground/30 bg-muted text-muted-foreground",
                  )}
                >
                  {stateLabels[current]}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">
                    {nameOf(delegation.principal_user_id)} → {nameOf(delegation.delegate_user_id)}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {delegation.reason} · {new Date(delegation.starts_at).toLocaleString()} 至{" "}
                    {new Date(delegation.ends_at).toLocaleString()}
                  </p>
                </div>
                {delegation.revoked_at === null ? (
                  <button
                    className="h-11 rounded-lg border px-3 text-xs sm:h-9"
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        await revokeDelegation(delegation.id);
                        return "代理已撤销";
                      })
                    }
                    type="button"
                  >
                    撤销
                  </button>
                ) : null}
              </li>
            );
          })}
          {delegations.length === 0 ? (
            <li className="text-xs text-muted-foreground">还没有代理记录。</li>
          ) : null}
        </ul>
      </section>

      <section aria-label="离职交接" className="mt-5 rounded-lg border bg-card p-4">
        <h2 className="text-sm font-semibold">离职交接</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          先查看实际在办责任和接手条件，再确认移交。固定批准版本中的责任从原流程办理，已关闭的历史保留原负责人。
        </p>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <label className="text-xs">
            <span className="block text-muted-foreground">离职成员</span>
            <select
              className="mt-1 h-11 min-w-40 rounded-lg border bg-background px-2 text-sm sm:h-9"
              onChange={(event) => {
                setHandoverFrom(event.target.value);
                setConfirmingHandover(false);
              }}
              value={handoverFrom}
            >
              <option value="">请选择</option>
              {users.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.display_name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs">
            <span className="block text-muted-foreground">接手成员</span>
            <select
              className="mt-1 h-11 min-w-40 rounded-lg border bg-background px-2 text-sm sm:h-9"
              onChange={(event) => {
                setHandoverTo(event.target.value);
                setConfirmingHandover(false);
              }}
              value={handoverTo}
            >
              <option value="">请选择</option>
              {users
                .filter((user) => user.id !== handoverFrom)
                .map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.display_name}
                  </option>
                ))}
            </select>
          </label>
          <button
            className="h-11 rounded-lg border px-3 text-xs font-medium disabled:opacity-50 sm:h-9"
            disabled={busy || handoverFrom === "" || handoverTo === ""}
            onClick={() => void run(async () => {
              const preview = await previewHandover({ from_user_id: handoverFrom, to_user_id: handoverTo });
              setHandoverPreview(preview);
              setDeactivateSource(preview.manual_count === 0);
              setConfirmingHandover(true);
              return "已按当前在办责任准备交接清单";
            })}
            type="button"
          >
            准备交接
          </button>
        </div>

        {confirmingHandover && handoverPreview?.from_user_id === handoverFrom && handoverPreview.to_user_id === handoverTo ? (
          <div
            aria-label="交接确认"
            className="mt-3 rounded-lg border border-primary/40 bg-primary/5 p-3"
            role="dialog"
          >
            <p className="text-sm">
              将 <strong>{nameOf(handoverFrom)}</strong> 的 {handoverPreview.transfer_count} 项可办理责任移交给{" "}
              <strong>{nameOf(handoverTo)}</strong>。另有 {handoverPreview.manual_count} 项须在原流程处理，
              将撤销 {handoverPreview.delegations_to_revoke} 项当前或尚未开始的代理，
              为接手人补齐 {handoverPreview.project_access_count} 个项目的成员资格。
            </p>
            <div className="mt-3 max-h-96 space-y-2 overflow-y-auto">
              {handoverPreview.groups.map((group) => (
                <details key={group.key} className="rounded-lg border bg-background p-2">
                  <summary className="cursor-pointer text-sm">{group.label} · {group.count} 项 · {group.can_transfer ? "本次移交" : "原流程办理"}</summary>
                  {group.reasons.map((reason) => <p key={reason} className="mt-1 text-xs text-muted-foreground">{reason}</p>)}
                  <ul className="mt-2 space-y-1">{group.items.map((item) => (
                    <li key={item.id} className="text-xs"><a className="text-primary underline" href={item.href}>{item.title}</a></li>
                  ))}</ul>
                </details>
              ))}
            </div>
            <label className="mt-3 flex items-center gap-2 text-xs">
              <input type="checkbox" checked={deactivateSource} disabled={handoverPreview.manual_count > 0}
                onChange={(event) => setDeactivateSource(event.target.checked)} />
              本次移交后停用原账号{handoverPreview.manual_count > 0 ? "（待原流程责任处理完毕）" : ""}
            </label>
            <div className="mt-3 flex gap-2">
              <button
                className="h-11 rounded-lg bg-primary px-3 text-xs font-medium text-primary-foreground sm:h-9"
                disabled={busy || (!deactivateSource && handoverPreview.transfer_count === 0 && handoverPreview.delegations_to_revoke === 0)}
                onClick={() =>
                  void run(async () => {
                    const result = await handOver({
                      from_user_id: handoverFrom,
                      to_user_id: handoverTo,
                      deactivate_source: deactivateSource,
                      expected_digest: handoverPreview.basis_digest,
                    });
                    setConfirmingHandover(false);
                    const summary = Object.entries(result.transferred_counts)
                      .filter(([, count]) => count > 0)
                      .map(([key, count]) => `${HANDOVER_COUNT_LABELS[key] ?? key} ${count}`)
                      .join("、");
                    return `本批已办理${summary ? `：${summary}` : "：没有在办责任需要移交"}。${result.deactivated ? "原账号已停用" : "原账号保留，未转移责任请继续从原流程办理"}`;
                  })
                }
                type="button"
              >
                确认交接
              </button>
              <button
                className="h-11 rounded-lg border px-3 text-xs sm:h-9"
                onClick={() => setConfirmingHandover(false)}
                type="button"
              >
                取消
              </button>
            </div>
          </div>
        ) : null}
      </section>
      <OrganizationHandoverHistory sourceId={handoverFrom} targetId={handoverTo}/>
      <ProcessTemplateLibrary />
    </WorkspaceShell>
  );
}
