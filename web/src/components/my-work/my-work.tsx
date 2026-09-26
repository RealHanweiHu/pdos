"use client";

import { WarningCircleIcon } from "@phosphor-icons/react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { useFirstScreenSample } from "@/components/diagnostics/use-first-screen-sample";

import { Button } from "@/components/ui/button";
import { requestIdentity } from "@/components/workspace-api";
import type { WorkspaceIdentity } from "@/components/workspace-types";

import {
  acknowledgeNotification,
  MyWorkForbiddenError,
  requestMyNotifications,
  requestMyWork,
} from "./my-work-api";
import type { MyNotifications, MyWork as MyWorkData } from "./my-work-types";
import { workDate } from "./work-dates";
import { MyWorkView } from "./my-work-view";

type MyWorkState = "loading" | "ready" | "forbidden" | "error" | "redirecting";

export function MyWork() {
  const { replace } = useRouter();
  const [state, setState] = useState<MyWorkState>("loading");
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null);
  const [work, setWork] = useState<MyWorkData | null>(null);
  const [notifications, setNotifications] = useState<MyNotifications | null>(null);
  const [notificationState, setNotificationState] = useState<"loading" | "ready" | "error">("loading");
  const [loggingOut, setLoggingOut] = useState(false);
  const loadSequence = useRef(0);
  const notificationSequence = useRef(0);

  const loadNotifications = useCallback(async (isActive: () => boolean = () => true) => {
    const sequence = ++notificationSequence.current;
    const isCurrent = () => isActive() && notificationSequence.current === sequence;
    setNotificationState("loading");
    try {
      const loaded = await requestMyNotifications();
      if (!isCurrent()) return;
      if (loaded === null) {
        setState("redirecting");
        replace("/login");
        return;
      }
      setNotifications(loaded);
      setNotificationState("ready");
    } catch {
      if (isCurrent()) setNotificationState("error");
    }
  }, [replace]);

  const load = useCallback(async (isActive: () => boolean = () => true) => {
    const sequence = ++loadSequence.current;
    const isCurrent = () => isActive() && loadSequence.current === sequence;
    notificationSequence.current += 1;
    setNotifications(null);
    setNotificationState("loading");
    try {
      const loadedIdentity = await requestIdentity();
      if (!isCurrent()) return;
      if (loadedIdentity === null) {
        setState("redirecting");
        replace("/login");
        return;
      }
      setIdentity(loadedIdentity);
      void loadNotifications(isCurrent);
      const loadedWork = await requestMyWork();
      if (!isCurrent()) return;
      if (loadedWork === null) {
        setState("redirecting");
        replace("/login");
        return;
      }
      setWork(loadedWork);
      setState("ready");
    } catch (error) {
      if (!isCurrent()) return;
      setState(error instanceof MyWorkForbiddenError ? "forbidden" : "error");
    }
  }, [loadNotifications, replace]);

  useFirstScreenSample("my-work", state === "ready" && notificationState === "ready" ? "ready"
    : ["error", "forbidden", "redirecting"].includes(state) || notificationState === "error" ? "error" : "loading",
    { tasks: work?.tasks.length ?? 0, totalTasks: work?.counts.tasks ?? 0, notifications: notifications?.unread_count ?? 0 });

  async function acknowledge(notificationId: string) {
    try {
      await acknowledgeNotification(notificationId);
      await loadNotifications();
    } catch {
      setNotificationState("error");
    }
  }

  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => { if (active) return load(() => active); });
    return () => { active = false; };
  }, [load]);

  async function logout() {
    setLoggingOut(true);
    try {
      await fetch("/api/session/logout", { method: "POST", credentials: "same-origin" });
    } finally {
      replace("/login");
    }
  }

  if (state === "redirecting") return null;
  if (state === "loading") {
    return (
      <main className="mx-auto max-w-6xl px-4 py-10 text-sm text-muted-foreground">
        正在加载我的工作…
      </main>
    );
  }
  if (state === "forbidden") {
    return (
      <main className="mx-auto flex min-h-svh max-w-md flex-col items-center justify-center px-6 text-center">
        <WarningCircleIcon aria-hidden className="size-9 text-muted-foreground" />
        <h1 className="mt-3 text-lg font-semibold">此角色没有个人工作台</h1>
        <p className="mt-1 text-sm text-muted-foreground">外部协作角色请从项目页查看开放给你的内容。</p>
      </main>
    );
  }
  if (state === "error" || identity === null || work === null) {
    return (
      <main className="mx-auto flex min-h-svh max-w-md flex-col items-center justify-center px-6 text-center">
        <WarningCircleIcon aria-hidden className="size-9 text-destructive" />
        <h1 className="mt-3 text-lg font-semibold">我的工作暂不可用</h1>
        <p className="mt-1 text-sm text-muted-foreground">无法读取个人待办，请检查连接后重试。</p>
        <Button className="mt-4 h-11" onClick={() => { setState("loading"); void load(); }}>
          重新加载
        </Button>
      </main>
    );
  }

  return (
    <MyWorkView
      identity={identity}
      loggingOut={loggingOut}
      notifications={notifications}
      notificationState={notificationState}
      onRetryNotifications={() => void loadNotifications()}
      onAcknowledge={(notificationId) => void acknowledge(notificationId)}
      onLogout={() => void logout()}
      today={workDate(new Date().toISOString())}
      work={work}
    />
  );
}
