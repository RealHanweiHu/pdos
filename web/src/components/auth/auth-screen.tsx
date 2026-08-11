"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";

import { AuthFrame } from "./auth-frame";
import type {
  AuthIdentity,
  LoginPayload,
  SetupPayload,
  SubmissionResult,
} from "./auth-types";
import { LoginForm } from "./login-form";
import { SetupForm } from "./setup-form";

type ScreenState = "loading" | "login" | "setup" | "unavailable";

const errorMessages: Record<string, string> = {
  INVALID_CREDENTIALS: "租户、账号或密码不正确。",
  SETUP_ALREADY_COMPLETED: "系统已经完成初始化，请刷新后登录。",
  SETUP_LOGIN_FAILED: "工作区已创建，请使用管理员账号登录。",
  AUTH_SERVICE_UNAVAILABLE: "认证服务暂不可用，请稍后重试。",
  LOGIN_RATE_LIMITED: "尝试次数过多，请稍后重试。",
};

async function responseError(response: Response) {
  try {
    const body: unknown = await response.json();
    if (
      body &&
      typeof body === "object" &&
      "detail" in body &&
      body.detail &&
      typeof body.detail === "object" &&
      "code" in body.detail &&
      typeof body.detail.code === "string"
    ) {
      return errorMessages[body.detail.code] ?? "请求未完成，请检查输入后重试。";
    }
  } catch {
    // Use a stable user-facing fallback without exposing upstream response text.
  }
  return "请求未完成，请稍后重试。";
}

async function requestedScreen(): Promise<"login" | "setup"> {
  const response = await fetch("/api/session/status", {
    cache: "no-store",
    credentials: "same-origin",
  });
  if (!response.ok) throw new Error("status unavailable");
  const body: unknown = await response.json();
  if (
    !body ||
    typeof body !== "object" ||
    !("needs_setup" in body) ||
    typeof body.needs_setup !== "boolean"
  ) {
    throw new Error("invalid status response");
  }
  return body.needs_setup ? "setup" : "login";
}

export function AuthScreen({
  onAuthenticated,
}: {
  onAuthenticated?: (identity: AuthIdentity) => void;
}) {
  const router = useRouter();
  const [screen, setScreen] = useState<ScreenState>("loading");
  const [busy, setBusy] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);

  const loadStatus = useCallback(async () => {
    try {
      setScreen(await requestedScreen());
    } catch {
      setScreen("unavailable");
    }
  }, []);

  useEffect(() => {
    let active = true;
    requestedScreen().then(
      (nextScreen) => {
        if (active) setScreen(nextScreen);
      },
      () => {
        if (active) setScreen("unavailable");
      },
    );
    return () => {
      active = false;
    };
  }, []);

  async function submit(
    endpoint: "/api/session/login" | "/api/session/setup",
    payload: LoginPayload | SetupPayload,
  ): Promise<SubmissionResult> {
    setBusy(true);
    setAuthenticated(false);
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) return { ok: false, message: await responseError(response) };

      const identityResponse = await fetch("/api/session/me", {
        cache: "no-store",
        credentials: "same-origin",
      });
      if (!identityResponse.ok) {
        return { ok: false, message: "会话未能验证，请重新登录。" };
      }
      const identity = (await identityResponse.json()) as AuthIdentity;
      setAuthenticated(true);
      if (onAuthenticated) onAuthenticated(identity);
      else router.push("/requirements");
      return { ok: true };
    } catch {
      return { ok: false, message: "网络连接失败，请稍后重试。" };
    } finally {
      setBusy(false);
    }
  }

  if (screen === "loading") {
    return (
      <AuthFrame>
        <div aria-busy="true" aria-label="正在确认工作区状态" className="space-y-4">
          <div className="h-4 w-24 animate-pulse rounded-lg bg-muted" />
          <div className="h-7 w-48 animate-pulse rounded-lg bg-muted" />
          <div className="h-11 animate-pulse rounded-lg bg-muted" />
          <div className="h-11 animate-pulse rounded-lg bg-muted" />
        </div>
      </AuthFrame>
    );
  }

  if (screen === "unavailable") {
    return (
      <AuthFrame>
        <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-destructive">
          Service unavailable
        </p>
        <h1 className="mt-3 text-xl font-semibold tracking-tight">无法连接认证服务</h1>
        <p className="mt-2 text-sm leading-6 text-muted-foreground" role="alert">
          尚未读取工作区状态。请确认 API 与数据库已启动，然后重试。
        </p>
        <Button
          className="mt-6 h-11 w-full"
          onClick={() => {
            setScreen("loading");
            void loadStatus();
          }}
        >
          重新连接
        </Button>
      </AuthFrame>
    );
  }

  const setup = screen === "setup";
  return (
    <AuthFrame>
      <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-primary">
        {setup ? "First-run setup" : "Tenant sign-in"}
      </p>
      <h1 className="mt-3 text-xl font-semibold tracking-tight">
        {setup ? "初始化 PDOS 工作区" : "登录 PDOS"}
      </h1>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">
        {setup
          ? "空库仅允许完成一次初始化。创建首个租户和 Owner 管理员后，setup 入口将永久关闭。"
          : "使用租户标识与本地账号进入。身份范围会在每次受保护请求中重新校验。"}
      </p>
      {authenticated ? (
        <p className="mt-4 rounded-lg border border-success/30 bg-success/10 px-3 py-2 text-sm text-success" role="status">
          身份验证成功，正在进入工作区…
        </p>
      ) : null}
      {setup ? (
        <SetupForm busy={busy} onSubmit={(payload) => submit("/api/session/setup", payload)} />
      ) : (
        <LoginForm busy={busy} onSubmit={(payload) => submit("/api/session/login", payload)} />
      )}
      <p className="mt-6 border-t pt-4 text-xs leading-5 text-muted-foreground">
        会话令牌仅保存在 HttpOnly cookie 中，不写入浏览器存储，也不会显示在页面上。
      </p>
    </AuthFrame>
  );
}
