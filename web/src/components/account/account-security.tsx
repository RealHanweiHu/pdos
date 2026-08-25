"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { WorkspaceShell } from "@/components/workspace-shell";
import { requestIdentity } from "@/components/workspace-api";
import type { WorkspaceIdentity } from "@/components/workspace-types";

type LoadState = "loading" | "ready" | "error" | "redirecting";

function errorMessage(code: string | undefined) {
  if (code === "INVALID_CURRENT_PASSWORD") return "当前密码不正确，请重新输入。";
  if (code === "PASSWORD_REUSE_NOT_ALLOWED") return "新密码不能与当前密码相同。";
  if (code === "LOCAL_PASSWORD_UNAVAILABLE") {
    return "此账户通过外部身份登录，尚未配置本地密码。请联系租户管理员。";
  }
  return "密码修改失败，请稍后重试。";
}

export function AccountSecurity() {
  const { replace } = useRouter();
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [changed, setChanged] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    requestIdentity().then(
      (loaded) => {
        if (!active) return;
        if (loaded === null) {
          setLoadState("redirecting");
          replace("/login");
          return;
        }
        setIdentity(loaded);
        setLoadState("ready");
      },
      () => {
        if (active) setLoadState("error");
      },
    );
    return () => {
      active = false;
    };
  }, [replace]);

  async function logout() {
    setLoggingOut(true);
    try {
      await fetch("/api/session/logout", { method: "POST", credentials: "same-origin" });
    } finally {
      replace("/login");
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    if (newPassword !== confirmation) {
      setFormError("两次输入的新密码不一致。");
      return;
    }
    setSubmitting(true);
    try {
      const response = await fetch("/api/session/change-password", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null) as {
          detail?: { code?: string };
        } | null;
        setFormError(errorMessage(body?.detail?.code));
        if (response.status === 401) replace("/login");
        return;
      }
      setCurrentPassword("");
      setNewPassword("");
      setConfirmation("");
      setChanged(true);
    } catch {
      setFormError("密码修改失败，请检查连接后重试。");
    } finally {
      setSubmitting(false);
    }
  }

  if (loadState === "redirecting") return null;
  if (loadState === "loading") {
    return <main className="grid min-h-svh place-items-center text-sm text-muted-foreground">正在读取账户…</main>;
  }
  if (loadState === "error" || identity === null) {
    return (
      <main className="grid min-h-svh place-items-center px-4">
        <div className="max-w-md text-center">
          <h1 className="text-xl font-semibold">无法读取账户</h1>
          <p className="mt-2 text-sm text-muted-foreground">请检查连接后重新加载页面。</p>
        </div>
      </main>
    );
  }

  return (
    <WorkspaceShell
      active="account-security"
      identity={identity}
      loggingOut={loggingOut}
      onLogout={() => void logout()}
    >
      <div className="mx-auto max-w-2xl">
        <p className="font-mono text-xs font-semibold tracking-[0.18em] text-primary">ACCOUNT SECURITY</p>
        {changed ? (
          <section aria-live="polite" className="mt-4 rounded-lg border bg-card p-6 shadow-sm">
            <h1 className="text-2xl font-semibold tracking-tight">密码已修改</h1>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              为保护账户，原有会话已全部失效。请使用新密码重新登录。
            </p>
            <Button asChild className="mt-5">
              <Link href="/login">使用新密码登录</Link>
            </Button>
          </section>
        ) : (
          <>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight">账户安全</h1>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              修改当前账户的本地登录密码。成功后会立即结束现有会话。
            </p>
            <form className="mt-6 space-y-5 rounded-lg border bg-card p-6 shadow-sm" onSubmit={(event) => void submit(event)}>
              <label className="block text-sm font-medium">
                当前密码
                <input
                  autoComplete="current-password"
                  className="mt-2 min-h-11 w-full rounded-lg border bg-background px-3 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/30"
                  maxLength={128}
                  onChange={(event) => setCurrentPassword(event.target.value)}
                  required
                  type="password"
                  value={currentPassword}
                />
              </label>
              <label className="block text-sm font-medium">
                新密码
                <input
                  aria-describedby="new-password-help"
                  autoComplete="new-password"
                  className="mt-2 min-h-11 w-full rounded-lg border bg-background px-3 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/30"
                  minLength={12}
                  maxLength={128}
                  onChange={(event) => setNewPassword(event.target.value)}
                  required
                  type="password"
                  value={newPassword}
                />
              </label>
              <p className="-mt-3 text-xs text-muted-foreground" id="new-password-help">至少 12 个字符，且不能与当前密码相同。</p>
              <label className="block text-sm font-medium">
                确认新密码
                <input
                  autoComplete="new-password"
                  className="mt-2 min-h-11 w-full rounded-lg border bg-background px-3 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/30"
                  minLength={12}
                  maxLength={128}
                  onChange={(event) => setConfirmation(event.target.value)}
                  required
                  type="password"
                  value={confirmation}
                />
              </label>
              {formError ? <p aria-live="polite" className="text-sm text-destructive">{formError}</p> : null}
              <Button disabled={submitting} type="submit">
                {submitting ? "正在修改…" : "修改密码"}
              </Button>
            </form>
          </>
        )}
      </div>
    </WorkspaceShell>
  );
}
