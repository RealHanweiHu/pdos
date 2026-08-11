"use client";

import { type FormEvent, useRef, useState } from "react";

import { Button } from "@/components/ui/button";

import type { SetupPayload, SubmissionResult } from "./auth-types";
import { FormField } from "./form-field";

export function SetupForm({
  busy,
  onSubmit,
}: {
  busy: boolean;
  onSubmit: (payload: SetupPayload) => Promise<SubmissionResult>;
}) {
  const [error, setError] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const passwordRef = useRef<HTMLInputElement>(null);

  async function submit(formData: FormData) {
    setError(null);
    const result = await onSubmit({
      tenant_slug: String(formData.get("tenant_slug") ?? ""),
      tenant_name: String(formData.get("tenant_name") ?? ""),
      username: String(formData.get("username") ?? ""),
      display_name: String(formData.get("display_name") ?? ""),
      password,
    });
    setPassword("");
    if (!result.ok) {
      setError(result.message);
      requestAnimationFrame(() => passwordRef.current?.focus());
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submit(new FormData(event.currentTarget));
  }

  return (
    <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
      {error ? (
        <div
          className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
          id="setup-error"
          role="alert"
        >
          {error}
        </div>
      ) : null}
      <FormField
        autoCapitalize="none"
        autoComplete="organization"
        disabled={busy}
        hint="小写字母、数字与连字符；创建后用于登录。"
        id="tenant-slug"
        label="租户标识"
        name="tenant_slug"
        placeholder="例如 beepump"
        required
      />
      <FormField
        autoComplete="organization-title"
        disabled={busy}
        id="tenant-name"
        label="组织名称"
        name="tenant_name"
        required
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField
          autoCapitalize="none"
          autoComplete="username"
          disabled={busy}
          id="username"
          label="管理员用户名"
          name="username"
          required
        />
        <FormField
          autoComplete="name"
          disabled={busy}
          id="display-name"
          label="显示名称"
          name="display_name"
          required
        />
      </div>
      <FormField
        aria-describedby={error ? "setup-error" : undefined}
        aria-invalid={Boolean(error)}
        autoComplete="new-password"
        disabled={busy}
        hint="至少 12 个字符；密码只发送到同源会话端点。"
        id="setup-password"
        label="管理员密码"
        minLength={12}
        name="password"
        onChange={(event) => setPassword(event.target.value)}
        ref={passwordRef}
        required
        type="password"
        value={password}
      />
      <Button className="h-11 w-full" disabled={busy} type="submit">
        {busy ? "正在创建…" : "创建工作区并登录"}
      </Button>
    </form>
  );
}
