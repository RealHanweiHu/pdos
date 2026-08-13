import { useState } from "react";

import { Button } from "@/components/ui/button";

import type { ComplaintCreateInput } from "./quality-types";

const fieldClass =
  "min-h-11 w-full rounded-lg border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/20";

export function ComplaintForm({
  busy,
  ownerUserId,
  onSubmit,
}: {
  busy: boolean;
  ownerUserId: string;
  onSubmit: (input: ComplaintCreateInput) => Promise<boolean>;
}) {
  const [open, setOpen] = useState(false);

  async function submit(form: FormData) {
    const accepted = await onSubmit({
      title: String(form.get("title")),
      description: String(form.get("description")),
      source: String(form.get("source")) as ComplaintCreateInput["source"],
      severity: String(form.get("severity")) as ComplaintCreateInput["severity"],
      occurred_at: new Date(String(form.get("occurred_at"))).toISOString(),
      owner_user_id: ownerUserId,
      customer_reference: String(form.get("customer_reference") || "") || null,
      affected_scope: String(form.get("affected_scope") || "") || null,
    });
    if (accepted) setOpen(false);
  }

  if (!open) {
    return (
      <Button className="h-11" onClick={() => setOpen(true)}>
        新建 Complaint
      </Button>
    );
  }
  return (
    <form
      action={(form) => void submit(form)}
      className="rounded-lg border bg-card p-4"
      data-testid="complaint-form"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold">登记质量反馈</h3>
          <p className="mt-1 text-sm text-muted-foreground">报告时间与编号由服务器生成。</p>
        </div>
        <Button disabled={busy} onClick={() => setOpen(false)} type="button" variant="ghost">
          取消
        </Button>
      </div>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <label className="grid gap-1.5 text-sm font-medium">
          标题
          <input className={fieldClass} maxLength={512} name="title" required />
        </label>
        <label className="grid gap-1.5 text-sm font-medium">
          发生时间
          <input className={fieldClass} name="occurred_at" required type="datetime-local" />
        </label>
        <label className="grid gap-1.5 text-sm font-medium">
          来源
          <select className={fieldClass} defaultValue="field" name="source">
            <option value="customer">客户</option>
            <option value="field">现场</option>
            <option value="rma">RMA</option>
            <option value="internal">内部</option>
          </select>
        </label>
        <label className="grid gap-1.5 text-sm font-medium">
          严重度
          <select className={fieldClass} defaultValue="medium" name="severity">
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </label>
        <label className="grid gap-1.5 text-sm font-medium sm:col-span-2">
          问题描述
          <textarea className={fieldClass} maxLength={20_000} name="description" required rows={4} />
        </label>
        <label className="grid gap-1.5 text-sm font-medium">
          客户投诉编号（可选）
          <input className={fieldClass} maxLength={128} name="customer_reference" />
        </label>
        <label className="grid gap-1.5 text-sm font-medium">
          受影响范围（可选）
          <input className={fieldClass} maxLength={20_000} name="affected_scope" />
        </label>
      </div>
      <Button className="mt-4 h-11" disabled={busy} type="submit">
        {busy ? "正在登记…" : "登记 Complaint"}
      </Button>
    </form>
  );
}
