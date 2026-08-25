"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import type { WorkspaceIdentity } from "@/components/workspace-types";

import {
  createManagedUser,
  requestUserManagementBootstrap,
  resetManagedUserPassword,
  updateManagedUser,
} from "./user-management-api";
import {
  UserManagementError,
  UserManagementForbidden,
  UserManagementLoading,
} from "./user-management-state";
import type { ManagedUser, UserCreate, UserUpdate } from "./user-management-types";
import { UserManagementView } from "./user-management-view";

type LoadState = "loading" | "ready" | "forbidden" | "error" | "redirecting";

export function UserManagement() {
  const { replace } = useRouter();
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null);
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [loggingOut, setLoggingOut] = useState(false);
  const [creating, setCreating] = useState(false);
  const [busyUserId, setBusyUserId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const applyBootstrap = useCallback(
    (loaded: Awaited<ReturnType<typeof requestUserManagementBootstrap>>) => {
      if (loaded === null) {
        setLoadState("redirecting");
        replace("/login");
        return;
      }
      setIdentity(loaded.identity);
      if (loaded.kind === "forbidden") {
        setLoadState("forbidden");
        return;
      }
      setUsers(loaded.users);
      setLoadState("ready");
    },
    [replace],
  );

  async function load() {
    try {
      applyBootstrap(await requestUserManagementBootstrap());
    } catch {
      setLoadState("error");
    }
  }

  useEffect(() => {
    let active = true;
    requestUserManagementBootstrap().then(
      (loaded) => {
        if (active) applyBootstrap(loaded);
      },
      () => {
        if (active) setLoadState("error");
      },
    );
    return () => {
      active = false;
    };
  }, [applyBootstrap]);

  function replaceUser(updated: ManagedUser) {
    setUsers((current) => current.map((user) => user.id === updated.id ? updated : user));
  }

  async function create(payload: UserCreate) {
    setCreating(true);
    setNotice(null);
    setActionError(null);
    try {
      const created = await createManagedUser(payload);
      if (created === null) {
        replace("/login");
        return false;
      }
      setUsers((current) => [...current, created]);
      setNotice(`账户 ${created.username} 已创建`);
      return true;
    } catch {
      setActionError("账户创建失败。请检查用户名、邮箱、角色和密码后重试。");
      return false;
    } finally {
      setCreating(false);
    }
  }

  async function update(user: ManagedUser, changes: UserUpdate) {
    setBusyUserId(user.id);
    setNotice(null);
    setActionError(null);
    try {
      const updated = await updateManagedUser(user.id, changes);
      if (updated === null) {
        replace("/login");
        return;
      }
      replaceUser(updated);
      setNotice(`${user.username} 的账户设置已更新`);
    } catch {
      setActionError(`无法更新 ${user.username}。请确认权限和 Owner 保留规则。`);
    } finally {
      setBusyUserId(null);
    }
  }

  async function resetPassword(user: ManagedUser, password: string) {
    setBusyUserId(user.id);
    setNotice(null);
    setActionError(null);
    try {
      const updated = await resetManagedUserPassword(user.id, password);
      if (updated === null) {
        replace("/login");
        return false;
      }
      replaceUser(updated);
      setNotice(`${user.username} 的密码已重置，旧会话已失效`);
      return true;
    } catch {
      setActionError(`无法重置 ${user.username} 的密码。`);
      return false;
    } finally {
      setBusyUserId(null);
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

  if (loadState === "redirecting") return null;
  if (loadState === "loading") return <UserManagementLoading />;
  if (loadState === "error" || identity === null) {
    return <UserManagementError onRetry={() => { setLoadState("loading"); void load(); }} />;
  }
  if (loadState === "forbidden") {
    return <UserManagementForbidden identity={identity} loggingOut={loggingOut} onLogout={() => void logout()} />;
  }
  return (
    <UserManagementView
      actionError={actionError}
      busyUserId={busyUserId}
      creating={creating}
      identity={identity}
      loggingOut={loggingOut}
      notice={notice}
      onCreate={create}
      onLogout={() => void logout()}
      onResetPassword={resetPassword}
      onUpdate={update}
      users={users}
    />
  );
}
