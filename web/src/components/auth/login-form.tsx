"use client";

import { type FormEvent, useRef, useState } from "react";

import { Button } from "@/components/ui/button";

import type { LoginPayload, SubmissionResult } from "./auth-types";
import { FormField } from "./form-field";

export function LoginForm({
  busy,
  onSubmit,
}: {
  busy: boolean;
  onSubmit: (payload: LoginPayload) => Promise<SubmissionResult>;
}) {
  const [error, setError] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const passwordRef = useRef<HTMLInputElement>(null);

  async function submit(formData: FormData) {
    setError(null);
    const result = await onSubmit({
      tenant_slug: String(formData.get("tenant_slug") ?? ""),
      username: String(formData.get("username") ?? ""),
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
          id="login-error"
          role="alert"
        >
          {error}
        </div>
      ) : null}
      <FormField
        autoCapitalize="none"
        autoComplete="organization"
        disabled={busy}
        id="tenant-slug"
        label="租户标识"
        name="tenant_slug"
        placeholder="例如 beepump"
        required
      />
      <FormField
        autoCapitalize="none"
        autoComplete="username"
        disabled={busy}
        id="username"
        label="用户名"
        name="username"
        required
      />
      <FormField
        aria-describedby={error ? "login-error" : undefined}
        aria-invalid={Boolean(error)}
        autoComplete="current-password"
        disabled={busy}
        id="password"
        label="密码"
        name="password"
        onChange={(event) => setPassword(event.target.value)}
        ref={passwordRef}
        required
        type="password"
        value={password}
      />
      <Button className="h-11 w-full" disabled={busy} type="submit">
        {busy ? "正在验证…" : "登录"}
      </Button>
    </form>
  );
}
