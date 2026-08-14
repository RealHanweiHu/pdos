"use client";

import { LockKeyIcon, WarningCircleIcon } from "@phosphor-icons/react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { WorkspaceShell } from "@/components/workspace-shell";
import type { WorkspaceIdentity } from "@/components/workspace-types";

import { requestDingTalkBootstrap, startDingTalkLink } from "./dingtalk-api";
import { DingTalkIntegrationView } from "./dingtalk-integration-view";
import type { DingTalkBootstrap } from "./dingtalk-types";

type LoadState = "loading" | "ready" | "forbidden" | "error" | "redirecting";

export function DingTalkIntegration() {
  const { replace } = useRouter();
  const [state, setState] = useState<LoadState>("loading");
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null);
  const [data, setData] = useState<DingTalkBootstrap | null>(null);
  const [linking, setLinking] = useState(false);
  const [linkError, setLinkError] = useState<string | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);

  const apply = useCallback(
    (loaded: Awaited<ReturnType<typeof requestDingTalkBootstrap>>) => {
      if (loaded === null) {
        setState("redirecting");
        replace("/login");
        return;
      }
      setIdentity(loaded.identity);
      if (loaded.kind === "forbidden") {
        setState("forbidden");
        return;
      }
      setData(loaded.data);
      setState("ready");
    },
    [replace],
  );

  const load = useCallback(async () => {
    try {
      apply(await requestDingTalkBootstrap());
    } catch {
      setState("error");
    }
  }, [apply]);

  useEffect(() => {
    let active = true;
    requestDingTalkBootstrap().then(
      (loaded) => active && apply(loaded),
      () => active && setState("error"),
    );
    return () => { active = false; };
  }, [apply]);

  async function link() {
    setLinking(true);
    setLinkError(null);
    try {
      const url = await startDingTalkLink();
      if (url === null) {
        replace("/login");
        return;
      }
      window.location.assign(url);
    } catch {
      setLinkError("无法启动钉钉身份绑定，请检查应用配置后重试。");
      setLinking(false);
    }
  }

  async function logout() {
    setLoggingOut(true);
    try { await fetch("/api/session/logout", { method: "POST" }); }
    finally { replace("/login"); }
  }

  if (state === "redirecting") return null;
  if (state === "loading") {
    return <main aria-busy="true" className="mx-auto max-w-6xl px-4 py-10 text-sm text-muted-foreground">正在读取钉钉集成状态…</main>;
  }
  if (identity === null || state === "error") {
    return (
      <main className="mx-auto flex min-h-svh max-w-md flex-col items-center justify-center px-6 text-center">
        <WarningCircleIcon aria-hidden="true" className="size-9 text-destructive" />
        <h1 className="mt-3 text-lg font-semibold">无法读取钉钉集成状态</h1>
        <Button className="mt-4 h-11" onClick={() => { setState("loading"); void load(); }}>重试</Button>
      </main>
    );
  }
  if (state === "forbidden") {
    return (
      <WorkspaceShell active="dingtalk-integration" identity={identity} loggingOut={loggingOut} onLogout={() => void logout()}>
        <section className="mx-auto max-w-lg rounded-lg border bg-card p-6 text-center">
          <LockKeyIcon aria-hidden="true" className="mx-auto size-9 text-muted-foreground" />
          <h1 className="mt-3 text-lg font-semibold">当前角色不可访问</h1>
          <p className="mt-1 text-sm text-muted-foreground">Supplier 与 Customer 不进入企业钉钉集成面。</p>
        </section>
      </WorkspaceShell>
    );
  }
  if (data === null) return null;
  return (
    <DingTalkIntegrationView
      data={data}
      identity={identity}
      linking={linking}
      linkError={linkError}
      loggingOut={loggingOut}
      onLink={() => void link()}
      onLogout={() => void logout()}
    />
  );
}
