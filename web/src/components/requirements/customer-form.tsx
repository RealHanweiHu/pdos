"use client";

import { type FormEvent } from "react";

import { Button } from "@/components/ui/button";

import type { CustomerCreateInput } from "./requirement-api";

const controlClass =
  "mt-1 min-h-11 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 disabled:opacity-60";

export function CustomerForm({
  busy,
  error,
  onCancel,
  onSubmit,
}: {
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onSubmit: (input: CustomerCreateInput) => Promise<boolean>;
}) {
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    await onSubmit({
      code: String(data.get("code") ?? "").trim(),
      name: String(data.get("name") ?? "").trim(),
    });
  }

  return (
    <form onSubmit={submit}>
      <h2 className="font-semibold">新建客户</h2>
      <p className="mt-1 text-xs leading-5 text-muted-foreground">
        客户建立后可立即关联需求；编号在当前租户内唯一。
      </p>
      {error ? <p className="mt-3 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive" role="alert">{error}</p> : null}
      <div className="mt-4 space-y-4">
        <label className="block text-xs font-medium" htmlFor="customer-code">
          客户编号
          <input className={controlClass} disabled={busy} id="customer-code" maxLength={64} name="code" required />
        </label>
        <label className="block text-xs font-medium" htmlFor="customer-name">
          客户名称
          <input className={controlClass} disabled={busy} id="customer-name" maxLength={256} name="name" required />
        </label>
      </div>
      <div className="mt-5 flex gap-2">
        <Button className="h-11 flex-1" disabled={busy} type="submit">保存客户</Button>
        <Button className="h-11" disabled={busy} onClick={onCancel} type="button" variant="outline">取消</Button>
      </div>
    </form>
  );
}
