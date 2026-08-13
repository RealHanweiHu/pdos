"use client";

import { WarningCircleIcon } from "@phosphor-icons/react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";

import { AuthFrame } from "@/components/auth/auth-frame";
import { Button } from "@/components/ui/button";

function DingTalkCallbackContent() {
  const router = useRouter();
  const params = useSearchParams();
  const authCode = params.get("authCode") ?? params.get("code");
  const oauthState = params.get("state");
  const [error, setError] = useState(!authCode || !oauthState);
  const submitted = useRef(false);

  useEffect(() => {
    if (!authCode || !oauthState || submitted.current) return;
    submitted.current = true;
    fetch("/api/session/dingtalk/callback", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ auth_code: authCode, state: oauthState }),
    }).then(
      async (response) => {
        if (!response.ok) {
          setError(true);
          return;
        }
        const body: unknown = await response.json();
        const returnPath =
          body &&
          typeof body === "object" &&
          "return_path" in body &&
          typeof body.return_path === "string"
            ? body.return_path
            : "/";
        router.replace(returnPath);
      },
      () => setError(true),
    );
  }, [authCode, oauthState, router]);

  return (
    <AuthFrame>
      {error ? (
        <div className="text-center">
          <WarningCircleIcon aria-hidden="true" className="mx-auto size-9 text-destructive" />
          <h1 className="mt-3 text-xl font-semibold">钉钉登录未完成</h1>
          <p className="mt-2 text-sm text-muted-foreground" role="alert">
            授权已失效或当前钉钉身份尚未绑定，请重新开始登录。
          </p>
          <Button className="mt-5 h-11 w-full" onClick={() => router.replace("/login")}>
            返回登录
          </Button>
        </div>
      ) : (
        <div aria-busy="true" className="text-center">
          <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-primary">
            DingTalk OAuth
          </p>
          <h1 className="mt-3 text-xl font-semibold">正在验证钉钉身份</h1>
          <p className="mt-2 text-sm text-muted-foreground">请勿关闭此页面。</p>
        </div>
      )}
    </AuthFrame>
  );
}

export default function DingTalkCallbackPage() {
  return (
    <Suspense
      fallback={
        <AuthFrame>
          <div aria-busy="true" className="text-center">
            <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-primary">
              DingTalk OAuth
            </p>
            <h1 className="mt-3 text-xl font-semibold">正在读取授权结果</h1>
          </div>
        </AuthFrame>
      }
    >
      <DingTalkCallbackContent />
    </Suspense>
  );
}
